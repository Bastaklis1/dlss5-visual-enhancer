# DLSS 5 Visual Enhancer

Experimental, source-only Windows application for applying a DLSS 5 Neural Rendering feature-18 pipeline to images and video through a local Gradio interface. It is an independent community project and is not affiliated with, sponsored by, or endorsed by NVIDIA, ReShade, RenoDX, FFmpeg, or their contributors.

<img width="1411" height="368" alt="image" src="https://github.com/user-attachments/assets/fc5aceb8-c010-4bf0-be9e-f5e38b29fffa" />

### Original

https://github.com/user-attachments/assets/f27f61a3-cad3-4278-af66-eb11c54600fb

### DLSS 5

https://github.com/user-attachments/assets/d91591a9-2df1-4b4b-b18f-bd4dff73d5bc

## Main features

- **Images:** batch processing with per-file success/failure results, enhanced previews, individual downloads, a ZIP of successful outputs, batch manifests, and diagnostic JSON reports.
- **Image formats:** common Pillow formats plus HEIF/HEIC, SVG, and many camera RAW formats. Outputs are PNG, JPEG, WebP, AVIF, or TIFF.
- **Image handling:** EXIF orientation is applied; ICC input is converted to sRGB; supported EXIF, DPI, and XMP metadata is retained; alpha is preserved except when JPEG composites it over white. Animated and multipage files use only the first frame/page.
- **Video:** whole-video rendering, a one-frame preview, and a three-second preview. H.264, HEVC, AV1, and ProRes Proxy are available in MP4, MKV, or MOV where compatible.
- **Media preservation:** frame timestamps and display rotation are handled; original metadata and chapters are copied. MKV copies compatible audio and subtitle streams, while MP4/MOV convert audio to 192 kbps AAC.
- **Safety and diagnostics:** only one GPU render runs at a time. Stop cancels the active worker/encoder, incomplete output and job data are removed, and outputs are accepted only after feature-18 execution and output dimensions/frame counts are verified.
- **Persistent controls:** Image and Video tabs share neural settings, saved in `config.ini`; Reset restores every setting to its default.

Outputs are written to `outputs/`, reports and manifests to `logs/`, and temporary data to `jobs/` while a render is active.

## Requirements and startup

- 64-bit Windows with Direct3D 12.
- A current NVIDIA driver, `nvidia-smi`, and an NVIDIA GeForce RTX GPU. RTX 40/50 are the primary targets; RTX 30 is enabled as a slower beta path. RTX 20 and non-RTX GPUs are rejected.
- The authorized runtime files described under [Required external files](#required-external-files).

This GitHub repository intentionally excludes executables, DLLs, the embedded Python environment, and proprietary/prebuilt runtime files. It is **not a complete runnable release**.

In a complete, lawfully assembled portable distribution, double-click `start.bat`. It starts the embedded Python interpreter and opens the local interface in a browser, normally at `http://127.0.0.1:7860`. The server binds only to `127.0.0.1`; Gradio sharing and analytics are disabled.

### Python development

The Python UI and pipeline source require Python 3.13 and these direct packages:

```powershell
py -3.13 -m pip install gradio==6.26.0 Pillow==12.3.0 pillow-heif==1.6.0 rawpy==0.27.1 resvg-py==0.5.0 av==18.1.0 opencv-python-headless==5.0.0.93 numpy==2.5.2
py -3.13 app.py
```

This can launch the UI for development, but rendering still requires the external runtime layout below. `start.bat` specifically expects `bin/python-3.13.15-embed-amd64/python.exe`. The project-specific native worker and its build project are not present, so the complete renderer cannot be rebuilt from this repository alone.

## How processing works

1. The input is decoded to 8-bit SDR RGBA and its orientation and dimensions are normalized.
2. The selected fixed DLSS mode determines the output size; the native worker negotiates its required render size.
3. Images send zero motion with a history reset. Video uses OpenCV DIS optical flow for current-to-previous motion, with resets on the first frame and detected scene changes.
4. Frames are streamed to the project-specific D3D12 worker, which hosts the ReShade/RenoDX DLSS feature-18 path.
5. Alpha is restored for images. Video frames are sent to FFmpeg with source presentation timestamps, then audio, metadata, chapters, and compatible subtitles are muxed.
6. ReShade evidence and output properties are verified. Unverified or incomplete results are deleted; successful renders receive JSON reports containing settings, dimensions, GPU/encoder data, hashes, logs, and feature evidence.

## Settings

| Neural control | Values | Default |
| --- | --- | --- |
| NR Preset | Default, Preset #1, Preset #2, Preset #3 | Default |
| NR Style | Default, Natural, Cinematic | Default |
| NR Intensity | 0.00–2.00 | 1.00 |
| Local Tone Strength | 0.00–2.00 | 1.00 |
| Local Structure Strength | 0.00–2.00 | 1.00 |
| Skin Structure Strength | -1.00–2.00 | -1.00 (native default) |

The preset numbers are experimental native model hints; their visual effect is content-dependent.

| Upscaling mode | Factor | Behavior |
| --- | ---: | --- |
| DLAA / native | 1× | Keeps the source dimensions |
| Quality | 1.5× | Produces 1.5× output dimensions |
| Balanced | 1.724× | Produces approximately 1.724× output dimensions |
| Performance | 2× | Produces 2× output dimensions |
| Ultra Performance | 3× | Produces 3× output dimensions |

Output dimensions are rounded to even pixels and limited to a 7680×4320 boundary.

| Output setting | Choices and behavior |
| --- | --- |
| Image format | PNG/TIFF are lossless; JPEG/WebP/AVIF use the 1–100 quality control (default 95) |
| Video codec | H.264, HEVC, AV1, or ProRes Proxy |
| Container | MP4, MKV, or MOV; ProRes Proxy requires MKV or MOV |
| Encoding quality | Auto (Default) uses resolution/FPS/codec; Good = Auto×2; Best = Auto×4; Max uses CQ/CRF 0; ProRes uses its fixed Proxy profile |

H.264 and HEVC prefer NVENC and fall back to slow software encoding. AV1 requires working AV1 NVENC at the selected output size. ProRes Proxy uses 10-bit 4:2:2 encoding, although the verified neural-rendering path remains RGBA8.

## Limitations

- The verified pipeline is 8-bit SDR sRGB/RGBA8. HDR preservation is disabled; HDR video and higher-bit-depth image data are converted to SDR rather than being incorrectly tagged as HDR.
- Both input dimensions must be at least 64 pixels, and output is limited to 8K (7680×4320, including portrait orientation).
- Video uses only the first decodable video stream and requires an exact frame count.
- Optical flow is not equivalent to engine-provided object motion, depth, masks, or exposure. Fast motion, occlusion, thin geometry, transparency, and hard cuts may produce temporal artifacts.
- Image batches may partially succeed. A stopped batch retains completed files; a stopped video removes its incomplete output.
- Successful log verification proves that the expected code path ran; it does not prove a binary's origin, authenticity, redistribution permission, or license compliance.

## Required external files

The placeholder documents under `bin/` describe the omitted layout. Restore files only from sources you are authorized to use; filenames alone do not establish authenticity or redistribution rights.

| Expected path | Purpose and ownership |
| --- | --- |
| `bin/python-3.13.15-embed-amd64/` | Python 3.13 portable runtime and packages; omitted and replaced by [BINARIES.md](bin/python-3.13.15-embed-amd64/BINARIES.md) |
| `bin/ffmpeg/bin/ffmpeg.exe`, `ffprobe.exe` | FFmpeg processing and probing tools; omitted and documented in [BINARIES.md](bin/ffmpeg/BINARIES.md) |
| `bin/runtime/nvngx.dll` | Project-specific standalone D3D12 worker, named for its caller contract; it is **not** NVIDIA's NGX core DLL |
| `bin/runtime/dxgi.dll` | ReShade carrier with add-on support |
| `bin/runtime/renodx-dlss5.addon64` | Third-party DLSS 5 Neural Rendering add-on; its specific distribution license must be verified separately |
| `bin/runtime/nvngx_dlss.dll`, `nvngx_dlssnr.dll` | DLSS/NGX runtime and neural-rendering components; NVIDIA proprietary terms apply to genuine NVIDIA SDK files |
| `bin/runtime/ReShade.ini` | Local ReShade configuration used by the runtime layout |

See [the complete runtime inventory](bin/runtime/BINARIES.md). Do not obtain or redistribute proprietary or closed-source files through unauthorized mirrors.

## License and third-party notices

Original application code in this repository is licensed under the [MIT License](LICENSE), copyright © 2026 Merserk. That license covers only original project code; it does not relicense or grant rights to any third-party software, model, binary, trademark, media, or other asset.

- **NVIDIA DLSS/NGX:** NVIDIA and its suppliers retain their rights in genuine NVIDIA SDK files. Use and distribution are governed by the [NVIDIA RTX SDK License](https://github.com/NVIDIA/DLSS/blob/main/LICENSE.txt). The files are not included here, no standalone redistribution right is implied, and this project must not be represented as NVIDIA-sponsored or endorsed.
- **FFmpeg:** the referenced Gyan.dev `9.0.1-full_build` was configured with GPL and version-3 components and is distributed under GPLv3. Its build information, license, and exact [corresponding FFmpeg source commit](https://github.com/FFmpeg/FFmpeg/commit/bf1b838f2a) are retained under `bin/ffmpeg/`. Anyone redistributing that binary must satisfy the applicable GPLv3 and corresponding-source obligations. See [FFmpeg licensing](https://github.com/FFmpeg/FFmpeg/blob/master/LICENSE.md).
- **ReShade:** copyright belongs to Patrick Mours and contributors; ReShade is available under the [BSD 3-Clause License](https://github.com/crosire/reshade).
- **RenoDX:** RenoDX core is copyright its authors and available under [MIT](https://github.com/clshortfuse/renodx/blob/main/LICENSE). This does not establish the license of the separate `renodx-dlss5.addon64` file.
- **Python and packages:** Python is provided under the [PSF License](https://docs.python.org/3.13/license.html). Gradio, Pillow, pillow-heif, rawpy, resvg-py, PyAV, OpenCV, NumPy, their transitive dependencies, and bundled codecs retain their own copyright and license terms; preserve the notices shipped with each distribution.

NVIDIA, GeForce RTX, NGX, and DLSS are trademarks and/or registered trademarks of NVIDIA Corporation. FFmpeg, ReShade, RenoDX, Python, and other names belong to their respective owners. Codec patent or other permissions may also be required depending on jurisdiction and use. Review the controlling licenses before building or distributing a complete package.
