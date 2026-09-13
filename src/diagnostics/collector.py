"""Gathers diagnostic information about the GPU, runtime files, environment,
and recent render reports. Kept free of any Gradio dependency (matches the
rest of the app's models/ui split) so it can be tested and reused on its own.

Every public function here is defensive: diagnostics tooling that crashes
because the very thing it's meant to report on is broken (a missing GPU, a
missing runtime file, an unreadable report) is worse than useless. Each
function catches its own failure modes and returns that failure as data
(an "error" field, an empty list, etc.) rather than raising, so one broken
subsystem never takes down the rest of the tab.
"""
from __future__ import annotations

import importlib.metadata
import json
import platform
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..core.paths import (
    ADDON, DLSS_SUPERRES, FFMPEG, FFPROBE, HOST_DXGI, JOBS, LOGS, MPV,
    NEURAL_RUNTIME, OUTPUTS, WORKER, YTDLP,
)

from ..core.version import APP_VERSION

# (path, human label, required for core Neural Rendering/Upscale/Frame
# Interpolation features vs. optional Live-tab externals)
RUNTIME_FILES: tuple[tuple[Path, str, bool], ...] = (
    (FFMPEG, "FFmpeg", True),
    (FFPROBE, "FFprobe", True),
    (WORKER, "NGX worker (nvngx.dll)", True),
    (HOST_DXGI, "Host dxgi.dll", True),
    (ADDON, "RenoDX DLSS5 add-on", True),
    (DLSS_SUPERRES, "DLSS Super Resolution (nvngx_dlss.dll)", True),
    (NEURAL_RUNTIME, "DLSS Neural Rendering runtime (nvngx_dlssnr.dll)", True),
    (MPV, "mpv (Live tab)", False),
    (YTDLP, "yt-dlp (Live tab)", False),
)

# Distribution name on PyPI vs. the module name actually imported -- these
# differ for a couple of these, so a plain importlib.metadata.version(mod)
# would silently miss them.
_PACKAGES = (
    ("gradio", "gradio"),
    ("numpy", "numpy"),
    ("opencv-python", "cv2"),
    ("av", "av"),
    ("pillow", "PIL"),
    ("pillow-heif", "pillow_heif"),
    ("rawpy", "rawpy"),
)


def _file_status(path: Path) -> dict[str, Any]:
    try:
        exists = path.exists()
    except OSError as exc:
        return {"path": str(path), "exists": False, "error": str(exc)}
    if not exists:
        return {"path": str(path), "exists": False}
    try:
        stat = path.stat()
        return {
            "path": str(path),
            "exists": True,
            "size_bytes": stat.st_size,
            "modified": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(stat.st_mtime)),
        }
    except OSError as exc:
        return {"path": str(path), "exists": True, "error": str(exc)}


def collect_runtime_files() -> list[dict[str, Any]]:
    """Presence/size/modified time for every runtime file the app depends on."""
    rows = []
    for path, label, required in RUNTIME_FILES:
        status = _file_status(path)
        status["label"] = label
        status["required"] = required
        rows.append(status)
    return rows


def collect_gpus() -> dict[str, Any]:
    """All detected GPUs, plus which ones are currently configured for use.

    Returns {"gpus": [...], "error": str|None, "ai_gpu_uuid": str,
    "video_gpu_uuid": str} -- detection failure is reported as data, not
    raised, since "no GPU / driver tools unavailable" is itself a
    diagnostic finding, not an exceptional case to hide from this tab.
    """
    from ..core.gpu_detection import detect_gpus
    from ..settings.storage import processing_gpu_settings

    try:
        ai_gpu_uuid, video_gpu_uuid = processing_gpu_settings()
    except Exception as exc:
        ai_gpu_uuid, video_gpu_uuid = "auto", "auto"
        settings_error = str(exc)
    else:
        settings_error = None

    try:
        gpus = [dict(gpu) for gpu in detect_gpus()]
        return {
            "gpus": gpus, "error": None, "ai_gpu_uuid": ai_gpu_uuid,
            "video_gpu_uuid": video_gpu_uuid, "settings_error": settings_error,
        }
    except Exception as exc:
        return {
            "gpus": [], "error": str(exc), "ai_gpu_uuid": ai_gpu_uuid,
            "video_gpu_uuid": video_gpu_uuid, "settings_error": settings_error,
        }


def collect_runtime_bundle() -> dict[str, Any]:
    """Add-on/neural-runtime identities and the encoder inventory, reusing
    the already-computed process-wide PreparedRuntime when available so this
    doesn't re-run FFmpeg's encoder probe or re-warm files on every visit."""
    from ..core import runtime as runtime_module

    prepared = runtime_module._PREPARED
    if prepared is not None:
        return {
            "runtime_bundle": prepared.runtime_bundle,
            "encoder_inventory": prepared.encoder_inventory,
            "encoder_inventory_error": None,
        }
    # Startup hasn't completed prepare_runtime() yet (shouldn't normally
    # happen since build_app() calls it before any tab is built, but this
    # tab shouldn't assume that and crash if it somehow does).
    try:
        bundle = runtime_module.inspect_runtime_bundle()
    except Exception as exc:
        bundle = {"error": str(exc)}
    return {"runtime_bundle": bundle, "encoder_inventory": {}, "encoder_inventory_error": "not yet prepared"}


def _tool_version(path: Path, *args: str) -> str:
    if not path.exists():
        return "(not found)"
    try:
        result = subprocess.run(
            [str(path), *args], capture_output=True, text=True, timeout=10,
            encoding="utf-8", errors="replace",
        )
        first_line = (result.stdout or result.stderr or "").splitlines()
        return first_line[0].strip() if first_line else "(no output)"
    except (OSError, subprocess.TimeoutExpired) as exc:
        return f"(failed to run: {exc})"


def _dir_size_bytes(path: Path) -> int:
    total = 0
    try:
        for entry in path.rglob("*"):
            try:
                if entry.is_file():
                    total += entry.stat().st_size
            except OSError:
                continue
    except OSError:
        pass
    return total


def collect_environment() -> dict[str, Any]:
    """App/package versions, OS info, and disk usage for outputs/logs/jobs."""
    packages: dict[str, str] = {}
    for distribution_name, _module_name in _PACKAGES:
        try:
            packages[distribution_name] = importlib.metadata.version(distribution_name)
        except importlib.metadata.PackageNotFoundError:
            packages[distribution_name] = "(not installed)"

    disk_usage = {}
    try:
        total, used, free = shutil.disk_usage(OUTPUTS.parent if OUTPUTS.exists() else Path.cwd())
        disk_usage = {"total_bytes": total, "used_bytes": used, "free_bytes": free}
    except OSError as exc:
        disk_usage = {"error": str(exc)}

    return {
        "app_version": APP_VERSION,
        "python_version": sys.version.split()[0],
        "platform": platform.platform(),
        "machine": platform.machine(),
        "packages": packages,
        "ffmpeg_version": _tool_version(FFMPEG, "-version"),
        "ffprobe_version": _tool_version(FFPROBE, "-version"),
        "folder_sizes_bytes": {
            "outputs": _dir_size_bytes(OUTPUTS),
            "logs": _dir_size_bytes(LOGS),
            "jobs": _dir_size_bytes(JOBS),
        },
        "disk_usage": disk_usage,
    }


OPERATIONAL_LOG_NAMES = ("app.log", "cache_cleanup.log", "startup_error.log")

# Generation-report classification, in priority order (checked top to bottom;
# first match wins). Built by grepping every LOGS-writing call site in the
# codebase rather than assumed, since the three feature areas below each
# invented their own naming convention independently:
#   - Neural Rendering (image + video): "<output>.report.json",
#     "DLSS5_IMAGE_BATCH_<stamp>.manifest.json" / "..._VIDEO_BATCH_..."
#   - Frame Interpolation: "DLSSFG_<stem>_<stamp>.report.json",
#     "DLSSFG_BATCH_<stamp>.manifest.json", "DLSSFG_<stem>_<stamp>.failure.json"
#   - Upscale (image + video): plain "upscale-<stamp>.json" / "upscale-image-
#     <stamp>.json" for a single render, "upscale-batch-..." / "upscale-image-
#     batch-..." for a batch -- no .report./.manifest. suffix at all, which is
#     exactly why these were showing up as "Other".
#   - The shared write_failure_report() helper (used by Neural Rendering and
#     Upscale): "<operation>-failure-<stamp>.json" -- a *different* failure
#     naming scheme than Frame Interpolation's own ".failure.json".
#   - Live: "logs/live/<stamp>.json" -- distinguished by folder, not filename,
#     since the stamp alone carries no other identifying prefix.
def _classify_report(name: str, parent_name: str) -> str:
    if parent_name == "live":
        return "Live session report"
    if name.endswith(".failure.json") or "-failure-" in name:
        return "Failure report"
    if name.endswith(".manifest.json"):
        return "Batch manifest"
    if name.endswith(".report.json"):
        return "Render report"
    if name.startswith(("upscale-", "upscale-image-")) and name.endswith(".json"):
        return "Batch manifest" if "batch-" in name else "Render report"
    return "Other"


def collect_reports(limit: int = 200) -> list[dict[str, Any]]:
    """Recent generation reports under LOGS (recursive, to catch logs/live/),
    newest first, classified by filename pattern. Excludes the operational
    logs (app.log etc.) -- those are a different kind of thing and have
    their own collect_operational_logs()."""
    try:
        entries = [entry for entry in LOGS.rglob("*") if entry.is_file()]
    except OSError as exc:
        return [{"name": f"(could not list logs folder: {exc})", "kind": "Other",
                  "size_bytes": 0, "modified": "", "modified_ts": 0, "path": ""}]
    rows = []
    for entry in entries:
        if entry.name in OPERATIONAL_LOG_NAMES:
            continue
        try:
            stat = entry.stat()
        except OSError:
            continue
        rows.append({
            "name": entry.name,
            "kind": _classify_report(entry.name, entry.parent.name),
            "size_bytes": stat.st_size,
            "modified": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(stat.st_mtime)),
            "modified_ts": stat.st_mtime,
            "path": str(entry),
        })
    rows.sort(key=lambda row: row["modified_ts"], reverse=True)
    return rows[:limit]


def collect_operational_logs() -> list[dict[str, Any]]:
    """app.log, cache_cleanup.log, startup_error.log -- the app's own
    running logs, as opposed to the per-render generation reports above."""
    rows = []
    for name in OPERATIONAL_LOG_NAMES:
        path = LOGS / name
        status = _file_status(path)
        status["name"] = name
        rows.append(status)
    return rows


def open_containing_folder(path: str) -> str:
    """Open the OS file browser at the folder containing `path`. This is a
    local desktop app -- the Gradio server and the browser viewing it run on
    the same machine -- so opening a folder server-side is opening it on the
    user's own desktop, not some remote machine."""
    import subprocess
    import sys as _sys

    try:
        folder = Path(path).resolve().parent if Path(path).is_file() else Path(path).resolve()
        if not folder.is_dir():
            return f"Could not open: {folder} is not a folder."
        if _sys.platform == "win32":
            import os as _os
            _os.startfile(str(folder))  # noqa: S606 -- local desktop app, user-owned path
        elif _sys.platform == "darwin":
            subprocess.run(["open", str(folder)], check=True)
        else:
            subprocess.run(["xdg-open", str(folder)], check=True)
        return f"Opened {folder}"
    except (OSError, subprocess.CalledProcessError) as exc:
        return f"Could not open folder: {exc}"


def cleanup_old_reports(max_age_days: int = 30) -> dict[str, Any]:
    """Delete generation reports (render reports, batch manifests, failure
    reports, live session reports) older than max_age_days. Deliberately
    does NOT touch the operational logs (app.log etc.) -- those are
    continuously-appended single files, not per-render artifacts, and
    deleting one out from under an open file handle is asking for trouble
    on Windows for very little benefit (they're already small)."""
    cutoff = time.time() - max_age_days * 86400
    removed = 0
    freed_bytes = 0
    errors: list[str] = []
    for report in collect_reports(limit=100_000):
        if report["modified_ts"] >= cutoff:
            continue
        try:
            path = Path(report["path"])
            size = path.stat().st_size
            path.unlink()
            removed += 1
            freed_bytes += size
        except OSError as exc:
            errors.append(f"{report['name']}: {exc}")
    return {"removed": removed, "freed_bytes": freed_bytes, "errors": errors}


def _tail_text(path: Path, max_lines: int = 200) -> str:
    if not path.exists():
        return "(not present)"
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError as exc:
        return f"(could not read: {exc})"
    tail = lines[-max_lines:]
    prefix = f"... ({len(lines) - max_lines} earlier lines omitted) ...\n" if len(lines) > max_lines else ""
    return prefix + "\n".join(tail) if tail else "(empty)"


def generate_diagnostic_bundle() -> str:
    """Write a single self-contained Markdown file combining the diagnostic
    summary and the tail of the operational logs -- built for pasting
    directly into a GitHub issue body, or attaching as a file. On-demand
    only (called from a button), not generated automatically -- there's no
    ongoing value in having this exist unless someone's about to use it."""
    summary = build_diagnostic_summary()
    app_log_tail = _tail_text(LOGS / "app.log")
    cache_log_tail = _tail_text(LOGS / "cache_cleanup.log", max_lines=50)

    content = (
        "# DLSS 5 Visual Enhancer — diagnostic bundle\n\n"
        f"Generated: {time.strftime('%Y-%m-%d %H:%M:%S')}\n\n"
        "## Diagnostic summary\n\n"
        f"```\n{summary}\n```\n\n"
        "## app.log (tail)\n\n"
        f"```\n{app_log_tail}\n```\n\n"
        "## cache_cleanup.log (tail)\n\n"
        f"```\n{cache_log_tail}\n```\n"
    )

    stamp = time.strftime("%Y%m%d-%H%M%S")
    bundle_path = LOGS / f"diagnostic-bundle-{stamp}.md"
    LOGS.mkdir(parents=True, exist_ok=True)
    bundle_path.write_text(content, encoding="utf-8")
    return str(bundle_path)


def read_report(path: str) -> str:
    """Read one report file for display. Refuses to read outside LOGS."""
    try:
        resolved = Path(path).resolve()
        if LOGS.resolve() not in resolved.parents:
            return "Refused: this file is outside the logs folder."
        text = resolved.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return f"Could not read this file: {exc}"
    if resolved.suffix == ".json":
        try:
            return json.dumps(json.loads(text), indent=2)
        except json.JSONDecodeError:
            return text  # show raw text rather than fail on a malformed report
    return text


def build_diagnostic_summary() -> str:
    """One copyable plain-text block for pasting into a bug report."""
    gpu_info = collect_gpus()
    bundle_info = collect_runtime_bundle()
    env = collect_environment()
    files = collect_runtime_files()

    lines = [
        f"DLSS 5 Visual Enhancer {env['app_version']} -- diagnostic summary",
        f"Generated: {time.strftime('%Y-%m-%d %H:%M:%S')}",
        "",
        f"OS: {env['platform']} ({env['machine']})",
        f"Python: {env['python_version']}",
        f"FFmpeg: {env['ffmpeg_version']}",
        f"FFprobe: {env['ffprobe_version']}",
        "Packages: " + ", ".join(f"{name}={version}" for name, version in env["packages"].items()),
        "",
        "GPUs:",
    ]
    if gpu_info["error"]:
        lines.append(f"  Detection failed: {gpu_info['error']}")
    else:
        for gpu in gpu_info["gpus"]:
            marker = []
            if gpu["uuid"] == gpu_info["ai_gpu_uuid"] or gpu_info["ai_gpu_uuid"] == "auto":
                marker.append("AI candidate" if gpu_info["ai_gpu_uuid"] == "auto" else "AI (configured)")
            lines.append(
                f"  [{gpu['index']}] {gpu['name']} | driver {gpu['driver']} | "
                f"{gpu['memory_mb']} MB | RTX-compatible: {gpu['ai_compatible']}"
                + (f" | {' '.join(marker)}" if marker else "")
            )
    lines.append(f"  Configured AI Processing GPU: {gpu_info['ai_gpu_uuid']}")
    lines.append(f"  Configured Video Encoding GPU: {gpu_info['video_gpu_uuid']}")
    lines += ["", "Encoder inventory:"]
    for name, available in bundle_info["encoder_inventory"].items():
        lines.append(f"  {name}: {'available' if available else 'not available'}")
    lines += ["", "Runtime files:"]
    for row in files:
        state = "OK" if row.get("exists") else "MISSING"
        req = "required" if row["required"] else "optional"
        lines.append(f"  [{state}] {row['label']} ({req})")
    return "\n".join(lines)
