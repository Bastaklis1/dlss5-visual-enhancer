from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
RUNTIME = ROOT / "bin" / "runtime"
HOST_DIR = RUNTIME / "host"
DLSS_DIR = RUNTIME / "dlss"
DLSSG_DIR = RUNTIME / "dlssg"
FFMPEG = ROOT / "bin" / "ffmpeg" / "bin" / "ffmpeg.exe"
FFPROBE = ROOT / "bin" / "ffmpeg" / "bin" / "ffprobe.exe"
WORKER = HOST_DIR / "nvngx.dll"  # Signed-snippet caller checks require this image name.
ADDON = HOST_DIR / "renodx-dlss5.addon64"
HOST_DXGI = HOST_DIR / "dxgi.dll"
RESHADE_LOG = HOST_DIR / "ReShade.log"
DLSS_SUPERRES = DLSS_DIR / "nvngx_dlss.dll"
# The RenoDX add-on only discovers the signed NR runtime next to itself in
# host/, so NEURAL_RUNTIME lives there even though it is a DLSS component.
NEURAL_RUNTIME = HOST_DIR / "nvngx_dlssnr.dll"
OUTPUTS = ROOT / "outputs"
LOGS = ROOT / "logs"
JOBS = ROOT / "jobs"
CONFIG_DIR = ROOT / "config"
CONFIG_PATH = CONFIG_DIR / "config.ini"
