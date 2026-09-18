"""Diagnostics tab: GPU detection, runtime file presence, environment info,
a browser for the generation reports every render writes to logs/, and a
Maintenance section for the app's own operational logs plus cleanup/export
actions.

Kept mostly read-only. The state-changing actions are all in Maintenance:
"Clear cache now" (runs the same sweep that already happens automatically),
"Clean up old generation reports" (age-based deletion, on demand only), and
"Generate diagnostic bundle" (writes a file, doesn't delete anything).
"""
from __future__ import annotations

from dataclasses import dataclass

import gradio as gr

from . import collector

REPORT_HEADERS = ["Name", "Kind", "Size", "Modified"]
RENDER_ACTIVITY_HEADERS = ["Time", "Area", "Level", "Message"]
GPU_HEADERS = ["#", "Name", "Driver", "Memory", "PCI Bus", "RTX-compatible", "Role"]
RUNTIME_FILE_HEADERS = ["File", "Required", "Status", "Size", "Modified"]
ENCODER_HEADERS = ["Encoder", "Available"]
OPERATIONAL_LOG_HEADERS = ["Log", "Status", "Size", "Modified"]


def _format_bytes(size: int) -> str:
    value = float(size)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024 or unit == "TB":
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} TB"


def _gpu_rows() -> tuple[list[list[str]], str]:
    info = collector.collect_gpus()
    if info["error"]:
        return [], f"GPU detection failed: {info['error']}"
    rows = []
    for gpu in info["gpus"]:
        roles = []
        if info["ai_gpu_uuid"] == gpu["uuid"]:
            roles.append("AI Processing (configured)")
        if info["video_gpu_uuid"] == gpu["uuid"]:
            roles.append("Video Encoding (configured)")
        if not roles and info["ai_gpu_uuid"] == "auto" and gpu["ai_compatible"]:
            roles.append("AI Processing (auto candidate)")
        rows.append([
            str(gpu["index"]), gpu["name"], gpu["driver"],
            f"{gpu['memory_mb'] / 1024:.1f} GB", gpu["pci_bus_id"] or "(n/a)",
            "Yes" if gpu["ai_compatible"] else f"No — {gpu['compatibility_error']}",
            ", ".join(roles) or "-",
        ])
    status = (
        f"Configured AI Processing GPU: {info['ai_gpu_uuid']} | "
        f"Configured Video Encoding GPU: {info['video_gpu_uuid']}"
    )
    if info["settings_error"]:
        status += f"\n(Could not read configured GPU settings: {info['settings_error']})"
    return rows, status


def _runtime_file_rows() -> list[list[str]]:
    rows = []
    for row in collector.collect_runtime_files():
        if row.get("exists"):
            status = "OK" if "error" not in row else f"Error: {row['error']}"
            size = _format_bytes(row["size_bytes"]) if "size_bytes" in row else "-"
            modified = row.get("modified", "-")
        else:
            status = "Missing" if "error" not in row else f"Error: {row['error']}"
            size, modified = "-", "-"
        rows.append([
            row["label"], "Yes" if row["required"] else "No", status, size, modified,
        ])
    return rows


def _encoder_rows() -> list[list[str]]:
    bundle_info = collector.collect_runtime_bundle()
    inventory = bundle_info["encoder_inventory"]
    if not inventory:
        note = bundle_info.get("encoder_inventory_error") or "unknown"
        return [[f"(encoder inventory unavailable: {note})", ""]]
    return [[name, "Yes" if available else "No"] for name, available in inventory.items()]


def _environment_markdown() -> str:
    env = collector.collect_environment()
    packages = "  \n".join(f"- **{name}**: {version}" for name, version in env["packages"].items())
    disk = env["disk_usage"]
    disk_line = (
        f"{_format_bytes(disk['free_bytes'])} free of {_format_bytes(disk['total_bytes'])}"
        if "error" not in disk else f"unavailable ({disk['error']})"
    )
    sizes = env["folder_sizes_bytes"]
    return (
        f"**App version**: {env['app_version']}  \n"
        f"**Python**: {env['python_version']}  \n"
        f"**OS**: {env['platform']} ({env['machine']})  \n"
        f"**FFmpeg**: {env['ffmpeg_version']}  \n"
        f"**FFprobe**: {env['ffprobe_version']}  \n\n"
        f"**Packages**  \n{packages}\n\n"
        f"**Disk**: {disk_line}  \n"
        f"**Folder sizes**: outputs {_format_bytes(sizes['outputs'])} | "
        f"logs {_format_bytes(sizes['logs'])} | jobs {_format_bytes(sizes['jobs'])}"
    )


def _report_rows() -> tuple[list[list[str]], list[str]]:
    """Returns (display rows, parallel list of real file paths for lookup by row index)."""
    reports = collector.collect_reports()
    rows = [[r["name"], r["kind"], _format_bytes(r["size_bytes"]), r["modified"]] for r in reports]
    paths = [r["path"] for r in reports]
    return rows, paths


def _render_activity_rows(sessions: int = 1) -> list[list[str]]:
    return [
        [e["time"], e["area"], e["level"], e["message"]]
        for e in collector.collect_render_activity(sessions=sessions)
    ]


def _operational_log_rows() -> tuple[list[list[str]], list[str]]:
    """Same shape as _report_rows(): (display rows, parallel path list)."""
    logs = collector.collect_operational_logs()
    rows, paths = [], []
    for row in logs:
        if row.get("exists"):
            status = "OK" if "error" not in row else f"Error: {row['error']}"
            size = _format_bytes(row["size_bytes"]) if "size_bytes" in row else "-"
            modified = row.get("modified", "-")
        else:
            status, size, modified = "Not present", "-", "-"
        rows.append([row["name"], status, size, modified])
        paths.append(row["path"])
    return rows, paths


@dataclass(slots=True)
class DiagnosticsTab:
    gpu_table: object
    gpu_status: object
    refresh_gpu_btn: object
    runtime_files_table: object
    encoder_table: object
    environment_markdown: object
    refresh_environment_btn: object
    reports_table: object
    report_viewer: object
    refresh_reports_btn: object
    report_paths: object  # gr.State, parallel to reports_table's rows
    open_report_folder_btn: object
    open_report_folder_status: object
    render_activity_table: object
    refresh_render_activity_btn: object
    operational_logs_table: object
    operational_log_paths: object  # gr.State, parallel to operational_logs_table's rows
    operational_log_viewer: object
    open_operational_log_folder_btn: object
    open_operational_log_folder_status: object
    clear_cache_btn: object
    clear_cache_status: object
    cleanup_reports_age_days: object
    cleanup_reports_btn: object
    cleanup_reports_status: object
    generate_bundle_btn: object
    bundle_file: object
    summary_box: object
    refresh_all_btn: object


def build_diagnostics_tab() -> DiagnosticsTab:
    gpu_rows, gpu_status_text = _gpu_rows()
    report_rows, initial_report_paths = _report_rows()
    operational_log_rows, initial_operational_log_paths = _operational_log_rows()

    gr.Markdown(
        "Read-only system and render diagnostics. State-changing actions are "
        "confined to **Maintenance** below."
    )
    refresh_all_btn = gr.Button("Refresh everything", variant="primary")

    with gr.Accordion("GPU", open=True):
        gpu_table = gr.Dataframe(
            headers=GPU_HEADERS, value=gpu_rows, interactive=False, wrap=True,
        )
        gpu_status = gr.Markdown(gpu_status_text)
        refresh_gpu_btn = gr.Button("Re-detect GPUs")

    with gr.Accordion("Runtime files & encoders", open=False):
        runtime_files_table = gr.Dataframe(
            headers=RUNTIME_FILE_HEADERS, value=_runtime_file_rows(),
            interactive=False, wrap=True,
        )
        gr.Markdown("**FFmpeg encoder inventory**")
        encoder_table = gr.Dataframe(
            headers=ENCODER_HEADERS, value=_encoder_rows(), interactive=False,
        )

    with gr.Accordion("Environment", open=False):
        environment_markdown = gr.Markdown(_environment_markdown())
        refresh_environment_btn = gr.Button("Refresh environment info")

    with gr.Accordion("Generation reports", open=False):
        gr.Markdown(
            "v9.0 no longer writes a separate report file per render (see "
            "**Render activity** below for that) -- this now only ever shows "
            "the small `.err` file written on a real failure. Select a row "
            "to view its contents."
        )
        reports_table = gr.Dataframe(
            headers=REPORT_HEADERS, value=report_rows, interactive=False, wrap=True,
        )
        report_paths = gr.State(initial_report_paths)
        with gr.Row():
            refresh_reports_btn = gr.Button("Refresh report list")
            open_report_folder_btn = gr.Button("Open containing folder")
        open_report_folder_status = gr.Markdown("")
        report_viewer = gr.Code(label="Selected report", language="json", value="", buttons=["copy"])

    with gr.Accordion("Render activity (session log)", open=False):
        gr.Markdown(
            "Every render's outcome and any errors, across every tab, as "
            "they were actually logged this session -- v9.0 writes one "
            "compact line per event to the current session log instead of "
            "a separate file per render. Newest first."
        )
        render_activity_table = gr.Dataframe(
            headers=RENDER_ACTIVITY_HEADERS, value=_render_activity_rows(), interactive=False, wrap=True,
        )
        refresh_render_activity_btn = gr.Button("Refresh render activity")

    with gr.Accordion("Maintenance", open=False):
        gr.Markdown("**Application logs** — the app's own running logs, not per-render reports.")
        operational_logs_table = gr.Dataframe(
            headers=OPERATIONAL_LOG_HEADERS, value=operational_log_rows,
            interactive=False, wrap=True,
        )
        operational_log_paths = gr.State(initial_operational_log_paths)
        open_operational_log_folder_btn = gr.Button("Open containing folder")
        open_operational_log_folder_status = gr.Markdown("")
        operational_log_viewer = gr.Code(label="Selected log", language=None, value="", buttons=["copy"])

        gr.Markdown("---\n**Cache**")
        with gr.Row():
            clear_cache_btn = gr.Button("Clear cache now")
            clear_cache_status = gr.Markdown("")

        gr.Markdown("---\n**Generation reports cleanup** — deletes render reports, batch "
                    "manifests, and failure reports older than the given age. Does not "
                    "touch the application logs above.")
        with gr.Row():
            cleanup_reports_age_days = gr.Number(value=30, label="Delete reports older than (days)", minimum=0)
            cleanup_reports_btn = gr.Button("Clean up old generation reports")
        cleanup_reports_status = gr.Markdown("")

        gr.Markdown("---\n**Support bundle** — a single Markdown file with the diagnostic "
                    "summary and recent application-log activity, for pasting or attaching "
                    "to a bug report. Generated on demand only.")
        generate_bundle_btn = gr.Button("Generate diagnostic bundle")
        bundle_file = gr.File(label="Generated bundle", visible=False)

        gr.Markdown("---\n**Copy this for a quick summary:**")
        summary_box = gr.Textbox(
            value=collector.build_diagnostic_summary(), label="Diagnostic summary",
            lines=14, max_lines=30, interactive=False,
        )

    return DiagnosticsTab(
        gpu_table=gpu_table, gpu_status=gpu_status, refresh_gpu_btn=refresh_gpu_btn,
        runtime_files_table=runtime_files_table, encoder_table=encoder_table,
        environment_markdown=environment_markdown, refresh_environment_btn=refresh_environment_btn,
        reports_table=reports_table, report_viewer=report_viewer,
        refresh_reports_btn=refresh_reports_btn, report_paths=report_paths,
        open_report_folder_btn=open_report_folder_btn, open_report_folder_status=open_report_folder_status,
        render_activity_table=render_activity_table, refresh_render_activity_btn=refresh_render_activity_btn,
        operational_logs_table=operational_logs_table, operational_log_paths=operational_log_paths,
        operational_log_viewer=operational_log_viewer,
        open_operational_log_folder_btn=open_operational_log_folder_btn,
        open_operational_log_folder_status=open_operational_log_folder_status,
        clear_cache_btn=clear_cache_btn, clear_cache_status=clear_cache_status,
        cleanup_reports_age_days=cleanup_reports_age_days, cleanup_reports_btn=cleanup_reports_btn,
        cleanup_reports_status=cleanup_reports_status,
        generate_bundle_btn=generate_bundle_btn, bundle_file=bundle_file,
        summary_box=summary_box, refresh_all_btn=refresh_all_btn,
    )


def _refresh_gpu():
    from ..core.gpu_detection import clear_gpu_detection_cache
    from ..core.gpu_selection import clear_gpu_selection_cache

    clear_gpu_selection_cache()
    clear_gpu_detection_cache()
    rows, status = _gpu_rows()
    return gr.update(value=rows), status


def _refresh_environment():
    return _environment_markdown()


def _refresh_reports():
    rows, paths = _report_rows()
    return gr.update(value=rows), paths, ""  # clear the viewer too, since old selection may be gone


def _selected_row_path(paths: list[str], evt: gr.SelectData) -> str | None:
    if evt is None or evt.index is None:
        return None
    row_index = evt.index[0] if isinstance(evt.index, (list, tuple)) else evt.index
    if row_index is None or row_index >= len(paths):
        return None
    return paths[row_index]


def _view_selected_report(paths: list[str], evt: gr.SelectData):
    path = _selected_row_path(paths, evt)
    return collector.read_report(path) if path else ""


def _view_selected_operational_log(paths: list[str], evt: gr.SelectData):
    path = _selected_row_path(paths, evt)
    if not path:
        return ""
    return collector.read_report(path)  # handles plain text fine; only .json gets parsed


def _clear_cache_now():
    from ..core.cache_cleanup import cleanup_old_caches

    result = cleanup_old_caches(max_age_seconds=0)
    freed = _format_bytes(result["freed_bytes"])
    return f"Removed {result['removed']} item(s), freed {freed}."


def _cleanup_reports(age_days):
    try:
        age_days = int(age_days)
    except (TypeError, ValueError):
        return "Enter a whole number of days.", gr.skip(), gr.skip()
    if age_days < 0:
        return "Age must be zero or more days.", gr.skip(), gr.skip()
    result = collector.cleanup_old_reports(max_age_days=age_days)
    freed = _format_bytes(result["freed_bytes"])
    message = f"Removed {result['removed']} report(s), freed {freed}."
    if result["errors"]:
        message += f" {len(result['errors'])} could not be removed (see logs)."
    rows, paths = _report_rows()
    return message, gr.update(value=rows), paths


def _generate_bundle():
    path = collector.generate_diagnostic_bundle()
    return gr.update(value=path, visible=True)


def _refresh_all():
    gpu_rows, gpu_status_text = _gpu_rows()
    report_rows, report_paths = _report_rows()
    op_log_rows, op_log_paths = _operational_log_rows()
    return (
        gr.update(value=gpu_rows), gpu_status_text,
        gr.update(value=_runtime_file_rows()), gr.update(value=_encoder_rows()),
        _environment_markdown(),
        gr.update(value=report_rows), report_paths,
        gr.update(value=op_log_rows), op_log_paths,
        gr.update(value=_render_activity_rows()),
        collector.build_diagnostic_summary(),
    )


def bind_diagnostics_events(tab: DiagnosticsTab) -> None:
    tab.refresh_gpu_btn.click(_refresh_gpu, outputs=[tab.gpu_table, tab.gpu_status], queue=False)
    tab.refresh_environment_btn.click(
        _refresh_environment, outputs=[tab.environment_markdown], queue=False,
    )
    tab.refresh_reports_btn.click(
        _refresh_reports, outputs=[tab.reports_table, tab.report_paths, tab.report_viewer],
        queue=False,
    )
    tab.reports_table.select(
        _view_selected_report, inputs=[tab.report_paths], outputs=[tab.report_viewer], queue=False,
    )
    # "Open containing folder" always opens the currently-selected report's
    # folder. Since every report lives directly under logs/ (or logs/live/
    # for Live sessions), any selection resolves to the right place; without
    # a selection yet, it falls back to the logs folder itself.
    tab.open_report_folder_btn.click(
        lambda paths: collector.open_containing_folder(paths[0] if paths else str(collector.LOGS)),
        inputs=[tab.report_paths], outputs=[tab.open_report_folder_status], queue=False,
    )
    tab.refresh_render_activity_btn.click(
        lambda: gr.update(value=_render_activity_rows()), outputs=[tab.render_activity_table], queue=False,
    )
    tab.operational_logs_table.select(
        _view_selected_operational_log, inputs=[tab.operational_log_paths],
        outputs=[tab.operational_log_viewer], queue=False,
    )
    tab.open_operational_log_folder_btn.click(
        lambda: collector.open_containing_folder(str(collector.LOGS)),
        outputs=[tab.open_operational_log_folder_status], queue=False,
    )
    tab.clear_cache_btn.click(
        _clear_cache_now, outputs=[tab.clear_cache_status], queue=False,
    )
    tab.cleanup_reports_btn.click(
        _cleanup_reports, inputs=[tab.cleanup_reports_age_days],
        outputs=[tab.cleanup_reports_status, tab.reports_table, tab.report_paths], queue=False,
    )
    tab.generate_bundle_btn.click(
        _generate_bundle, outputs=[tab.bundle_file], queue=False,
    )
    tab.refresh_all_btn.click(
        _refresh_all,
        outputs=[
            tab.gpu_table, tab.gpu_status, tab.runtime_files_table, tab.encoder_table,
            tab.environment_markdown, tab.reports_table, tab.report_paths,
            tab.operational_logs_table, tab.operational_log_paths, tab.render_activity_table,
            tab.summary_box,
        ],
        queue=False,
    )
