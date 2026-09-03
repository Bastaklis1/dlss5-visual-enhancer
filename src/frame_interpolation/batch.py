from __future__ import annotations

import json
import os
import time
from dataclasses import asdict
from pathlib import Path
from typing import Callable, Iterable

from ..core.jobs import Cancelled, active_job
from ..core.paths import LOGS
from .models import (
    FrameInterpolationBatchResult, FrameInterpolationFailure, FrameInterpolationOptions,
    FrameInterpolationSuccess,
)
from .processor import _BATCH_CONTEXT, _json_safe, interpolate_video

def interpolate_videos(
    input_paths: Iterable[str | os.PathLike[str]],
    options: FrameInterpolationOptions | None = None,
    progress: Callable[[float, str], None] | None = None,
) -> FrameInterpolationBatchResult:
    options = options or FrameInterpolationOptions()
    paths = [Path(path).resolve() for path in input_paths]
    if not paths:
        raise ValueError("Choose at least one video.")
    stamp = time.strftime("%Y%m%d-%H%M%S") + f"-{time.time_ns() % 1_000_000:06d}"
    successes: list[FrameInterpolationSuccess] = []
    failures: list[FrameInterpolationFailure] = []
    cancelled = False
    with active_job() as controller:
        _BATCH_CONTEXT.controller = controller
        try:
            for index, path in enumerate(paths):
                if controller.cancel.is_set():
                    cancelled = True
                    failures.extend(
                        FrameInterpolationFailure(i, str(item), "Cancelled before rendering.", True)
                        for i, item in enumerate(paths[index:], start=index)
                    )
                    break
                def item_progress(value: float, message: str, *, position=index) -> None:
                    if progress:
                        progress((position + value) / len(paths), f"[{position + 1}/{len(paths)}] {message}")
                try:
                    result = interpolate_video(path, options, item_progress)
                    successes.append(FrameInterpolationSuccess(index, str(path), result))
                except Cancelled as exc:
                    cancelled = True
                    failures.append(FrameInterpolationFailure(index, str(path), str(exc), True))
                    failures.extend(
                        FrameInterpolationFailure(
                            queued_index,
                            str(queued),
                            "Cancelled before rendering.",
                            True,
                        )
                        for queued_index, queued in enumerate(
                            paths[index + 1 :], start=index + 1
                        )
                    )
                    break
                except Exception as exc:
                    failures.append(FrameInterpolationFailure(index, str(path), str(exc)))
        finally:
            del _BATCH_CONTEXT.controller
    manifest = {
        "status": "cancelled" if cancelled else ("partial" if failures else "success"),
        "options": _json_safe(asdict(options)),
        "successes": [asdict(item) for item in successes],
        "failures": [asdict(item) for item in failures],
    }
    LOGS.mkdir(exist_ok=True)
    manifest_path = LOGS / f"DLSSFG_BATCH_{stamp}.manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return FrameInterpolationBatchResult(successes, failures, cancelled, str(manifest_path.resolve()))
