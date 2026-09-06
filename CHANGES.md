**Fix in this drop: removed a dead import (`src.core.dlss_architecture`) in `app.py` that doesn't exist in the tree and was never actually used — this was causing a `ModuleNotFoundError` on launch. Nothing else changed from the last drop.**

# Comparison tools + Grid — changes vs. current main (7.0)

These files assume 7.0 (the Neural Rendering Mode toggle, Upscale tab, About
tab). **Path changed**: `src/image/ui.py` and `src/video/ui.py` moved to
`src/neural_rendering/image/ui.py` and `src/neural_rendering/video/ui.py` in
7.0 — that's where the files in this drop go, not the old path.

## Modified
- `app.py` — added "Comparison" and "Grid" tabs alongside the new Neural
  Rendering / Upscale / About tabs. `bind_comparison_events`/`bind_grid_events`
  now take `neural_rendering_tab.image` instead of a standalone `image_tab`,
  since Image and Video are a Mode toggle inside one tab now, not separate tabs.
- `src/neural_rendering/image/ui.py`:
  - Our uploader-alignment fix is gone — no longer needed. 7.0's own
    restructuring (the Mode toggle sits above both Image and Video, each in
    its own panel) already keeps input/output aligned without it.
  - Renders still default to `outputs/images/`; a single-image render still
    skips the zip. Both carried over unchanged from before.
  - "Send to Comparison" reads `tab.sources` + `tab.results` (the live batch
    table) instead of the removed `output_files` component — see below.
- `src/neural_rendering/video/ui.py` — same alignment-fix removal (7.0 already
  handles it); `outputs/videos/` default carried over unchanged.
- `src/frame_interpolation/ui.py` — **kept** the alignment fix here — this tab
  wasn't restructured the way Image/Video were, so it still needs it.
  `outputs/frame_interpolation/` default carried over unchanged.
- `.gitignore` — added (`outputs/`, `__pycache__/`, `*.pyc`); wasn't tracked
  upstream at all.

## Send to Comparison, rebuilt again (the real substance of this pass)
7.0 removed the Image tab's `output_files` component entirely (redundant with
the gallery's own download buttons). Rather than re-adding something just for
our own bookkeeping, `build_comparison_items_from_batch_results()`
(`compare/models.py`) now reads real per-item output paths straight from the
"Output path" column of the live batch results table (`tab.results`),
populated during rendering by `BatchProgress` — looked up via `BATCH_HEADERS`
rather than a hardcoded column index. This is arguably more robust than
`output_files` ever was, and since Video and Frame Interpolation go through
the exact same `bind_batch_ui`/`BatchProgress` system, this same helper is
already positioned to work for them once they're wired into Comparison too.

One thing this exposed in testing rather than by inspection: `gr.Dataframe`
defaults to `type="pandas"`, so `tab.results`'s value is a `pandas.DataFrame`,
not a plain list of lists — a test using plain lists would have passed while
the real UI broke. Fixed by normalizing via `.values.tolist()` before
indexing, and re-verified with an actual DataFrame.

## Everything else (Grid, diff engine, etc.)
Unchanged in substance from the last drop — only import paths moved. See the
previous CHANGES.md for the full feature rundown (axis-labeled XY sweep,
same-shape input-tiled reference grid, selectable diff baseline, single Send
to Comparison sending input/grid/diff-grid/cells together). All of it was
re-verified against 7.0, not just carried over blind.

## Not done yet (next up)
- Synced single-control video/frame-interpolation player — also where the
  video-preview-not-persisting-across-tabs behavior gets a look.
- Frame Interpolation's own grid (engine × target FPS, time-windowed).
- Diagnostics tab.
- Wiring Video/Frame Interpolation into Comparison (now more straightforward
  than it would have been, since `build_comparison_items_from_batch_results`
  already works generically off `tab.results`).

## Testing note
No GPU or worker binary in the environment this was built in, so no real DLSS
render was possible. Verified directly: the full app graph (Neural Rendering
toggle, Upscale, Frame Interpolation, Live, Comparison, Grid, Settings, About)
builds without error against 7.0; `convert_images`'s signature and result
shapes were confirmed unchanged after the module move; a stubbed 2D (X+Y)
sweep still produces correct labeled output; both diff-baseline modes still
produce correct, distinct diffs; and — the one genuinely new check this pass —
`build_comparison_items_from_batch_results` was tested against a real
`pandas.DataFrame` (not just plain lists) to catch the type mismatch above. A
real render is the one thing only your machine can confirm.
