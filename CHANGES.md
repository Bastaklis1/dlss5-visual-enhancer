# Comparison tools + Grid — changes vs. current main

These files assume they're being applied on top of current
`Merserk/dlss5-visual-enhancer` main (the "6.0" release with the Live tab and
the direct-disk batch path) — replace them at the matching paths.

## Modified
- `app.py` — added "Comparison" and "Grid" tabs, wired alongside the existing
  Image/Video/Frame Interpolation/Live/Settings tabs.
- `src/image/ui.py`:
  - Uploader (and the direct-disk path controls) moved above the
    input/output columns instead of stacked in the left column only, so the
    input and output previews line up vertically.
  - Renders now default to `outputs/images/` instead of a flat `outputs/`
    root. Direct-disk mode is untouched — it already uses an explicit
    user-chosen path.
  - A single-image render no longer generates a zip (it only zipped one file
    with no report inside anyway) — only batches of more than one image do.
  - Added a "Send to Comparison" button under the output gallery. Reads the
    tab's current `sources`/`output_files` live at click time rather than
    hooking into the render pipeline's return value, since rendering is
    already routed through the shared `bind_batch_ui` — this doesn't touch
    that system at all.
- `src/video/ui.py` — same alignment fix, plus renders now default to
  `outputs/videos/`.
- `src/frame_interpolation/ui.py` — same alignment fix, plus renders now
  default to `outputs/frame_interpolation/`.

## New: `src/compare/`
- `models.py` — `ComparisonItem` (label + path), `DiffMetrics`, and
  `build_comparison_items_from_paths()` (turns a tab's current input/output
  path lists into ComparisonItems at Send-to-Comparison time).
- `processor.py` — `load_rgb()` (decodes via the app's own decoder first for
  RAW/HEIC/SVG, falls back to Pillow for plain raster), `compute_diff()` /
  `compute_diff_from_images()`: MAE, RMSE, changed-pixel %, max channel
  delta, plus an amplified grayscale diff image. Resamples the candidate to
  the reference's resolution if they differ and flags that it happened.
- `ui.py` — the Comparison tab: reference/candidate dropdowns backed by a
  per-session pool, a swap button, an `ImageSlider` before/after view, the
  metrics table, and a diff-amplify slider + diff view. `receive_items()`
  picks sensible defaults: preferred-reference labels (e.g. "Grid: Input
  grid") beat a plain "Input:" prefix match beat the first item; preferred-
  candidate labels (e.g. "Grid: Full grid") beat a plain "Output:" prefix
  match beat the last item. `bind_comparison_events()` wires up Send to
  Comparison from both the Image tab and the Grid tab.
- `grid.py` — `compose_grid()`: pure PIL tiling of a 2D cell grid into one
  labeled image. Scales each tile independently to a target long-edge size
  (or full res), never upscales past a tile's native resolution, widens
  each column to fit its label text (not just its tile images — axis-name
  labels can be wider than a narrow tile), and renders a legible red error
  tile for any cell that failed instead of breaking the whole grid.
- `grid_render.py` — the axis registry, the per-cell render loop, and the
  diff-grid logic. Cell renders go to `outputs/grids/cells/` with
  `generate_previews=False, create_zip=False` (a grid can be dozens of
  cells — no need for either per cell). Composite grid/diff/input images
  save to `outputs/grids/`.
- `grid_ui.py` — the Grid tab: its own full copy of the baseline settings
  (`build_neural_controls`/`build_dlss_model_control`, imported from
  `image.ui` — the same cross-module pattern `live/ui.py` already uses for
  the same two functions from `video.ui`), X/Y axis pickers, resolution
  choice, diff toggle + baseline choice, and the render button.

## How the Grid works
- X axis required, Y optional. Baseline settings (Neural Rendering + DLSS
  Model Preset) are the Grid tab's own controls — whatever isn't picked as
  an axis renders using these; picking a setting as an axis overrides just
  that field per cell.
- Categorical axes default to every valid choice as checkboxes; continuous
  axes default to 5 evenly-spaced points across their real range as an
  editable comma list.
- Row/column headers and cell labels are prefixed with the axis name (e.g.
  "NR Intensity: 0.5"), so a numeric X+Y sweep is never ambiguous about
  which value belongs to which axis.
- Optional diff grid: a second full grid, same shape as the render grid,
  diffed against either the first rendered cell or the input image. Shown
  as its own image, hidden when not requested.
- "Send to Comparison" sends: the input image, a same-shape grid of the
  input repeated in every cell (so the default comparison is apples-to-
  apples instead of one image vs. a whole tiled grid), the full render
  grid, the diff grid (if generated), and every individual cell. The input
  grid/full grid pair is the default reference/candidate; cells stay
  reachable from the dropdown.

## Not done yet (next up)
- Synced single-control video/frame-interpolation player (one play button,
  one time slider) — also where the video-preview-not-persisting-across-
  tabs behavior will get a look.
- Frame Interpolation's own grid (engine × target FPS, time-windowed).
- Diagnostics tab.

## Testing note
No GPU or worker binary in the environment this was built in, so no real DLSS
render was possible. Verified directly: the full 7-tab app graph (including
Live) builds without error against current main; a stubbed 2D (X+Y) sweep
produces correct independent gradients and correctly labeled headers/cells;
both diff-baseline modes produce correct, distinct diffs; the input-tiled
reference grid comes out pixel-identical in size to the render grid for the
common case; output_dir routing was verified directly against the real
`render_image_batch`/`render_video_batch`/`render_frame_interpolation_batch`
functions (mocking only the underlying `convert_images`/`convert_videos`/
`interpolate_videos` calls) in both normal and direct-disk modes; and
zip-only-for-batches was verified for both a 1-file and 2-file case. A real
render is the one thing only your machine can confirm.
