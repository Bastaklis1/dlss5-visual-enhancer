from __future__ import annotations

import os
from typing import Callable

from .batch import convert_images
from .models import ImageConversionOptions, ImageConversionResult

def convert_image(
    input_path: str | os.PathLike[str],
    options: ImageConversionOptions | None = None,
    progress: Callable[[float, str], None] | None = None,
) -> ImageConversionResult:
    result = convert_images([input_path], options, progress)
    if result.successes:
        return result.successes[0]
    if result.failures:
        raise RuntimeError(result.failures[0].error)
    raise RuntimeError("Image conversion produced no result.")
