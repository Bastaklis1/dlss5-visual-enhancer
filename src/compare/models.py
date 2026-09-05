from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(slots=True)
class ComparisonItem:
    """One image that can be picked as a reference or candidate in the Comparison tab.

    `label` is what shows up in the dropdowns (e.g. "Input: cat.png" or
    "Output: cat_DLSS5.png"); `path` is the real file on disk. For sent-from-Image-tab
    items this is always the full-resolution file, never a UI thumbnail.
    """

    label: str
    path: str


def build_comparison_items_from_paths(
    input_paths: list[str] | str | None, output_paths: list[str] | None
) -> list[ComparisonItem]:
    """Turn a tab's current input/output file lists into ComparisonItems.

    Used at "Send to Comparison" click time, reading whatever's currently in the
    tab's own components — decoupled from how that tab's render pipeline is wired,
    since that can (and did) change independently.
    """
    if isinstance(input_paths, str):
        input_paths = [input_paths]
    items = [ComparisonItem(f"Input: {Path(path).name}", path) for path in (input_paths or [])]
    items.extend(
        ComparisonItem(f"Output: {Path(path).name}", path) for path in (output_paths or [])
    )
    return items


@dataclass(slots=True)
class DiffMetrics:
    """Numeric results of comparing two images. Purely computational — no display
    formatting or labels here; the UI layer turns this into rows for the user.
    """

    reference_size: tuple[int, int]
    candidate_size: tuple[int, int]
    compared_size: tuple[int, int]
    resampled: bool
    mean_abs_error: float
    root_mean_square_error: float
    changed_pixels_pct: float
    max_channel_delta: int
