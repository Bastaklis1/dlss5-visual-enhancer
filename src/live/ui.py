from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import gradio as gr

from ..settings.models import UISettings, parse_automatic_mask
from ..neural_rendering.video.ui import build_neural_controls
from ..neural_rendering.composition_ui import CompositionWidgets, build_composition_widgets
from .models import (LIVE_FPS_CHOICES, LIVE_MAX_HEIGHT_CHOICES,
                     LIVE_MAX_HEIGHTS, LIVE_SEGMENT_CHOICES, LIVE_SOURCE_QUALITY_CHOICES)
from .pipeline import is_live_running, live_status, start_live_session, stop_live_session
from .models import LiveOptions


def start_live(
    source: str,
    nr_style: str,
    nr_intensity: float,
    nr_passes: float,
    local_tone_strength: float,
    local_structure_strength: float,
    skin_structure_strength: float,
    upscaling_factor: float,
    automatic_mask: str,
    nr_color_strength: float,
    tone_preservation: float,
    face_skin_protection: float,
    grain_preservation: float,
    mask_feather: float,
    shimmer_suppression: float,
    nr_mask: object | None,
    nr_gpu_mode: bool,
    max_height: str,
    segment_seconds: str,
    open_mpv: bool,
    target_fps: str = "Auto",
    buffer_seconds: float = 6.0,
    source_quality: str = "Auto",
    source_mode: str = "Online",
    local_video: str | None = None,
) -> str:
    if is_live_running():
        raise gr.Error("A Live session is already running; Stop it first.")
    if source_mode == "Local":
        if not local_video or not Path(local_video).is_file():
            raise gr.Error("Select a local video before starting Live.")
        selected_source = str(local_video)
    elif source_mode == "Online":
        selected_source = (source or "").strip()
        if not selected_source:
            raise gr.Error("Enter an online URL, or select Local to use the uploaded video.")
    else:
        raise gr.Error("Choose Online or Local as the source.")
    try:
        height = int(max_height)
    except (TypeError, ValueError):
        height = 720
    try:
        segment = int(segment_seconds)
    except (TypeError, ValueError):
        segment = 2
    try:
        factor = float(upscaling_factor)
    except (TypeError, ValueError):
        raise gr.Error("Choose a valid scale.") from None
    try:
        auto_mask = parse_automatic_mask(automatic_mask)
    except ValueError as exc:
        raise gr.Error(str(exc)) from exc
    options = LiveOptions(
        source=selected_source,
        nr_style=nr_style,
        nr_intensity=float(nr_intensity),
        nr_passes=int(nr_passes),
        local_tone_strength=float(local_tone_strength),
        local_structure_strength=float(local_structure_strength),
        skin_structure_strength=float(skin_structure_strength),
        automatic_mask=auto_mask,
        nr_color_strength=float(nr_color_strength),
        tone_preservation=float(tone_preservation),
        face_skin_protection=float(face_skin_protection),
        grain_preservation=float(grain_preservation),
        shimmer_suppression=float(shimmer_suppression),
        mask_feather=int(mask_feather),
        nr_mask=nr_mask,
        nr_gpu_mode=nr_gpu_mode,
        max_height=height if height in LIVE_MAX_HEIGHTS else 720,
        upscaling_factor=factor,
        segment_seconds=segment if segment in (1, 2, 4, 6) else 2,
        open_mpv=bool(open_mpv),
        target_fps=target_fps,
        buffer_seconds=float(buffer_seconds),
        source_quality=source_quality,
    )
    try:
        info = start_live_session(options)
    except RuntimeError as exc:
        raise gr.Error(str(exc)) from exc
    return info.status


def stop_live() -> str:
    try:
        info = stop_live_session()
    except RuntimeError as exc:
        raise gr.Error(str(exc)) from exc
    return info.status


def refresh_live_status() -> str:
    info = live_status()
    if not info.running and info.status == "Idle.":
        return "Idle. Enter a source and press Start Live."
    parts = [info.status]
    if info.playlist_url:
        parts.append(f"Playlist: {info.playlist_url}")
    if info.mpv_running:
        parts.append(f"MPV: {info.player_dropped_frames} dropped | {info.rebuffer_events} rebuffer events | "
                     f"A/V offset {info.av_sync_ms:+.1f} ms")
    if info.output_size:
        parts.append(f"Received {info.source_size} -> Processing {info.input_size} -> Output {info.output_size} | {info.encoder}")
    if info.source_quality_note:
        parts.append(info.source_quality_note)
    parts.append(f"DLSS effects: {info.effects_status}")
    if info.applied_at_pts is not None:
        parts.append(f"Latest applied change starts at video time {info.applied_at_pts / 90000:.2f}s; "
                     "buffered video keeps its previous appearance until then.")
    if info.effects_error:
        parts.append(f"Effect update: {info.effects_error}")
    if info.processing and info.source_fps:
        parts.append(f"Source: {info.source_fps:.2f} fps. Scene analysis: {info.guide_ms:.1f} ms | "
                     f"DLSS: {info.dlss_ms:.1f} ms | Encode transport: {info.encode_ms:.1f} ms")
    if info.report_path:
        parts.append(f"Diagnostics: {info.report_path}")
    return "\n".join(parts)


@dataclass(slots=True)
class LiveTab:
    source: object
    neural: list[object]
    composition: CompositionWidgets
    mask_state: object
    gpu_mode: object
    max_height: object
    segment: object
    open_mpv: object
    start: object
    stop: object
    status: object
    target_fps: object
    buffer: object
    source_quality: object
    source_mode: object
    local_video: object

    @property
    def settings_inputs(self) -> list[object]:
        # Shared DLSS values only (persisted globally + mirrored); the rest
        # of the Live options are session-local.
        return [*self.neural]


def build_live_tab(settings: UISettings, gpu_mode_state: object, mask_state: object) -> LiveTab:
    height_labels = {"1440": "1440p (2K)", "2160": "2160p (4K)"}
    with gr.Row():
        with gr.Column(scale=3):
            source_mode = gr.Radio(
                choices=["Online", "Local"], value="Online", label="Source",
            )
            source = gr.Textbox(
                label="Online URL",
                placeholder="Direct stream URL, YouTube or Twitch URL",
            )
            local_video = gr.File(
                label="Local video", file_count="single", file_types=["video"],
                type="filepath", interactive=True,
            )
            with gr.Row():
                start = gr.Button("Start Live", variant="primary")
                stop = gr.Button("Stop", variant="stop")
            with gr.Column(elem_classes=["neural-controls-unified"]):
                neural = build_neural_controls(settings)
                composition = build_composition_widgets()
            with gr.Row():
                source_quality = gr.Dropdown(
                    choices=[("Auto (follow Max input height)" if height == "Auto" else
                              height_labels.get(height, f"{height}p"), height)
                             for height in LIVE_SOURCE_QUALITY_CHOICES],
                    value="Auto", label="Source quality",
                )
                max_height = gr.Dropdown(
                    choices=[(height_labels.get(height, height), height) for height in LIVE_MAX_HEIGHT_CHOICES],
                    value="720",
                    label="Max input height",
                )
                segment = gr.Dropdown(
                    choices=list(LIVE_SEGMENT_CHOICES),
                    value="2",
                    label="Segment length (s)",
                )
            with gr.Row():
                target_fps = gr.Dropdown(
                    choices=list(LIVE_FPS_CHOICES), value="Auto", label="Live frame rate",
                )
                buffer = gr.Slider(
                    minimum=2, maximum=30, step=1, value=6, label="Playback buffer (seconds)",
                )
            open_mpv = gr.Checkbox(
                value=True,
                label="Open in MPV",
            )
        with gr.Column(scale=3):
            status = gr.Textbox(
                label="Live status",
                value="Idle. Enter a source and press Start Live.",
                interactive=False,
                lines=10,
            )
    tab = LiveTab(
        source, neural, composition, mask_state, gpu_mode_state, max_height, segment,
        open_mpv, start, stop, status, target_fps, buffer, source_quality,
        source_mode, local_video,
    )
    start.click(
        start_live,
        inputs=[source, *neural, mask_state, gpu_mode_state, max_height, segment, open_mpv, target_fps, buffer,
                source_quality, source_mode, local_video],
        outputs=status,
        concurrency_limit=1,
        show_progress="full",
    )
    stop.click(stop_live, outputs=status, queue=False, show_progress="hidden")
    timer = gr.Timer(0.5)
    timer.tick(refresh_live_status, outputs=status, queue=False, show_progress="hidden")
    return tab
