from __future__ import annotations

import os
from dataclasses import replace
from pathlib import Path
from typing import Callable, Iterable

from ..core import app_log
from ..core.batch_progress import BatchItemUpdate, BatchProgress
from ..core.disk_paths import prepare_output_dir
from ..core.jobs import Cancelled, JobController, active_job
from .models import FrameInterpolationBatchResult, FrameInterpolationFailure, FrameInterpolationOptions, FrameInterpolationSuccess
from . import processor


def interpolate_videos(
    input_paths: Iterable[str | os.PathLike[str]],
    options: FrameInterpolationOptions | None = None,
    progress: Callable[[float, str], None] | None = None,
    *, output_dir: str | os.PathLike[str] | None = None,
    controller: JobController | None = None,
    on_item_update: Callable[[BatchItemUpdate], None] | None = None,
) -> FrameInterpolationBatchResult:
    options = replace(options) if options else FrameInterpolationOptions()
    paths = [Path(path).resolve() for path in input_paths]
    if not paths:
        raise ValueError("Choose at least one video.")
    controller = controller or JobController()
    reporter = BatchProgress(paths, on_item_update, progress)
    successes, failures = [], []
    try:
        destination = prepare_output_dir(output_dir, default=processor.OUTPUTS)
        with active_job(controller):
            processor._BATCH_CONTEXT.controller = controller
            try:
                for index, path in enumerate(paths):
                    if controller.cancel.is_set():
                        break
                    reporter.advance(index)
                    try:
                        result = processor.interpolate_video(
                            path, options, lambda value, message, i=index: reporter.advance(i, value, message),
                            output_dir=destination,
                        )
                    except Exception as exc:
                        cancelled = isinstance(exc, Cancelled) or controller.cancel.is_set()
                        failures.append(FrameInterpolationFailure(index, str(path), str(exc), cancelled))
                        reporter.fail(index, exc, cancelled=cancelled)
                        if cancelled:
                            controller.stop()
                            break
                    else:
                        successes.append(FrameInterpolationSuccess(index, str(path), result))
                        reporter.complete(index, result.output_path, f"{result.output_frames} frames; report: {result.report_path}")
            finally:
                del processor._BATCH_CONTEXT.controller
        cancelled = controller.cancel.is_set()
        if cancelled:
            for item in reporter.items:
                if item.state == "Queued":
                    failures.append(FrameInterpolationFailure(item.index, item.input_path, "Cancelled before rendering.", True))
            reporter.skip_from(0)
        status = "cancelled" if cancelled else ("partial" if failures else "success")
        app_log.info("frame-interp-batch", f"{status} ok={len(successes)} failed={len(failures)}")
        manifest_path = app_log.session_path()
        reporter.finish(cancelled=cancelled, manifest_path=manifest_path)
        return FrameInterpolationBatchResult(successes, failures, cancelled, manifest_path)
    except BaseException as exc:
        reporter.finish(cancelled=controller.cancel.is_set(), error=str(exc))
        raise
