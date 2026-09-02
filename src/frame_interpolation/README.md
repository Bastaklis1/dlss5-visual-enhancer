# Frame Interpolation runtime

This feature uses NVIDIA DLSS Frame Generation directly through D3D12 NGX. The
signed `nvngx_dlssg.dll` 310.7 runtime is isolated under
`bin/runtime/frame_interpolation/dlssg`; `manifest.json` pins its SHA-256 and the
worker never changes `DLSSG.MultiFrameCountMax`.

On an RTX 40 GPU, a worker session asks for exactly one generated frame (2×).
Experimental 4× and 8× grids use two or three independent, sequential 2×
sessions. Output rates up to 6× are sampled from that raw dyadic grid with exact
rational presentation timestamps. Intermediate images are never encoded.

Decoded video does not contain engine depth or motion vectors. A planar SDR depth
buffer and CUDA-free OpenCV DIS optical-flow guides are supplied to DLSSG. Those
guides do not synthesize images; every generated image comes from the signed
NVIDIA runtime. Hard cuts and timestamp discontinuities reset every downstream
history. PQ and HLG input is rejected.

The NVIDIA Optical Flow SDK 5.0 DirectX headers and redistributable are not
silently downloaded because NVIDIA distributes them behind a developer-account
license gate. No CUDA, PyTorch, ONNX, RIFE, FSR FG, XeSS FG, DLSS Enabler, or
OptiScaler dependency is used.
