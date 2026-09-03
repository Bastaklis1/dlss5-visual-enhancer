from __future__ import annotations

import os
import time
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable

import cv2
import numpy as np

from ..core.gpu_selection import resolve_runtime_ai_gpu
from ..core.jobs import Cancelled, active_job
from ..core.naming import output_filename, require_available_output, validate_rename
from ..core.paths import LOGS, OUTPUTS
from ..core.runtime import (
    DLSSFrameSession, prepare_runtime, resize_fit, resolve_native_settings,
    resolve_output_size, resolve_upscaling_mode, verify_feature_18, write_failure_report,
)
from .decoder import _DecodedImage, decode_image, probe_image
from .encoder import _encode_image
from .models import (
    IMAGE_EXTENSIONS, IMAGE_FORMATS, RAW_EXTENSIONS, ImageBatchResult, ImageConversionFailure,
    ImageConversionOptions, ImageConversionResult,
)
from .reports import _ImageReportData, _build_manifest_and_zip, _report_data, _write_report

@dataclass(slots=True)
class _ImageProbe:
    index: int
    path: Path
    width: int
    height: int
    output_width: int
    output_height: int
    decoded: _DecodedImage | None = None

def _validate_options(options: ImageConversionOptions) -> ImageConversionOptions:
    if options.output_format not in IMAGE_FORMATS:
        raise ValueError(f"Unknown image output format: {options.output_format!r}.")
    if isinstance(options.quality, bool):
        raise ValueError("Image quality must be an integer from 1 to 100.")
    try:
        quality = int(options.quality)
    except (TypeError, ValueError) as exc:
        raise ValueError("Image quality must be an integer from 1 to 100.") from exc
    if quality != options.quality or not 1 <= quality <= 100:
        raise ValueError("Image quality must be an integer from 1 to 100.")
    validate_rename(options.rename_mode, options.custom_suffix)
    resolve_native_settings(options)
    resolve_upscaling_mode(options.upscaling_factor)
    return options

def _output_path(
    source: Path,
    output_format: str,
    stamp: str,
    index: int,
    rename_mode: str,
    custom_suffix: str,
) -> Path:
    suffix = IMAGE_EXTENSIONS[output_format]
    safe_stem = source.stem.strip().rstrip(".") or "image"
    return OUTPUTS / output_filename(
        source,
        suffix,
        rename_mode,
        custom_suffix,
        f"{safe_stem}_DLSS5_IMAGE_{stamp}-{index + 1:04d}",
    )

def convert_images(
    input_paths: Iterable[str | os.PathLike[str]],
    options: ImageConversionOptions | None = None,
    progress: Callable[[float, str], None] | None = None,
) -> ImageBatchResult:
    options = options or ImageConversionOptions()
    neural = _validate_options(options)
    paths = [Path(path).resolve() for path in input_paths]
    if not paths:
        raise ValueError("Choose at least one image.")
    prepared_runtime = prepare_runtime()
    OUTPUTS.mkdir(exist_ok=True)
    LOGS.mkdir(exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S") + f"-{time.time_ns() % 1_000_000:06d}"
    batch_started = time.perf_counter()

    def _report_progress(value: float, desc: str) -> None:
        if progress is None:
            return
        try:
            v = float(value)
            v = 0.0 if v < 0 else (1.0 if v > 1 else v)
            elapsed = time.perf_counter() - batch_started
            if 0.01 < v < 0.99 and elapsed > 0.5:
                eta = elapsed * (1 - v) / max(v, 1e-6)
                desc = f"{desc} - Time Remaining: {eta:.1f}s"
            progress(v, desc)
        except Exception:
            try:
                progress(value, desc)
            except Exception:
                pass

    failures_by_index: dict[int, ImageConversionFailure] = {}
    probes: list[_ImageProbe] = []
    for index, path in enumerate(paths):
        try:
            decoded: _DecodedImage | None = None
            if path.suffix.lower() in {*RAW_EXTENSIONS, ".svg"}:
                decoded = decode_image(path)
                height, width = decoded.rgba.shape[:2]
                if width < 64 or height < 64:
                    raise ValueError(
                        f"{path.name} is {width}×{height}; DLSS requires both input "
                        "dimensions to be at least 64 pixels."
                    )
            else:
                width, height = probe_image(path)
            output_width, output_height = resolve_output_size(
                width, height, options.upscaling_factor
            )
            probes.append(
                _ImageProbe(
                    index, path, width, height, output_width, output_height, decoded
                )
            )
        except Exception as exc:
            failures_by_index[index] = ImageConversionFailure(str(path), str(exc))

    planned_outputs: dict[int, Path] = {}
    reserved_outputs: set[str] = set()
    available_probes: list[_ImageProbe] = []
    for probe in probes:
        output = _output_path(
            probe.path,
            options.output_format,
            stamp,
            probe.index,
            options.rename_mode,
            options.custom_suffix,
        )
        output_key = str(output.resolve()).casefold()
        try:
            require_available_output(output)
            if output_key in reserved_outputs:
                raise FileExistsError(
                    f"More than one input would create {output.name}. "
                    "Choose Auto naming or use unique input names."
                )
        except Exception as exc:
            failures_by_index[probe.index] = ImageConversionFailure(
                str(probe.path), str(exc)
            )
            continue
        reserved_outputs.add(output_key)
        planned_outputs[probe.index] = output
        available_probes.append(probe)
    probes = available_probes

    if not probes:
        manifest_path, zip_path = _build_manifest_and_zip(
            stamp, options, [], list(failures_by_index.values()), False
        )
        return ImageBatchResult([], list(failures_by_index.values()), False, manifest_path, zip_path)

    groups: dict[tuple[int, int], list[_ImageProbe]] = {}
    for probe in probes:
        groups.setdefault((probe.output_width, probe.output_height), []).append(probe)

    successes_by_index: dict[int, ImageConversionResult] = {}
    cancelled = False
    gpu: dict | None = None
    processed_total = 0
    decode_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="dlss5-image-decode")
    encode_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="dlss5-image-encode")
    with active_job() as controller:
        gpu = resolve_runtime_ai_gpu(
            prepared_runtime.gpus, prepared_runtime.runtime_bundle, options.ai_gpu_uuid
        )
        runtime_bundle = prepared_runtime.runtime_bundle
        _report_progress(0.0, f"Starting feature 18 on {gpu['display_name']}")
        total = len(probes)
        factor, mode = resolve_upscaling_mode(neural.upscaling_factor)
        native_settings = resolve_native_settings(neural)
        try:
            for (output_width, output_height), group in groups.items():
                cursor = 0
                while cursor < len(group):
                    if controller.cancel.is_set():
                        cancelled = True
                        break
                    remaining = group[cursor:]
                    first = remaining[0]
                    try:
                        session = DLSSFrameSession(
                            input_width=first.width,
                            input_height=first.height,
                            output_width=output_width,
                            output_height=output_height,
                            frame_count=len(remaining),
                            warmup_frames=neural.warmup_frames,
                            factor=factor,
                            mode=mode,
                            native_settings=native_settings,
                            gpu=gpu,
                            runtime_bundle=runtime_bundle,
                            controller=controller,
                        )
                    except Exception as exc:
                        controller.terminate_processes()
                        report_path = write_failure_report(
                            operation="image-batch-dlss-setup",
                            source="; ".join(str(item.path) for item in remaining),
                            error=exc,
                            gpu=gpu,
                            runtime_bundle=runtime_bundle,
                        )
                        failure = f"{exc}\nDiagnostic report: {report_path}"
                        for item in remaining:
                            failures_by_index[item.index] = ImageConversionFailure(str(item.path), failure)
                        break
    
                    segment: list[
                        tuple[
                            _ImageProbe,
                            ImageConversionResult,
                            _ImageReportData,
                            Future[list[str]],
                            float,
                        ]
                    ] = []
                    sent = 0
                    motion = np.zeros(
                        (session.render_height, session.render_width, 2), dtype=np.float16
                    )
                    interrupted = False
                    close_error: Exception | None = None
                    decode_future: Future[_DecodedImage] | None = decode_executor.submit(
                        lambda probe=group[cursor]: probe.decoded or decode_image(probe.path)
                    )
                    while cursor < len(group):
                        item = group[cursor]
                        started = time.perf_counter()
                        if controller.cancel.is_set():
                            cancelled = True
                            interrupted = True
                            session.abort()
                            break
                        _report_progress(processed_total / max(1, total), f"Preparing {item.path.name}")
                        try:
                            assert decode_future is not None
                            decoded = decode_future.result()
                            item.decoded = None
                            next_cursor = cursor + 1
                            decode_future = (
                                decode_executor.submit(
                                    lambda probe=group[next_cursor]:
                                    probe.decoded or decode_image(probe.path)
                                )
                                if next_cursor < len(group)
                                else None
                            )
                        except Exception as exc:
                            failures_by_index[item.index] = ImageConversionFailure(str(item.path), str(exc))
                            cursor += 1
                            processed_total += 1
                            session.abort()
                            interrupted = True
                            break
                        try:
                            render_rgba = resize_fit(
                                decoded.rgba, session.render_width, session.render_height
                            )
                            processed, _pts = session.process(
                                index=sent,
                                rgba=render_rgba,
                                motion=motion,
                                reset=True,
                                pts=sent,
                            )
                            alpha = (
                                decoded.alpha
                                if decoded.alpha.shape == (output_height, output_width)
                                else cv2.resize(
                                    decoded.alpha,
                                    (output_width, output_height),
                                    interpolation=cv2.INTER_LANCZOS4,
                                )
                            )
                            processed[..., 3] = alpha
                            output = planned_outputs[item.index]
                            result = ImageConversionResult(
                                str(item.path),
                                str(output),
                                "",
                                time.perf_counter() - started,
                                str(gpu["display_name"]),
                                item.width,
                                item.height,
                                session.render_width,
                                session.render_height,
                                output_width,
                                output_height,
                                float(options.upscaling_factor),
                                str(session.mode["name"]),
                                options.output_format,
                                options.dlss_model_preset,
                                session.applied_dlss_model_preset,
                                list(decoded.warnings),
                            )
                            encoding = encode_executor.submit(
                                _encode_image, output, processed, options, decoded.metadata
                            )
                            segment.append(
                                (item, result, _report_data(decoded), encoding, started)
                            )
                            # Keep at most two full rendered frames queued for encoding.
                            # Completed futures retain only their small warning list.
                            if len(segment) > 2:
                                segment[-3][3].result()
                            sent += 1
                        except Cancelled:
                            cancelled = True
                            session.abort()
                            interrupted = True
                            break
                        except Exception as exc:
                            session.abort()
                            report_path = write_failure_report(
                                operation="image-render",
                                source=str(item.path),
                                error=exc,
                                gpu=gpu,
                                runtime_bundle=runtime_bundle,
                                worker_code=session.worker.poll(),
                                worker_logs=session.worker_logs,
                                reshade_lines=session.reshade_diagnostics(),
                            )
                            failures_by_index[item.index] = ImageConversionFailure(
                                str(item.path), f"{exc}\nDiagnostic report: {report_path}"
                            )
                            interrupted = True
                            cursor += 1
                            processed_total += 1
                            break
                        cursor += 1
                        processed_total += 1
                        _report_progress(processed_total / total, f"Rendered {item.path.name}")
    
                    if not segment and interrupted:
                        if cancelled:
                            break
                        continue
                    if not interrupted:
                        try:
                            session.close()
                        except Exception as exc:
                            close_error = exc
                    try:
                        if close_error:
                            raise close_error
                        evidence = verify_feature_18(
                            session.worker_logs, session.reshade_log_text()
                        )
                        assert gpu is not None
                        for item, result, decoded, encoding, item_started in segment:
                            result.warnings.extend(encoding.result())
                            result.elapsed_seconds = time.perf_counter() - item_started
                        for item, result, decoded, _encoding, _item_started in segment:
                            result.report_path = _write_report(
                                result, options, decoded, gpu, session, evidence
                            )
                            successes_by_index[item.index] = result
                    except Exception as exc:
                        report_path = write_failure_report(
                            operation="image-batch-verification",
                            source="; ".join(str(item.path) for item, *_rest in segment),
                            error=exc,
                            gpu=gpu,
                            runtime_bundle=runtime_bundle,
                            worker_code=session.worker.poll(),
                            worker_logs=session.worker_logs,
                            reshade_lines=session.reshade_diagnostics(),
                        )
                        failure = f"{exc}\nDiagnostic report: {report_path}"
                        for item, result, _decoded, encoding, _item_started in segment:
                            if not encoding.done():
                                encoding.cancel()
                            output = Path(result.output_path)
                            if output.exists():
                                output.unlink()
                            failures_by_index[item.index] = ImageConversionFailure(str(item.path), failure)
                    if cancelled:
                        break
                if cancelled:
                    break
        finally:
            decode_executor.shutdown(wait=True, cancel_futures=True)
            encode_executor.shutdown(wait=True, cancel_futures=True)
    if cancelled:
        completed = set(successes_by_index) | set(failures_by_index)
        for probe in probes:
            if probe.index not in completed:
                failures_by_index[probe.index] = ImageConversionFailure(
                    str(probe.path), "Cancelled before rendering."
                )
    successes = [successes_by_index[index] for index in sorted(successes_by_index)]
    failures = [failures_by_index[index] for index in sorted(failures_by_index)]
    manifest_path, zip_path = _build_manifest_and_zip(
        stamp, options, successes, failures, cancelled
    )
    _report_progress(1.0, "Cancelled" if cancelled else "Complete")
    return ImageBatchResult(successes, failures, cancelled, manifest_path, zip_path)
