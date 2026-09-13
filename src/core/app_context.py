"""Lets code anywhere in the app (disk-mode path resolution, output-dir
preparation, etc.) register a directory as safe for Gradio to serve
Video/Image/File component values from.

Gradio's own `allowed_paths` list is normally fixed at `launch()` time, set
to just the app's own `outputs/` folder. But disk-mode input/output paths
are arbitrary, user-chosen directories decided at runtime -- there's no way
to know them ahead of time, so anything rendered through disk mode and then
sent to Comparison would otherwise always fail with a silent
`InvalidPathError` (confirmed against a real Gradio server: this error
fails the *entire* click event's output batch, not just the offending
component, so a single disallowed path can look like nothing on that click
worked at all).

Gradio re-reads `blocks.allowed_paths` fresh on every request (it's not
snapshotted at launch), so appending to it at runtime takes effect
immediately -- this module just gives the rest of the app a way to reach
that live list without importing app.py directly (avoiding a circular
import) or depending on Gradio's request-scoped context vars being active,
which they aren't guaranteed to be from a background render thread."""
from __future__ import annotations

from pathlib import Path

_blocks = None


def set_blocks(blocks) -> None:
    """Called once from app.py right after the Blocks instance is built."""
    global _blocks
    _blocks = blocks


def register_allowed_directory(path) -> None:
    """Make `path` (and everything under it) safe for Gradio to serve.
    Safe to call often -- a no-op if `path` is falsy or already covered."""
    if _blocks is None or not path:
        return
    try:
        resolved = str(Path(path).resolve())
    except (OSError, ValueError):
        return
    if resolved not in _blocks.allowed_paths:
        _blocks.allowed_paths.append(resolved)
