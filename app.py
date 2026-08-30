from __future__ import annotations

import traceback
from pathlib import Path

import gradio as gr

from dlss5_converter.core import (
    ConversionOptions,
    OUTPUTS,
    cancel_active_job,
    convert_video,
    detect_gpu,
)


def gpu_banner() -> str:
    try:
        gpu = detect_gpu()
        beta = " — RTX 30 beta mode" if gpu["beta"] else ""
        return (
            f"**Ready:** {gpu['name']} · driver {gpu['driver']} · "
            f"{gpu['memory_mb'] // 1024} GB VRAM{beta}"
        )
    except Exception as exc:
        return f"**Not ready:** {exc}"


def render_video(
    input_path: str,
    profile: str,
    codec: str,
    container: str,
    quality: str,
    progress=gr.Progress(track_tqdm=False),
):
    if not input_path:
        raise gr.Error("Choose a video first.")
    options = ConversionOptions(
        profile=profile,
        codec=codec,
        container=container,
        quality=quality,
    )

    def report(value: float, message: str) -> None:
        progress(value, desc=message)

    try:
        result = convert_video(input_path, options, progress=report)
    except Exception as exc:
        traceback.print_exc()
        raise gr.Error(str(exc)) from exc
    preview = result.output_path if Path(result.output_path).suffix.lower() == ".mp4" else None
    status = (
        f"Complete: {result.frames} frames processed on {result.gpu} in "
        f"{result.elapsed_seconds:.1f}s. All {result.nr_count_evidence} frames returned success "
        "from direct feature 18."
    )
    return preview, result.output_path, result.report_path, status


with gr.Blocks(title="DLSS 5 Video Converter") as demo:
    gr.Markdown(
        "# DLSS 5 Video Converter\n"
        "Render an entire video through the experimental NVIDIA DLSS 5 Neural Rendering runtime. "
        "The supplied `nvngx_dlssnr.dll` is the only image-transforming stage. Optical flow supplies required motion vectors; "
        "there is no DLAA, ReShade, RenoDX, depth enhancer, resize, sharpening, or denoising fallback.\n\n"
        "> Experimental reverse-engineered integration. RTX 40/50 are primary; RTX 30 is beta. A failed feature-18 call aborts the render."
    )
    gr.Markdown(gpu_banner())
    with gr.Row():
        with gr.Column(scale=3):
            source = gr.Video(label="Input video", sources=["upload"], format=None)
        with gr.Column(scale=2):
            profile = gr.Radio(
                ["Faithful", "Natural", "Strong / Cinematic"], value="Strong / Cinematic", label="Native DLSS 5 profile"
            )
            quality = gr.Radio(["High", "Balanced", "Small"], value="High", label="Encoding quality")

    with gr.Accordion("Output format", open=False):
        with gr.Row():
            codec = gr.Dropdown(["H.264", "HEVC", "AV1"], value="H.264", label="Video codec")
            container = gr.Dropdown(["MP4", "MKV"], value="MP4", label="Container")
        gr.Checkbox(
            value=False,
            interactive=False,
            label="Preserve HDR (disabled: verified feature-18 path is currently RGBA8; HDR input is safely output as SDR)",
        )

    with gr.Row():
        render = gr.Button("Render whole video", variant="primary")
        stop = gr.Button("Stop", variant="stop")
    status = gr.Textbox(label="Status", interactive=False)
    preview = gr.Video(label="MP4 preview", interactive=False)
    with gr.Row():
        output_file = gr.File(label="Rendered video")
        report_file = gr.File(label="Render report")

    inputs = [
        source, profile, codec, container, quality,
    ]
    render.click(render_video, inputs=inputs, outputs=[preview, output_file, report_file, status], concurrency_limit=1)
    stop.click(cancel_active_job, outputs=status, queue=False)


if __name__ == "__main__":
    OUTPUTS.mkdir(exist_ok=True)
    demo.queue(default_concurrency_limit=1).launch(
        server_name="127.0.0.1",
        inbrowser=True,
        share=False,
        allowed_paths=[str(OUTPUTS.resolve())],
        show_error=True,
    )
