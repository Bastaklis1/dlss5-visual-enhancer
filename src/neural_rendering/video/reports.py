from __future__ import annotations

from ...core import app_log
from .models import ConversionOptions, VideoConversionFailure, VideoConversionSuccess


def _write_video_batch_manifest(
    stamp: str,
    options: ConversionOptions,
    successes: list[VideoConversionSuccess],
    failures: list[VideoConversionFailure],
    cancelled: bool,
    *, batch_diagnostics: dict | None = None, output_dir: str | None = None,
) -> str:
    status = "cancelled" if cancelled else ("partial" if failures else "success")
    app_log.info("video-batch", f"{status} ok={len(successes)} failed={len(failures)}")
    return app_log.session_path()
