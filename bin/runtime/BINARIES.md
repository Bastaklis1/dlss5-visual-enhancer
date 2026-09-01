# DLSS and ReShade runtime files

The proprietary, closed-source, or prebuilt Windows runtime files are intentionally not included in this source repository.

- `dxgi.dll` — ReShade/DXGI carrier with add-on support. ReShade is BSD-3-Clause licensed.
- `nvngx.dll` — project-specific standalone D3D12 worker. Its filename is required by the caller contract; it is **not** NVIDIA's NGX core DLL. Its source/build project is not included.
- `nvngx_dlss.dll` — DLSS Super Resolution runtime component; NVIDIA proprietary terms apply to genuine NVIDIA SDK files.
- `nvngx_dlssnr.dll` — DLSS Neural Rendering runtime/model component; origin, authenticity, and applicable NVIDIA terms must be verified before use.
- `renodx-dlss5.addon64` — third-party ReShade-compatible DLSS 5 add-on. Do not assume that the RenoDX core MIT license covers this separate binary; verify its own distribution terms.
- `ReShade.ini` — local configuration used by the ReShade runtime layout.

The repository's MIT license does not cover these files and grants no right to obtain or redistribute them. Restore only components you are authorized to use, from trusted sources permitted by their controlling licenses. Do not use unauthorized binary mirrors. This project is not affiliated with or endorsed by NVIDIA, ReShade, or RenoDX.
