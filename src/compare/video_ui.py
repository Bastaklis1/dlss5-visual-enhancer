from __future__ import annotations

from dataclasses import dataclass

import gradio as gr

from .models import ComparisonItem

NO_SELECTION = "(none yet — send a video here from another tab)"

# Stable, globally-unique element IDs. The control bar below is static markup
# rendered through gr.HTML (so it just needs to exist in the page — no script
# tags required for it to render); SYNC_PLAYER_HEAD_SCRIPT (injected via
# Blocks.launch(head=...), NOT through gr.HTML) is what actually wires it up.
# Scripts embedded inside a gr.HTML component's own value are inserted via
# innerHTML and silently never execute — this is a real browser/Svelte
# behavior, not a Gradio limitation to work around lazily. head= content is
# parsed as real page markup, so its <script> tag runs normally.
VIDEO_A_ELEM_ID = "dlss5-cmp-video-a"
VIDEO_B_ELEM_ID = "dlss5-cmp-video-b"

CONTROL_BAR_HTML = f"""
<div id="dlss5-sync-controls" style="display:flex;align-items:center;gap:8px;flex-wrap:wrap;padding:8px 0;">
  <button type="button" id="dlss5-sync-playpause">▶ Play</button>
  <button type="button" id="dlss5-sync-reset" title="Pause both and jump to 0:00">⏮ Reset to 0</button>
  <input type="range" id="dlss5-sync-seek" min="0" max="1000" value="0" step="1" style="flex:1;min-width:120px;">
  <span id="dlss5-sync-time" style="font-variant-numeric:tabular-nums;">0:00 / 0:00</span>
  <select id="dlss5-sync-speed" title="Playback speed">
    <option value="0.25">0.25x</option>
    <option value="0.5">0.5x</option>
    <option value="1" selected>1x</option>
    <option value="1.5">1.5x</option>
    <option value="2">2x</option>
  </select>
  <button type="button" id="dlss5-sync-prev-frame" title="Step back — pauses first">⏪ Frame</button>
  <button type="button" id="dlss5-sync-next-frame" title="Step forward — pauses first">Frame ⏩</button>
  <input type="number" id="dlss5-sync-frame-step" value="0.033" step="0.001" min="0.001"
         style="width:70px;" title="Frame step size, in seconds (1/fps — default assumes ~30fps)">
</div>
"""

# Injected once via Blocks.launch(head=...). Polls for the two <video> elements
# (they mount slightly after this script first runs, since Gradio's Svelte app
# renders client-side) rather than assuming any particular load order. Once
# found, listeners are attached exactly once and keep working even as the
# videos' sources change later via ordinary Gradio value updates, since the
# underlying <video> elements persist across those — only their src changes.
SYNC_PLAYER_HEAD_SCRIPT = f"""
<script>
(function() {{
  function fmt(t) {{
    if (!isFinite(t)) return '0:00';
    var m = Math.floor(t / 60), s = Math.floor(t % 60);
    return m + ':' + (s < 10 ? '0' : '') + s;
  }}

  function trySetup(attempts) {{
    var a = document.querySelector('#{VIDEO_A_ELEM_ID} video');
    var b = document.querySelector('#{VIDEO_B_ELEM_ID} video');
    var controls = document.getElementById('dlss5-sync-controls');
    if (!a || !b || !controls) {{
      if (attempts > 0) setTimeout(function() {{ trySetup(attempts - 1); }}, 200);
      return;
    }}
    if (a.dataset.dlss5SyncBound) return; // already wired up, don't double-attach
    a.dataset.dlss5SyncBound = '1';
    setup(a, b, controls);
  }}

  function setup(a, b, root) {{
    var playBtn = root.querySelector('#dlss5-sync-playpause');
    var resetBtn = root.querySelector('#dlss5-sync-reset');
    var seek = root.querySelector('#dlss5-sync-seek');
    var timeLabel = root.querySelector('#dlss5-sync-time');
    var speed = root.querySelector('#dlss5-sync-speed');
    var prevFrame = root.querySelector('#dlss5-sync-prev-frame');
    var nextFrame = root.querySelector('#dlss5-sync-next-frame');
    var frameStep = root.querySelector('#dlss5-sync-frame-step');
    var draggingSeek = false;
    var mirroring = false; // guard against the two 'seeking' mirror listeners ping-ponging
    var syncingPlayback = false; // guard against bothPlay/bothPause re-triggering their own play/pause listeners

    function mirror(from, to) {{
      if (mirroring) return;
      mirroring = true;
      if (Math.abs(to.currentTime - from.currentTime) > 0.04) to.currentTime = from.currentTime;
      mirroring = false;
    }}
    function bothPause() {{
      syncingPlayback = true;
      a.pause(); b.pause();
      syncingPlayback = false;
    }}
    function bothPlay() {{
      syncingPlayback = true;
      var p1 = a.play(), p2 = b.play();
      if (p1 && p1.catch) p1.catch(function() {{}});
      if (p2 && p2.catch) p2.catch(function() {{}});
      syncingPlayback = false;
    }}
    function updateTimeLabel() {{
      var duration = isFinite(a.duration) ? a.duration : 0;
      timeLabel.textContent = fmt(a.currentTime) + ' / ' + fmt(duration);
      if (!draggingSeek && duration > 0) seek.value = (a.currentTime / duration) * 1000;
    }}
    function updatePlayLabel() {{ playBtn.textContent = a.paused ? '\\u25B6 Play' : '\\u23F8 Pause'; }}
    function stepFrames(direction) {{
      bothPause();
      var step = parseFloat(frameStep.value) || 0.0333;
      var t = Math.max(0, a.currentTime + direction * step);
      a.currentTime = t; b.currentTime = t;
      updateTimeLabel();
    }}

    playBtn.addEventListener('click', function() {{ if (a.paused) bothPlay(); else bothPause(); }});
    resetBtn.addEventListener('click', function() {{
      bothPause(); a.currentTime = 0; b.currentTime = 0; seek.value = 0; updateTimeLabel();
    }});
    seek.addEventListener('mousedown', function() {{ draggingSeek = true; }});
    seek.addEventListener('touchstart', function() {{ draggingSeek = true; }});
    seek.addEventListener('input', function() {{
      var duration = isFinite(a.duration) ? a.duration : 0;
      var t = (seek.value / 1000) * duration;
      a.currentTime = t; b.currentTime = t;
      updateTimeLabel();
    }});
    seek.addEventListener('change', function() {{ draggingSeek = false; }});
    speed.addEventListener('change', function() {{
      var rate = parseFloat(speed.value);
      a.playbackRate = rate; b.playbackRate = rate;
    }});
    prevFrame.addEventListener('click', function() {{ stepFrames(-1); }});
    nextFrame.addEventListener('click', function() {{ stepFrames(1); }});

    // Mirror native per-video controls too, so dragging either video's own
    // progress bar (instead of the shared one above) still keeps both in sync.
    a.addEventListener('play', function() {{ updatePlayLabel(); if (syncingPlayback) return; if (b.paused) bothPlay(); }});
    b.addEventListener('play', function() {{ updatePlayLabel(); if (syncingPlayback) return; if (a.paused) bothPlay(); }});
    a.addEventListener('pause', function() {{ updatePlayLabel(); if (syncingPlayback) return; if (!b.paused) bothPause(); }});
    b.addEventListener('pause', function() {{ updatePlayLabel(); if (syncingPlayback) return; if (!a.paused) bothPause(); }});
    a.addEventListener('seeking', function() {{ mirror(a, b); }});
    b.addEventListener('seeking', function() {{ mirror(b, a); }});
    a.addEventListener('timeupdate', updateTimeLabel);

    // A new source (dropdown selection / Send to Comparison) always starts
    // from a known, paused, zeroed state rather than wherever it last was.
    a.addEventListener('loadedmetadata', function() {{
      a.currentTime = 0; b.currentTime = 0; updateTimeLabel(); updatePlayLabel();
    }});

    updateTimeLabel();
    updatePlayLabel();
  }}

  trySetup(30);
  // Gradio re-renders the video elements on some value updates, which can
  // detach the ones we bound to — keep checking periodically so a later
  // selection change still gets wired up even if the original pair got
  // replaced outright rather than just having their src swapped.
  setInterval(function() {{ trySetup(1); }}, 3000);
}})();
</script>
"""


def _choices(pool: list[ComparisonItem]) -> list[str]:
    return [item.label for item in pool] or [NO_SELECTION]


def _path_for(pool: list[ComparisonItem], label: str) -> str | None:
    for item in pool:
        if item.label == label:
            return item.path
    return None


def refresh_video_selection(pool: list[ComparisonItem], reference_label: str, candidate_label: str):
    return _path_for(pool, reference_label), _path_for(pool, candidate_label)


def swap_video_selection(reference_label: str, candidate_label: str):
    return candidate_label, reference_label


def receive_video_items(new_items: list[ComparisonItem]):
    labels = [item.label for item in new_items]
    default_reference = next((label for label in labels if label.startswith("Input: ")), None) or (
        labels[0] if labels else NO_SELECTION
    )
    default_candidate = next((label for label in labels if label.startswith("Output: ")), None) or (
        labels[-1] if labels else NO_SELECTION
    )
    return (
        new_items,
        gr.update(choices=labels or [NO_SELECTION], value=default_reference),
        gr.update(choices=labels or [NO_SELECTION], value=default_candidate),
        gr.Tabs(selected="compare"),
        gr.update(value="Video"),
        gr.update(visible=False),  # image panel
        gr.update(visible=True),  # video panel
    )


@dataclass(slots=True)
class VideoCompareTab:
    pool: object
    reference: object
    candidate: object
    swap: object
    reference_video: object
    candidate_video: object


def build_video_compare_panel() -> VideoCompareTab:
    gr.Markdown(
        "Send a video here with **Send to Comparison** (Video or Frame Interpolation tab). "
        "One play button and one seek bar drive both videos together; dragging either video's "
        "own progress bar also keeps them in sync. Frame step is in seconds — adjust it to "
        "match your video's actual frame rate for accurate single-frame stepping."
    )
    pool = gr.State([])
    with gr.Row():
        reference = gr.Dropdown(choices=[NO_SELECTION], value=NO_SELECTION, label="Reference (baseline)")
        candidate = gr.Dropdown(choices=[NO_SELECTION], value=NO_SELECTION, label="Candidate")
        swap = gr.Button("⇄ Swap", scale=0)
    gr.HTML(CONTROL_BAR_HTML)
    with gr.Row():
        reference_video = gr.Video(label="Reference", interactive=False, elem_id=VIDEO_A_ELEM_ID)
        candidate_video = gr.Video(label="Candidate", interactive=False, elem_id=VIDEO_B_ELEM_ID)
    return VideoCompareTab(pool, reference, candidate, swap, reference_video, candidate_video)


def bind_video_compare_events(video_tab: VideoCompareTab) -> None:
    refresh_inputs = [video_tab.pool, video_tab.reference, video_tab.candidate]
    refresh_outputs = [video_tab.reference_video, video_tab.candidate_video]
    video_tab.reference.change(refresh_video_selection, inputs=refresh_inputs, outputs=refresh_outputs, queue=False)
    video_tab.candidate.change(refresh_video_selection, inputs=refresh_inputs, outputs=refresh_outputs, queue=False)
    video_tab.swap.click(
        swap_video_selection, inputs=[video_tab.reference, video_tab.candidate],
        outputs=[video_tab.reference, video_tab.candidate], queue=False,
    )
