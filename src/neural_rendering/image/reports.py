from __future__ import annotations

import os
import zipfile
from dataclasses import dataclass
from pathlib import Path

from ...core import app_log
from ...core.paths import OUTPUTS
from ...core.disk_paths import OutputFile
from ...core.jobs import Cancelled
from ...core.runtime import DLSSFrameSession
from .decoder import _DecodedImage
from .models import ImageConversionFailure, ImageConversionOptions, ImageConversionResult


@dataclass(slots=True)
class _ImageReportData:
    decoder: str
    metadata: dict[str, object]
    warnings: list[str]


@dataclass(frozen=True, slots=True)
class _SessionReportData:
    minimum_width: int
    minimum_height: int
    maximum_width: int
    maximum_height: int
    setup_result: int
    native_settings: dict[str, int | float]
    runtime_bundle: dict[str, object]
    bridge_status: dict[str, object]
    bridge_log: tuple[str, ...]


def _report_data(decoded: _DecodedImage) -> _ImageReportData:
    """Keep diagnostics without retaining decoded pixel/alpha arrays."""
    return _ImageReportData(decoded.decoder, decoded.metadata, list(decoded.warnings))


def snapshot_session(session: DLSSFrameSession) -> _SessionReportData:
    """Detach structured report inputs from the live bridge session."""
    return _SessionReportData(
        minimum_width=session.minimum_width,
        minimum_height=session.minimum_height,
        maximum_width=session.maximum_width,
        maximum_height=session.maximum_height,
        setup_result=session.setup_result,
        native_settings=dict(session.native_settings),
        runtime_bundle=dict(session.runtime_bundle),
        bridge_status=session.structured_status(),
        bridge_log=tuple(session.bridge_logs),
    )


def _write_report(
    result: ImageConversionResult,
    options: ImageConversionOptions,
    decoded: _ImageReportData,
    gpu: dict,
    session: _SessionReportData,
    evidence: dict[str, object],
    *, metadata_diagnostics: dict | None = None,
) -> str:
    app_log.info(
        "image-render",
        f"done src={Path(result.input_path).name} out={Path(result.output_path).name} "
        f"elapsed={result.elapsed_seconds:.1f}s",
    )
    return app_log.session_path()


def update_report_performance(result: ImageConversionResult) -> None:
    """No-op: per-job report files no longer exist (see session log)."""
    return


class IncrementalImageArchive:
    """Build the uncompressed batch ZIP while later images are on the GPU."""

    def __init__(self, path: Path, controller=None):
        self.path = path
        self.controller = controller
        self.output_file = OutputFile(path)
        self.archive = zipfile.ZipFile(
            self.output_file.temporary, "w", compression=zipfile.ZIP_STORED, allowZip64=True,
        )
        self.closed = False
        self.error: str | None = None
        self.count = 0

    def add(self, source_path: str | os.PathLike[str]) -> None:
        if self.closed or self.error:
            return
        source = Path(source_path)
        try:
            info = zipfile.ZipInfo.from_file(source, arcname=source.name)
            info.compress_type = zipfile.ZIP_STORED
            with source.open("rb") as input_stream, self.archive.open(info, "w", force_zip64=True) as output_stream:
                while True:
                    if self.controller is not None and self.controller.cancel.is_set():
                        raise Cancelled("ZIP creation cancelled.")
                    chunk = input_stream.read(1024 * 1024)
                    if not chunk:
                        break
                    output_stream.write(chunk)
            self.count += 1
        except Cancelled:
            raise
        except Exception as exc:
            # ZIP is a convenience artifact; never turn an already valid image into
            # a failed render because archive I/O failed.
            self.error = str(exc)

    def finish(self, *, cancelled: bool) -> str | None:
        if self.closed:
            return None
        self.closed = True
        try:
            try:
                self.archive.close()
            except Exception as exc:
                self.error = self.error or str(exc)
            if not self.count or cancelled or self.error or (self.controller is not None and self.controller.cancel.is_set()):
                return None
            self.output_file.publish()
            return str(self.path)
        finally:
            self.output_file.cleanup()

    def abort(self) -> None:
        if self.closed:
            return
        self.closed = True
        try:
            try:
                self.archive.close()
            except Exception:
                pass
        finally:
            self.output_file.cleanup(rollback=True)


def _build_manifest(
    stamp: str,
    options: ImageConversionOptions,
    successes: list[ImageConversionResult],
    failures: list[ImageConversionFailure],
    cancelled: bool,
    *, output_dir: Path | None = None, batch_diagnostics: dict | None = None,
    archive_error: str | None = None,
) -> str:
    status = "cancelled" if cancelled else ("partial" if failures else "success")
    app_log.info(
        "image-batch",
        f"{status} ok={len(successes)} failed={len(failures)}"
        + (f" archive_warning={archive_error}" if archive_error else ""),
    )
    return app_log.session_path()


def _build_manifest_and_zip(
    stamp: str,
    options: ImageConversionOptions,
    successes: list[ImageConversionResult],
    failures: list[ImageConversionFailure],
    cancelled: bool,
    *, create_zip: bool = True, output_dir: Path | None = None, batch_diagnostics: dict | None = None,
    controller=None,
) -> tuple[str, str | None]:
    """Compatibility helper for callers that do not use IncrementalImageArchive."""
    manifest_path = _build_manifest(
        stamp, options, successes, failures, cancelled,
        output_dir=output_dir, batch_diagnostics=batch_diagnostics,
    )
    if not successes or not create_zip:
        return manifest_path, None
    zip_path = (output_dir or OUTPUTS) / f"DLSS5_IMAGE_BATCH_{stamp}.zip"
    archive = IncrementalImageArchive(zip_path, controller)
    try:
        for item in successes:
            archive.add(item.output_path)
        result = archive.finish(cancelled=cancelled)
        if archive.error:
            manifest_path = _build_manifest(
                stamp, options, successes, failures, cancelled,
                output_dir=output_dir, batch_diagnostics=batch_diagnostics,
                archive_error=archive.error,
            )
        return manifest_path, result
    except Cancelled:
        archive.abort()
        return _build_manifest(
            stamp, options, successes, failures, True,
            output_dir=output_dir, batch_diagnostics=batch_diagnostics,
        ), None
