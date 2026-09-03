from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Callable, Iterable

from ..core.jobs import Cancelled, active_job
from ..core.paths import LOGS
from ..core.runtime import prepare_runtime
from .models import (
    ConversionOptions, VideoBatchResult, VideoConversionFailure, VideoConversionSuccess,
)
from .processor import _BATCH_CONTEXT, convert_video
from .reports import _write_video_batch_manifest

def convert_videos(
    input_paths: Iterable[str | os.PathLike[str]],
    options: ConversionOptions | None = None,
    progress: Callable[[float, str], None] | None = None,
) -> VideoBatchResult:
    """Convert videos sequentially while holding one cancellable GPU batch slot."""
    options = options or ConversionOptions()
    paths = [Path(path).resolve() for path in input_paths]
    if not paths:
        raise ValueError("Choose at least one video.")

    prepared_runtime = prepare_runtime()
    LOGS.mkdir(exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S") + f"-{time.time_ns() % 1_000_000:06d}"
    successes: list[VideoConversionSuccess] = []
    failures: list[VideoConversionFailure] = []
    cancelled = False
    total = len(paths)

    with active_job() as controller:
        if getattr(_BATCH_CONTEXT, "controller", None) is not None:
            raise RuntimeError("A video batch is already active on this worker thread.")
        _BATCH_CONTEXT.controller = controller
        _BATCH_CONTEXT.prepared_runtime = prepared_runtime
        try:
            for index, path in enumerate(paths):
                position = index + 1
                prefix = f"[{position}/{total}] {path.name}"
                if controller.cancel.is_set():
                    cancelled = True
                    failures.extend(
                        VideoConversionFailure(
                            queued_index,
                            str(queued),
                            "Cancelled before rendering.",
                            cancelled=True,
                        )
                        for queued_index, queued in enumerate(paths[index:], start=index)
                    )
                    break

                def report_item(
                    value: float,
                    message: str,
                    *,
                    item_index: int = index,
                    item_prefix: str = prefix,
                ) -> None:
                    bounded = min(1.0, max(0.0, float(value)))
                    overall = (item_index + bounded) / total
                    if progress:
                        progress(overall, f"{item_prefix} — {message}")

                if progress:
                    progress(index / total, f"{prefix} — starting")
                try:
                    result = convert_video(path, options, progress=report_item)
                except Cancelled:
                    cancelled = True
                    failures.append(
                        VideoConversionFailure(
                            index,
                            str(path),
                            "Cancelled during rendering.",
                            cancelled=True,
                        )
                    )
                    failures.extend(
                        VideoConversionFailure(
                            queued_index,
                            str(queued),
                            "Cancelled before rendering.",
                            cancelled=True,
                        )
                        for queued_index, queued in enumerate(paths[position:], start=position)
                    )
                    break
                except Exception as exc:
                    failures.append(VideoConversionFailure(index, str(path), str(exc)))
                    if progress:
                        progress(position / total, f"{prefix} — failed")
                    continue

                successes.append(VideoConversionSuccess(index, str(path), result))
                if progress:
                    progress(position / total, f"{prefix} — complete")
        finally:
            del _BATCH_CONTEXT.controller
            del _BATCH_CONTEXT.prepared_runtime

    manifest_path = _write_video_batch_manifest(
        stamp, options, successes, failures, cancelled
    )
    if progress:
        progress(1.0, "Cancelled" if cancelled else "Complete")
    return VideoBatchResult(successes, failures, cancelled, manifest_path)
