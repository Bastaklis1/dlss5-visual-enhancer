from __future__ import annotations

import os
import threading
import time
from collections import OrderedDict
from pathlib import Path

import numpy as np
from PIL import Image

from .models import ImageConversionOptions

_PREVIEW_CACHE_LIMIT = 32
_preview_cache: OrderedDict[str, Image.Image] = OrderedDict()
_preview_cache_lock = threading.Lock()

def take_image_preview(output_path: str | os.PathLike[str]) -> Image.Image | None:
    """Return and remove a UI thumbnail created from the rendered frame in memory."""
    key = str(Path(output_path).resolve())
    with _preview_cache_lock:
        return _preview_cache.pop(key, None)


def _remember_image_preview(
    output_path: Path, rgba: np.ndarray, output_format: str
) -> None:
    image = Image.fromarray(rgba, mode="RGBA")
    try:
        if output_format == "JPEG":
            background = Image.new("RGBA", image.size, (255, 255, 255, 255))
            background.alpha_composite(image)
            preview = background
        else:
            preview = image.copy()
        preview.thumbnail((1600, 1200), Image.Resampling.LANCZOS)
        key = str(output_path.resolve())
        with _preview_cache_lock:
            previous = _preview_cache.pop(key, None)
            if previous is not None:
                previous.close()
            _preview_cache[key] = preview
            while len(_preview_cache) > _PREVIEW_CACHE_LIMIT:
                _unused_key, unused = _preview_cache.popitem(last=False)
                unused.close()
    finally:
        image.close()


def _encode_image(
    output: Path,
    rgba: np.ndarray,
    options: ImageConversionOptions,
    metadata: dict[str, object],
) -> list[str]:
    warnings = save_image(output, rgba, options, metadata)
    try:
        _remember_image_preview(output, rgba, options.output_format)
    except Exception:
        # A UI convenience must never invalidate an otherwise correct output.
        pass
    return warnings

def _metadata_save_args(metadata: dict[str, object], output_format: str) -> dict[str, object]:
    args: dict[str, object] = {}
    if metadata.get("icc_profile"):
        args["icc_profile"] = metadata["icc_profile"]
    if metadata.get("dpi"):
        args["dpi"] = metadata["dpi"]
    if metadata.get("exif") and output_format in {"JPEG", "WebP", "AVIF", "TIFF", "PNG"}:
        args["exif"] = metadata["exif"]
    if metadata.get("xmp") and output_format in {"WebP", "AVIF"}:
        args["xmp"] = metadata["xmp"]
    return args


def save_image(
    output: Path,
    rgba: np.ndarray,
    options: ImageConversionOptions,
    metadata: dict[str, object],
) -> list[str]:
    output_format = options.output_format
    image = Image.fromarray(rgba, mode="RGBA")
    warnings: list[str] = []
    args = _metadata_save_args(metadata, output_format) if options.preserve_metadata else {}
    if output_format == "PNG":
        args.update(optimize=False, compress_level=6)
    elif output_format == "TIFF":
        args.update(compression="tiff_deflate")
    elif output_format == "JPEG":
        background = Image.new("RGBA", image.size, (255, 255, 255, 255))
        background.alpha_composite(image)
        image = background.convert("RGB")
        args.update(
            quality=int(options.quality),
            subsampling=0,
            optimize=False,
            progressive=False,
        )
        if np.any(rgba[..., 3] != 255):
            warnings.append("Transparency was composited over white for JPEG output.")
    elif output_format == "WebP":
        args.update(quality=int(options.quality), method=6)
    elif output_format == "AVIF":
        args.update(quality=int(options.quality), speed=4)

    temporary = output.with_name(f".{output.stem}.{time.time_ns()}{output.suffix}")
    try:
        image.save(temporary, format=output_format, **args)
        os.replace(temporary, output)
    finally:
        image.close()
        if temporary.exists():
            temporary.unlink()
    return warnings
