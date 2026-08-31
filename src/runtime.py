from __future__ import annotations

import re
import struct
import subprocess
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

import cv2
import numpy as np


ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "bin" / "runtime"
FFMPEG = ROOT / "bin" / "ffmpeg" / "bin" / "ffmpeg.exe"
FFPROBE = ROOT / "bin" / "ffmpeg" / "bin" / "ffprobe.exe"
WORKER = RUNTIME / "nvngx.dll"  # Signed-snippet caller checks require this image name.
OUTPUTS = ROOT / "outputs"
LOGS = ROOT / "logs"
JOBS = ROOT / "jobs"

VIDEO_MAGIC = 0x33563544
SETUP_MAGIC = 0x33505553
FRAME_MAGIC = 0x314D5246
OUT_MAGIC = 0x3154554F
VIDEO_HEADER_FORMAT = "<13I4f"
SETUP_RESPONSE_FORMAT = "<11I"


class Cancelled(RuntimeError):
    pass


class JobController:
    """Own cancellation state and subprocesses for one render."""

    def __init__(self) -> None:
        self.cancel = threading.Event()
        self._lock = threading.Lock()
        self._processes: list[subprocess.Popen] = []

    def register(self, process: subprocess.Popen) -> None:
        with self._lock:
            self._processes.append(process)

    def unregister(self, process: subprocess.Popen) -> None:
        with self._lock:
            if process in self._processes:
                self._processes.remove(process)

    def stop(self) -> None:
        self.cancel.set()
        self.terminate_processes()

    def terminate_processes(self) -> None:
        with self._lock:
            processes = list(self._processes)
        for process in processes:
            if process.poll() is None:
                try:
                    process.terminate()
                except OSError:
                    pass


_RENDER_LOCK = threading.Lock()
_ACTIVE_LOCK = threading.Lock()
_ACTIVE: JobController | None = None


@contextmanager
def active_job() -> Iterator[JobController]:
    """Claim the single GPU render slot and always release its resources."""
    global _ACTIVE
    if not _RENDER_LOCK.acquire(blocking=False):
        raise RuntimeError("Another GPU render is already running.")
    controller = JobController()
    with _ACTIVE_LOCK:
        _ACTIVE = controller
    try:
        yield controller
    finally:
        controller.terminate_processes()
        with _ACTIVE_LOCK:
            if _ACTIVE is controller:
                _ACTIVE = None
        _RENDER_LOCK.release()


def cancel_active_job() -> str:
    with _ACTIVE_LOCK:
        controller = _ACTIVE
    if controller is None:
        return "No render is running."
    controller.stop()
    return "Stop requested; incomplete output will be removed and completed batch files retained."


def drain_text(stream, lines: list[str]) -> None:
    for raw in iter(stream.readline, b""):
        lines.append(raw.decode("utf-8", "replace").rstrip())


def resize_fit(rgba: np.ndarray, width: int, height: int) -> np.ndarray:
    source_height, source_width = rgba.shape[:2]
    scale = min(width / source_width, height / source_height)
    fit_width = max(1, min(width, int(round(source_width * scale))))
    fit_height = max(1, min(height, int(round(source_height * scale))))
    resized = cv2.resize(rgba, (fit_width, fit_height), interpolation=cv2.INTER_LANCZOS4)
    canvas = np.zeros((height, width, 4), dtype=np.uint8)
    canvas[..., 3] = 255
    x = (width - fit_width) // 2
    y = (height - fit_height) // 2
    canvas[y : y + fit_height, x : x + fit_width] = resized
    return canvas


def rotate_frame(frame: np.ndarray, rotation: int) -> np.ndarray:
    if rotation == 90:
        return np.ascontiguousarray(np.rot90(frame, 3))
    if rotation == 180:
        return np.ascontiguousarray(np.rot90(frame, 2))
    if rotation == 270:
        return np.ascontiguousarray(np.rot90(frame, 1))
    return frame


def detect_gpu() -> dict:
    command = [
        "nvidia-smi",
        "--query-gpu=name,driver_version,memory.total,compute_cap",
        "--format=csv,noheader,nounits",
    ]
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError(
            "NVIDIA driver tools are unavailable; an RTX GPU and current driver are required."
        ) from exc
    candidates = []
    for line in result.stdout.splitlines():
        parts = [part.strip() for part in line.split(",")]
        if len(parts) >= 4 and "RTX" in parts[0].upper():
            candidates.append(parts)
    if not candidates:
        raise RuntimeError("No supported NVIDIA RTX GPU was detected.")
    name, driver, memory, capability = candidates[0]
    match = re.search(r"RTX\s+(\d{2})", name.upper())
    generation = int(match.group(1)) if match else 0
    if generation < 30:
        raise RuntimeError(f"{name} is outside the supported RTX 30/40/50 scope.")
    return {
        "name": name,
        "driver": driver,
        "memory_mb": int(memory),
        "compute_capability": capability,
        "generation": generation,
        "beta": generation == 30,
    }


def validate_runtime_files() -> None:
    required = [
        FFMPEG,
        FFPROBE,
        WORKER,
        RUNTIME / "dxgi.dll",
        RUNTIME / "renodx-dlss5.addon64",
        RUNTIME / "nvngx_dlss.dll",
        RUNTIME / "nvngx_dlssnr.dll",
    ]
    missing = [str(path) for path in required if not path.exists()]
    if missing:
        raise RuntimeError("Portable runtime is incomplete:\n" + "\n".join(missing))


def _read_exact(stream, size: int) -> bytes:
    chunks = bytearray()
    while len(chunks) < size:
        block = stream.read(size - len(chunks))
        if not block:
            raise EOFError(f"Native worker stopped after {len(chunks)} of {size} output bytes")
        chunks.extend(block)
    return bytes(chunks)


class DLSSFrameSession:
    """A reusable native DLSSNR feature-18 frame stream."""

    def __init__(
        self,
        *,
        input_width: int,
        input_height: int,
        output_width: int,
        output_height: int,
        frame_count: int,
        warmup_frames: int,
        factor: float,
        mode: dict[str, str | int],
        native_settings: dict[str, int | float],
        controller: JobController,
    ) -> None:
        self.controller = controller
        self.worker_logs: list[str] = []
        self.closed = False
        self.factor = factor
        self.mode = mode
        self.native_settings = native_settings
        creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        self.worker = subprocess.Popen(
            [str(WORKER), "--video"],
            cwd=RUNTIME,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            creationflags=creation_flags,
        )
        controller.register(self.worker)
        assert self.worker.stderr is not None
        self.worker_thread = threading.Thread(
            target=drain_text,
            args=(self.worker.stderr, self.worker_logs),
            daemon=True,
        )
        self.worker_thread.start()
        native = native_settings
        header = struct.pack(
            VIDEO_HEADER_FORMAT,
            VIDEO_MAGIC,
            input_width,
            input_height,
            output_width,
            output_height,
            int(warmup_frames),
            frame_count,
            int(mode["perf_quality"]),
            native["profile"],
            native["preset"],
            native["style"],
            native["auto_mask"],
            native["ui_correction"],
            native["intensity"],
            native["local_tone"],
            native["local_structure"],
            native["skin_structure"],
        )
        assert self.worker.stdin is not None and self.worker.stdout is not None
        try:
            self.worker.stdin.write(header)
            self.worker.stdin.flush()
            try:
                setup_data = _read_exact(
                    self.worker.stdout, struct.calcsize(SETUP_RESPONSE_FORMAT)
                )
            except EOFError as exc:
                worker_code = self.worker.wait(timeout=10)
                self.worker_thread.join(timeout=2)
                details = (
                    "\n".join(self.worker_logs[-60:])
                    or "The worker produced no diagnostic output."
                )
                raise RuntimeError(
                    "The native worker is incompatible with the version-3 upscaling protocol "
                    f"or failed during DLSS setup (exit {worker_code}):\n{details}"
                ) from exc
            (
                setup_magic,
                setup_ok,
                self.setup_result,
                self.render_width,
                self.render_height,
                negotiated_output_width,
                negotiated_output_height,
                self.minimum_width,
                self.minimum_height,
                self.maximum_width,
                self.maximum_height,
            ) = struct.unpack(SETUP_RESPONSE_FORMAT, setup_data)
            if setup_magic != SETUP_MAGIC:
                raise RuntimeError(
                    "The installed native worker does not support the version-3 upscaling protocol. "
                    "Rebuild it."
                )
            if not setup_ok:
                details = "\n".join(self.worker_logs[-60:])
                raise RuntimeError(
                    f"DLSS {mode['name']} is unavailable for {output_width}×{output_height} "
                    f"(NGX 0x{self.setup_result:08X}). Choose a lower upscaling factor or update "
                    "the NVIDIA driver."
                    + (f"\n{details}" if details else "")
                )
            if (negotiated_output_width, negotiated_output_height) != (
                output_width,
                output_height,
            ):
                raise RuntimeError(
                    "The native worker returned output dimensions different from the request."
                )
            if self.render_width < 64 or self.render_height < 64:
                raise RuntimeError(
                    f"DLSS returned an unsupported render size: "
                    f"{self.render_width}×{self.render_height}; both dimensions must be at least "
                    "64 pixels."
                )
            self.output_width = output_width
            self.output_height = output_height
        except Exception:
            self.abort()
            raise

    def process(
        self,
        *,
        index: int,
        rgba: np.ndarray,
        motion: np.ndarray,
        reset: bool,
        pts: int,
    ) -> tuple[np.ndarray, int]:
        if self.controller.cancel.is_set():
            raise Cancelled("Render stopped by user.")
        assert self.worker.stdin is not None and self.worker.stdout is not None
        frame_header = struct.pack("<4Iq", FRAME_MAGIC, index, int(reset), 0, pts)
        self.worker.stdin.write(frame_header)
        self.worker.stdin.write(np.ascontiguousarray(rgba, dtype=np.uint8).tobytes())
        self.worker.stdin.write(np.ascontiguousarray(motion, dtype=np.float16).tobytes())
        self.worker.stdin.flush()
        try:
            result_header = _read_exact(self.worker.stdout, struct.calcsize("<5Iq"))
        except EOFError as exc:
            worker_code = self.worker.wait(timeout=10)
            self.worker_thread.join(timeout=2)
            details = (
                "\n".join(self.worker_logs[-60:])
                or "The worker produced no diagnostic output."
            )
            raise RuntimeError(
                f"Native DLSS worker exited with code {worker_code} before frame {index} "
                f"completed:\n{details}"
            ) from exc
        magic, out_index, ok, byte_count, ngx_result, out_pts = struct.unpack(
            "<5Iq", result_header
        )
        expected = self.output_width * self.output_height * 4
        if magic != OUT_MAGIC or not ok or out_index != index or byte_count != expected:
            raise RuntimeError(f"Invalid native worker response for frame {index}")
        if ngx_result != 1:
            raise RuntimeError(
                f"Direct feature-18 evaluation failed on frame {index}: 0x{ngx_result:08X}"
            )
        output = np.frombuffer(
            _read_exact(self.worker.stdout, byte_count), dtype=np.uint8
        ).reshape(self.output_height, self.output_width, 4)
        return output.copy(), out_pts

    def close(self) -> None:
        if self.closed:
            return
        if self.worker.stdin and not self.worker.stdin.closed:
            self.worker.stdin.close()
        worker_code = self.worker.wait(timeout=60)
        self.worker_thread.join(timeout=2)
        self.controller.unregister(self.worker)
        self.closed = True
        if worker_code:
            raise RuntimeError(
                "Native DLSS worker failed:\n" + "\n".join(self.worker_logs[-40:])
            )

    def abort(self) -> None:
        if self.closed:
            return
        if self.worker.poll() is None:
            try:
                self.worker.terminate()
                self.worker.wait(timeout=10)
            except (OSError, subprocess.TimeoutExpired):
                try:
                    self.worker.kill()
                except OSError:
                    pass
        self.worker_thread.join(timeout=2)
        self.controller.unregister(self.worker)
        self.closed = True


def verify_feature_18(worker_logs: list[str]) -> dict[str, object]:
    reshade_log_path = RUNTIME / "ReShade.log"
    reshade_log = (
        reshade_log_path.read_text(encoding="utf-8", errors="replace")
        if reshade_log_path.exists()
        else ""
    )
    feature_created = "feature 18 created via the signed snippet" in reshade_log
    feature_evaluated = "inline feature 18 evaluation succeeded" in reshade_log
    runtime_initialized = "signed DLSSNR 310.8.0 D3D12 runtime initialized" in reshade_log
    if not (runtime_initialized and feature_created and feature_evaluated):
        evidence = "\n".join(
            line
            for line in reshade_log.splitlines()
            if "DLSS 5 Neural Rendering" in line
            or "DLSSNR" in line
            or "feature 18" in line
        )
        raise RuntimeError(
            "The carrier render completed, but signed DLSSNR feature-18 execution was not "
            "verified.\n"
            + (evidence[-6000:] or "ReShade produced no DLSSNR evidence.")
        )
    carrier_matches = re.findall(
        r"DLSS carrier ready:.*result=0x([0-9A-Fa-f]{8})", "\n".join(worker_logs)
    )
    return {
        "reshade_log": reshade_log,
        "nr_upscaling_active": "[upscaling]" in reshade_log and feature_evaluated,
        "nr_native_fallback": "NR upscaling fell back to native" in reshade_log,
        "carrier_create_result": (
            f"0x{carrier_matches[-1].upper()}" if carrier_matches else "unreported"
        ),
        "evidence": [
            line
            for line in reshade_log.splitlines()
            if "signed DLSSNR" in line
            or "feature 18 created" in line
            or "feature 18 evaluation succeeded" in line
            or "NR upscaling fell back" in line
        ],
    }
