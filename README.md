# DLSS 5 Video Converter (Experimental)

This Windows application renders every frame through the supplied DLSS 5 Neural Rendering feature-18 runtime and writes a new video with the original audio and metadata. Optical flow supplies only the current-to-previous motion vectors required by the model. No heuristic depth, masks, sharpening, denoising, resizing, DLAA, ReShade, or RenoDX stage modifies the image.

## Start

Double-click `start.bat`. The portable Gradio interface opens at `http://127.0.0.1:7860`. No installation or internet connection is required.

1. Upload a video.
2. **Strong / Cinematic** is selected by default. Faithful and Natural remain available for a milder result.
3. Click **Render whole video**.
4. Download the video and its JSON report. Every output frame must carry an exact successful feature-18 result or the render is rejected.

Outputs and their JSON reports are written to the automatically created `outputs` directory. Temporary job data is removed after every completed, failed, or cancelled render. **Stop** terminates the decoder, DLSS worker, and encoder and removes incomplete output.

## GPU support

- RTX 40/50: primary support target.
- RTX 30: allowed in beta mode and may be extremely slow.
- RTX 20, non-RTX NVIDIA, AMD, and Intel GPUs: rejected for DLSS processing.

The native host explicitly selects an NVIDIA adapter on hybrid AMD/Intel systems. It was functionally tested here on an RTX 4060 Ti with driver 616.56.

## Output and limitations

- Source resolution is always preserved. There is no pre-upscaling or DLSS Super Resolution pass.
- H.264 NVENC MP4 with AAC is the default. HEVC, AV1, and MKV are available when the GPU and container support them. H.264/HEVC fall back to software encoding when NVENC is unavailable.
- Variable timestamps are carried in a NUT stream to FFmpeg. The first video stream is processed; audio and metadata are remuxed, and MKV also preserves compatible subtitle streams.
- HDR preservation is disabled because the verified path is RGBA8. HDR files are handled as SDR rather than being incorrectly tagged as HDR.
- Optical-flow motion cannot equal engine-provided object motion. Fast motion, occlusions, thin objects, and cuts may show temporal artifacts.
- The supplied modified model is experimental. Its original snippet checks that its caller is named `nvngx.dll`, so the standalone executable intentionally uses that filename; it is not NVIDIA's NGX core DLL.

## Source layout

- `app.py` — Gradio interface.
- `dlss5_converter` — probing, optical-flow motion generation, D5V2 worker protocol, encoding, cancellation, and verification.
- `native/DLSS5-Feeder` — MIT reference host adapted with NVIDIA-adapter selection and video-frame transport.
- `native/NVIDIA-DLSS` — the NVIDIA NGX headers, required x64 import library, and license needed to rebuild the worker.
- `bin/runtime` — clean offline runtime containing only the standalone worker image and supplied DLSSNR model.
