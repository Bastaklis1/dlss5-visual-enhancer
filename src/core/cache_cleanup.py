from __future__ import annotations

"""Automatic cleanup of stale app-local Gradio caches and job leftovers.

Official Gradio cleanup (``gr.Blocks(delete_cache=...)``) handles tracked
session files while the server runs and on graceful shutdown. Crash-orphaned
files are covered here by an age-gated startup sweep over only this install's
portable locations:

1. ``<app>/temp/gradio`` (Gradio uploads/cache plus UI-owned temp artifacts).
2. Orphaned ``<app>/jobs/*`` per-render dirs left behind by killed runs.

No system/user temp directory is inspected or migrated. This build is isolated
from previous installations. Final deliverables in ``OUTPUTS/`` and anything
in ``LOGS/`` are never touched. Every failure is swallowed per-entry so
cleanup can never block startup.
"""

import os
import shutil
import time
from pathlib import Path

from .paths import GRADIO_TEMP, JOBS

# Agreed retention: sweep hourly while running (via Blocks delete_cache),
# treat anything older than 24h as stale (startup sweep + periodic sweep).
CACHE_SWEEP_INTERVAL_SECONDS = 3600
CACHE_MAX_AGE_SECONDS = 24 * 3600


def resolve_gradio_temp_dir() -> Path | None:
    """Return this installation's fixed app-local Gradio temp directory."""
    try:
        resolved = GRADIO_TEMP.resolve()
    except OSError:
        return None
    return resolved if resolved.is_dir() else None


def _entry_age_seconds(stat_result: os.stat_result, now: float) -> float:
    # Stale only when BOTH mtime and ctime are old: protects files that were
    # created long ago but are still being written/read, and vice versa.
    newest = max(stat_result.st_mtime, getattr(stat_result, "st_ctime", stat_result.st_mtime))
    return now - newest


def _remove_entry(path: Path) -> int:
    """Remove one top-level cache entry; return bytes freed (best effort)."""
    try:
        if path.is_symlink() or path.is_file():
            try:
                size = path.stat().st_size
            except OSError:
                size = 0
            path.unlink(missing_ok=True)
            return size
        if path.is_dir():
            size = 0
            try:
                for root, _dirs, files in os.walk(path):
                    for name in files:
                        try:
                            size += (Path(root) / name).stat().st_size
                        except OSError:
                            continue
            except OSError:
                pass
            shutil.rmtree(path, ignore_errors=True)
            return size
    except OSError:
        pass
    return 0


def sweep_dir_by_age(root: Path, max_age_seconds: int) -> tuple[int, int]:
    """Remove direct children of ``root`` older than ``max_age_seconds``.

    Returns ``(removed_count, freed_bytes)``. Never raises, never removes
    ``root`` itself, never follows symlinks.
    """
    removed = 0
    freed = 0
    try:
        entries = list(os.scandir(root))
    except OSError:
        return (0, 0)
    now = time.time()
    for entry in entries:
        try:
            stat_result = os.stat(entry.path, follow_symlinks=False)
        except OSError:
            continue
        if _entry_age_seconds(stat_result, now) <= max_age_seconds:
            continue
        freed += _remove_entry(Path(entry.path))
        removed += 1
    return (removed, freed)


def cleanup_old_caches(
    max_age_seconds: int = CACHE_MAX_AGE_SECONDS,
    logs_dir: Path | None = None,
) -> dict[str, int]:
    """Sweep all stale cache locations. Never raises; logs one summary line.

    Returns ``{"removed": N, "freed_bytes": B}`` for optional status display.
    """
    started = time.time()
    removed_total = 0
    freed_total = 0

    gradio_dir = resolve_gradio_temp_dir()
    if gradio_dir is not None:
        try:
            removed, freed = sweep_dir_by_age(gradio_dir, max_age_seconds)
            removed_total += removed
            freed_total += freed
        except Exception:
            pass

    try:
        if JOBS.is_dir():
            removed, freed = sweep_dir_by_age(JOBS, max_age_seconds)
            removed_total += removed
            freed_total += freed
    except Exception:
        pass

    elapsed = time.time() - started
    try:
        from . import app_log

        app_log.info(
            "cache",
            f"removed={removed_total} freed_mb={freed_total / (1024 * 1024):.1f} "
            f"elapsed_s={elapsed:.1f}",
        )
    except Exception:
        pass
    return {"removed": removed_total, "freed_bytes": freed_total}
