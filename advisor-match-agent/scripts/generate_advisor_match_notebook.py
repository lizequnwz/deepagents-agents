"""Generate the interactive stateless Advisor Match Jupyter notebook."""

from __future__ import annotations

import json
import hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "notebooks" / "advisor_match_stateless_workflow.ipynb"


def markdown(source: str) -> dict:
    return {
        "cell_type": "markdown",
        "metadata": {},
        "source": source.strip() + "\n",
    }


def code(source: str) -> dict:
    return {
        "cell_type": "code",
        "execution_count": None,
        "metadata": {},
        "outputs": [],
        "source": source.strip() + "\n",
    }


CELLS = [
    markdown(
        r"""
# Advisor Match — interactive stateless workflow

This notebook is an interactive client for the production Advisor Match REST API. It covers the complete workflow:

1. Upload and analyze a CSV/XLSX advisor file.
2. Review or correct the proposed physical column mapping.
3. Resolve firm handling and run deterministic policy-version-5 matching.
4. Inspect summary counts and download `advisor_matches.xlsx` plus `result.json`.
5. Hand the generated workbook to profile generation, or upload a separate CRD file.
6. Confirm the CRD column, generate the placeholder HTML report, preview it, and download it.

The notebook does **not** reproduce matching rules or retain API-side workflow state. Every API operation sends all required bytes and configuration, so requests can reach different EKS pods. Notebook variables are temporary kernel state; files under `notebook_outputs/` exist only because you explicitly generated a download.
"""
    ),
    markdown(
        r"""
## Prerequisites

From the repository root, install the locked environment and start JupyterLab:

```bash
uv sync --locked --all-groups
uv run jupyter lab notebooks/advisor_match_stateless_workflow.ipynb
```

Use an existing deployed API URL, or start the local API in another terminal:

```bash
uv run uvicorn advisor_match.api:app --host 127.0.0.1 --port 8001
```

The local API reads `.env`; configure `MODEL_NAME` and `OPENAI_API_KEY` before running mapping requests. You may instead set `START_LOCAL_API = True` in the next cell to launch the API from this kernel.
"""
    ),
    code(
        r"""
from __future__ import annotations

import atexit
import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass
from html import escape
from pathlib import Path
from typing import Any

import ipywidgets as widgets
from IPython.display import FileLink, HTML, display

from advisor_match.ui.api_client import APIError, AdvisorMatchAPIClient


def find_project_root(start: Path) -> Path:
    for candidate in (start, *start.parents):
        if (candidate / "pyproject.toml").exists() and (candidate / "advisor_match").is_dir():
            return candidate
    raise RuntimeError("Run this notebook from inside the Advisor Match repository.")


PROJECT_ROOT = find_project_root(Path.cwd().resolve())
os.chdir(PROJECT_ROOT)
OUTPUT_DIR = PROJECT_ROOT / "notebook_outputs"
OUTPUT_DIR.mkdir(exist_ok=True)

API_BASE_URL = "http://127.0.0.1:8001"
START_LOCAL_API = False
LOCAL_API_PROCESS: subprocess.Popen[str] | None = None


def start_local_api(base_url: str = API_BASE_URL) -> subprocess.Popen[str]:
    # Optionally launch the stateless API with this kernel's Python environment.

    global LOCAL_API_PROCESS
    if LOCAL_API_PROCESS and LOCAL_API_PROCESS.poll() is None:
        return LOCAL_API_PROCESS
    host_port = base_url.removeprefix("http://").removeprefix("https://")
    host, port_text = host_port.rsplit(":", 1)
    LOCAL_API_PROCESS = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "advisor_match.api:app",
            "--host",
            host,
            "--port",
            port_text,
        ],
        cwd=PROJECT_ROOT,
        text=True,
    )
    client = AdvisorMatchAPIClient(base_url)
    for _ in range(50):
        try:
            client.health()
            break
        except APIError:
            if LOCAL_API_PROCESS.poll() is not None:
                raise RuntimeError("The local Advisor Match API exited during startup.")
            time.sleep(0.2)
    else:
        LOCAL_API_PROCESS.terminate()
        raise RuntimeError("The local Advisor Match API did not become healthy.")
    return LOCAL_API_PROCESS


def stop_local_api() -> None:
    global LOCAL_API_PROCESS
    if LOCAL_API_PROCESS and LOCAL_API_PROCESS.poll() is None:
        LOCAL_API_PROCESS.terminate()
        try:
            LOCAL_API_PROCESS.wait(timeout=5)
        except subprocess.TimeoutExpired:
            LOCAL_API_PROCESS.kill()
    LOCAL_API_PROCESS = None


atexit.register(stop_local_api)
if START_LOCAL_API:
    start_local_api()

print(f"Project root: {PROJECT_ROOT}")
print(f"Notebook downloads: {OUTPUT_DIR}")
"""
    ),
    markdown(
        r"""
## Interactive client implementation

The controls below call only the public REST API through `AdvisorMatchAPIClient`. Mapping selectors bind a zero-based physical column index and its exact observed header. The original uploaded bytes are retained only in this kernel and resent to the next endpoint with the analysis SHA-256.
"""
    ),
    code(
        r"""
MATCH_FIELDS = (
    ("crd_number", "Advisor CRD"),
    ("firm_name", "Firm"),
    ("email", "Email"),
    ("city", "City"),
    ("state", "State"),
    ("zip_code", "ZIP code"),
)


@dataclass(frozen=True)
class UploadedBytes:
    filename: str
    content: bytes
    content_type: str | None = None


def uploaded_bytes(uploader: widgets.FileUpload) -> UploadedBytes:
    # Read one ipywidgets 8 upload without writing a temporary file.

    values = uploader.value
    if not values:
        raise ValueError("Choose a CSV or XLSX file first.")
    record = next(iter(values.values())) if isinstance(values, dict) else values[0]
    return UploadedBytes(
        filename=str(record["name"]),
        content=bytes(record["content"]),
        content_type=str(record.get("type") or "application/octet-stream"),
    )


def api_error_html(exc: Exception) -> str:
    if isinstance(exc, APIError):
        details = (
            f"<pre>{escape(json.dumps(exc.details, indent=2, default=str))}</pre>"
            if exc.details
            else ""
        )
        code = f" [{escape(exc.code)}]" if exc.code else ""
        return f'<div style="color:#b91c1c"><b>API error{code}:</b> {escape(str(exc))}{details}</div>'
    return f'<div style="color:#b91c1c"><b>Error:</b> {escape(str(exc))}</div>'


def write_download(filename: str, content: bytes | str) -> Path:
    # Create a user-visible notebook output and return its Jupyter download path.

    path = OUTPUT_DIR / Path(filename).name
    if isinstance(content, str):
        path.write_text(content, encoding="utf-8")
    else:
        path.write_bytes(content)
    return path


def display_download(path: Path, label: str | None = None) -> None:
    display(FileLink(str(path.relative_to(PROJECT_ROOT)), result_html_prefix=(label or "Download") + ": "))


def render_profile_preview(profile: dict[str, Any], output: widgets.Output) -> None:
    with output:
        output.clear_output()
        print(f"Format: {profile['format'].upper()} · SHA-256: {profile['source_sha256']}")
        for warning in profile.get("warnings") or []:
            print(f"Warning: {warning}")
        for sheet in profile.get("sheets") or []:
            title = sheet.get("name") or "CSV"
            rows = sheet.get("preview_rows") or []
            display(HTML(f"<h4>{escape(title)}</h4>"))
            if not rows:
                print("No preview rows.")
                continue
            width = max(len(row.get("values") or []) for row in rows)
            body = []
            for row in rows:
                values = list(row.get("values") or []) + [""] * (width - len(row.get("values") or []))
                cells = "".join(f"<td>{escape(str(value))}</td>" for value in values)
                body.append(f"<tr><th>{row['row_number']}</th>{cells}</tr>")
            display(
                HTML(
                    '<div style="overflow:auto;max-height:260px"><table style="border-collapse:collapse">'
                    '<thead><tr><th>Source row</th><th colspan="99">Bounded values</th></tr></thead>'
                    f"<tbody>{''.join(body)}</tbody></table></div>"
                )
            )


class MappingEditor:
    # Editable worksheet/header/physical-column controls derived from one profile.

    def __init__(self, profile: dict[str, Any], proposal: dict[str, Any] | None, *, crd_only: bool = False):
        self.profile = profile
        self.proposal = proposal or {}
        self.crd_only = crd_only
        sheets = profile["sheets"]
        sheet_options = [(sheet.get("name") or "CSV", sheet.get("name")) for sheet in sheets]
        proposed_sheet = self.proposal.get("sheet_name")
        initial_sheet = proposed_sheet if proposed_sheet in [value for _, value in sheet_options] else sheet_options[0][1]
        self.sheet = widgets.Dropdown(options=sheet_options, value=initial_sheet, description="Worksheet:", layout=widgets.Layout(width="520px"))
        self.header = widgets.Dropdown(description="Header row:", layout=widgets.Layout(width="520px"))
        self.selectors: dict[str, widgets.Dropdown] = {}
        self.name_mode = widgets.ToggleButtons(
            options=[("Full name", "full_name"), ("First + last", "split")],
            value="full_name" if self.proposal.get("full_name") or not self.proposal.get("first_name") else "split",
            description="Name mode:",
        )
        fields = (("crd_number", "Advisor CRD"),) if crd_only else MATCH_FIELDS
        if not crd_only:
            fields = (*fields, ("full_name", "Full name"), ("first_name", "First name"), ("last_name", "Last name"))
        for field, label in fields:
            self.selectors[field] = widgets.Dropdown(description=f"{label}:", layout=widgets.Layout(width="520px"))
        self.sheet.observe(self._on_sheet, names="value")
        self.header.observe(self._on_header, names="value")
        if not crd_only:
            self.name_mode.observe(self._on_name_mode, names="value")
        self._set_header_options(use_proposal=True)
        self._sync_columns(use_proposal=True)
        self._on_name_mode(None)
        controls: list[widgets.Widget] = [self.sheet, self.header]
        if not crd_only:
            controls.append(self.name_mode)
        controls.extend(self.selectors.values())
        self.ui = widgets.VBox(controls)

    def _selected_sheet(self) -> dict[str, Any]:
        return next(sheet for sheet in self.profile["sheets"] if sheet.get("name") == self.sheet.value)

    def _set_header_options(self, *, use_proposal: bool = False) -> None:
        sheet = self._selected_sheet()
        options = [(f"Row {candidate['row_number']}", candidate["row_number"]) for candidate in sheet["header_candidates"]]
        options.append(("Headerless", None))
        proposed = self.proposal.get("header_row", 1) if use_proposal else None
        values = [value for _, value in options]
        self.header.options = options
        self.header.value = proposed if proposed in values else values[0]

    def _columns(self) -> list[dict[str, Any]]:
        sheet = self._selected_sheet()
        if self.header.value is None:
            return sheet["headerless"]["columns"]
        candidate = next(item for item in sheet["header_candidates"] if item["row_number"] == self.header.value)
        return candidate["columns"]

    def _sync_columns(self, *, use_proposal: bool = False) -> None:
        columns = self._columns()
        options = [("Not mapped", None)] + [
            (f"{column['label']} (physical column {int(column['index']) + 1})", int(column["index"]))
            for column in columns
        ]
        values = [value for _, value in options]
        for field, selector in self.selectors.items():
            proposed_ref = self.proposal.get(field) if use_proposal else None
            proposed_index = int(proposed_ref["index"]) if proposed_ref else None
            selector.options = options
            selector.value = proposed_index if proposed_index in values else None

    def _on_sheet(self, _change: Any) -> None:
        self._set_header_options()
        self._sync_columns()

    def _on_header(self, _change: Any) -> None:
        if self.header.options:
            self._sync_columns()

    def _on_name_mode(self, _change: Any) -> None:
        if self.crd_only:
            return
        split = self.name_mode.value == "split"
        self.selectors["full_name"].disabled = split
        self.selectors["first_name"].disabled = not split
        self.selectors["last_name"].disabled = not split

    def mapping(self) -> dict[str, Any]:
        columns = {int(column["index"]): column for column in self._columns()}
        result: dict[str, Any] = {"sheet_name": self.sheet.value, "header_row": self.header.value}
        selected_fields = ["crd_number"] if self.crd_only else [field for field, _ in MATCH_FIELDS]
        if not self.crd_only:
            selected_fields += ["full_name"] if self.name_mode.value == "full_name" else ["first_name", "last_name"]
        for field in selected_fields:
            index = self.selectors[field].value
            if index is not None:
                column = columns[int(index)]
                result[field] = {
                    "index": int(index),
                    "header": column.get("header") if self.header.value is not None else None,
                }
        if self.crd_only and "crd_number" not in result:
            raise ValueError("Select the exact advisor CRD column.")
        has_name = bool(result.get("full_name") or (result.get("first_name") and result.get("last_name")))
        if not self.crd_only and not (result.get("crd_number") or result.get("email") or has_name):
            raise ValueError("Map CRD, email, full name, or both first and last name.")
        return result
"""
    ),
    code(
        r"""
class AdvisorMatchNotebook:
    def __init__(self, api_base_url: str = API_BASE_URL):
        self.api_url = widgets.Text(value=api_base_url, description="API URL:", layout=widgets.Layout(width="620px"))
        self.health_button = widgets.Button(description="Check API", icon="check", button_style="info")
        self.health_output = widgets.Output()
        self.health_button.on_click(self._check_health)

        self.match_upload = widgets.FileUpload(accept=".csv,.xlsx", multiple=False, description="Upload advisor file")
        self.match_analyze = widgets.Button(description="Analyze columns", icon="search", button_style="primary")
        self.match_preview = widgets.Output()
        self.match_status = widgets.Output()
        self.match_form = widgets.VBox()
        self.match_downloads = widgets.Output()
        self.match_analyze.on_click(self._analyze_match)
        self.match_upload.observe(self._reset_match_state, names="value")

        self.firm_resolution = widgets.Dropdown(
            options=[
                ("Automatic policy handling", "auto"),
                ("Keep firms from the mapped column", "use_source"),
                ("Apply one firm to every row", "override_all"),
                ("Continue without firm information", "continue_without_firm"),
            ],
            value="auto",
            description="Firm handling:",
            layout=widgets.Layout(width="620px"),
        )
        self.all_rows_firm = widgets.Text(description="All-rows firm:", disabled=True, layout=widgets.Layout(width="620px"))
        self.firm_resolution.observe(
            lambda change: setattr(self.all_rows_firm, "disabled", change["new"] != "override_all"),
            names="value",
        )
        self.match_run = widgets.Button(description="Start matching", icon="play", button_style="success", disabled=True)
        self.match_run.on_click(self._run_match)
        self.to_profiles = widgets.Button(description="Use matched workbook for profiles", icon="arrow-right", disabled=True)
        self.to_profiles.on_click(self._handoff_profiles)

        self.profile_upload = widgets.FileUpload(accept=".csv,.xlsx", multiple=False, description="Upload CRD file")
        self.profile_analyze = widgets.Button(description="Analyze CRD column", icon="search", button_style="primary")
        self.profile_source_label = widgets.HTML("<i>No profile source selected.</i>")
        self.profile_preview = widgets.Output()
        self.profile_status = widgets.Output()
        self.profile_form = widgets.VBox()
        self.profile_downloads = widgets.Output()
        self.profile_analyze.on_click(self._analyze_profile_upload)
        self.profile_upload.observe(self._reset_profile_state, names="value")
        self.profile_generate = widgets.Button(description="Generate profile report", icon="file", button_style="success", disabled=True)
        self.profile_generate.on_click(self._generate_profile)

        self.match_source: UploadedBytes | None = None
        self.match_analysis: dict[str, Any] | None = None
        self.match_editor: MappingEditor | None = None
        self.match_result: dict[str, Any] | None = None
        self.match_workbook: bytes | None = None
        self.profile_source: UploadedBytes | None = None
        self.profile_analysis: dict[str, Any] | None = None
        self.profile_editor: MappingEditor | None = None

        self.match_tab = widgets.VBox(
            [
                widgets.HTML("<h3>Step 1 — Upload and configure</h3>"),
                widgets.HBox([self.match_upload, self.match_analyze]),
                self.match_status,
                self.match_preview,
                self.match_form,
                widgets.HTML("<h3>Step 2 — Match advisors</h3>"),
                self.firm_resolution,
                self.all_rows_firm,
                self.match_run,
                self.match_downloads,
                self.to_profiles,
            ]
        )
        self.profile_tab = widgets.VBox(
            [
                widgets.HTML("<h3>Step 3 — Generate advisor profiles</h3>"),
                widgets.HBox([self.profile_upload, self.profile_analyze]),
                self.profile_source_label,
                self.profile_status,
                self.profile_preview,
                self.profile_form,
                self.profile_generate,
                self.profile_downloads,
            ]
        )
        self.tabs = widgets.Tab(children=[self.match_tab, self.profile_tab])
        self.tabs.set_title(0, "Advisor matching")
        self.tabs.set_title(1, "Profile generation")
        self.ui = widgets.VBox(
            [
                widgets.HTML("<h2>Advisor Match API notebook</h2>"),
                widgets.HBox([self.api_url, self.health_button]),
                self.health_output,
                self.tabs,
            ]
        )

    def _client(self) -> AdvisorMatchAPIClient:
        return AdvisorMatchAPIClient(self.api_url.value.strip())

    def _reset_match_state(self, _change: Any) -> None:
        self.match_source = None
        self.match_analysis = None
        self.match_editor = None
        self.match_result = None
        self.match_workbook = None
        self.match_run.disabled = True
        self.to_profiles.disabled = True
        self.match_form.children = ()
        self.match_preview.clear_output()
        self.match_downloads.clear_output()

    def _reset_profile_state(self, _change: Any) -> None:
        self.profile_source = None
        self.profile_analysis = None
        self.profile_editor = None
        self.profile_generate.disabled = True
        self.profile_source_label.value = "<i>Upload selected; analyze it to continue.</i>"
        self.profile_form.children = ()
        self.profile_preview.clear_output()
        self.profile_downloads.clear_output()

    @staticmethod
    def _busy(button: widgets.Button, active: bool, normal: str) -> None:
        button.disabled = active
        button.description = "Working…" if active else normal
        button.icon = "spinner" if active else ""

    def _check_health(self, _button: widgets.Button) -> None:
        with self.health_output:
            self.health_output.clear_output()
            try:
                health = self._client().health()
                display(HTML(f'<div style="color:#15803d"><b>API ready:</b> {escape(json.dumps(health))}</div>'))
            except Exception as exc:
                display(HTML(api_error_html(exc)))

    def _analyze_match(self, _button: widgets.Button) -> None:
        self._busy(self.match_analyze, True, "Analyze columns")
        try:
            source = uploaded_bytes(self.match_upload)
            analysis = self._client().map_advisors(source.filename, source.content, source.content_type)
            self.match_source = source
            self.match_analysis = analysis
            self.match_result = None
            self.match_workbook = None
            self.to_profiles.disabled = True
            self.match_downloads.clear_output()
            render_profile_preview(analysis["profile"], self.match_preview)
            self.match_editor = MappingEditor(analysis["profile"], analysis["decision"].get("mapping"))
            notices = []
            question = analysis["decision"].get("clarification_question")
            if question:
                notices.append(f'<div style="color:#92400e"><b>Mapping review:</b> {escape(question)}</div>')
            if analysis.get("validation_error"):
                notices.append(f'<div style="color:#92400e"><b>Validation:</b> {escape(analysis["validation_error"])}</div>')
            for warning in (analysis.get("validation") or {}).get("warnings") or []:
                notices.append(f'<div style="color:#92400e">{escape(warning)}</div>')
            self.match_form.children = (
                widgets.HTML("<h4>Confirm physical column mapping</h4>"),
                widgets.HTML("".join(notices)),
                self.match_editor.ui,
            )
            self.match_run.disabled = False
            with self.match_status:
                self.match_status.clear_output()
                display(HTML(f'<div style="color:#15803d"><b>Analyzed:</b> {escape(source.filename)}</div>'))
        except Exception as exc:
            with self.match_status:
                self.match_status.clear_output()
                display(HTML(api_error_html(exc)))
        finally:
            self._busy(self.match_analyze, False, "Analyze columns")

    def _run_match(self, _button: widgets.Button) -> None:
        self._busy(self.match_run, True, "Start matching")
        try:
            if not self.match_source or not self.match_analysis or not self.match_editor:
                raise ValueError("Analyze an advisor file first.")
            firm = (
                self.all_rows_firm.value.strip() or None
                if self.firm_resolution.value == "override_all"
                else None
            )
            configuration = {
                "analyzed_source_sha256": self.match_analysis["source"]["sha256"],
                "mapping": self.match_editor.mapping(),
                "firm_resolution": self.firm_resolution.value,
                "all_rows_firm": firm,
            }
            result, workbook = self._client().match_advisors(
                self.match_source.filename,
                self.match_source.content,
                configuration,
                self.match_source.content_type,
            )
            self.match_result = result
            self.match_workbook = workbook
            workbook_path = write_download("advisor_matches.xlsx", workbook)
            result_path = write_download("result.json", json.dumps(result, indent=2, sort_keys=True))
            counts = result["counts"]
            with self.match_downloads:
                self.match_downloads.clear_output()
                display(
                    HTML(
                        "<h4>Matching complete</h4>"
                        f"<p><b>Matched:</b> {counts['matched']} &nbsp; "
                        f"<b>Ambiguous:</b> {counts['ambiguous_match']} &nbsp; "
                        f"<b>No match:</b> {counts['no_match']}</p>"
                    )
                )
                for warning in result.get("warnings") or []:
                    display(HTML(f'<div style="color:#92400e">{escape(warning)}</div>'))
                display_download(workbook_path, "Download workbook")
                display_download(result_path, "Download result metadata")
            self.to_profiles.disabled = False
        except Exception as exc:
            with self.match_downloads:
                self.match_downloads.clear_output()
                display(HTML(api_error_html(exc)))
        finally:
            self._busy(self.match_run, False, "Start matching")

    def _handoff_profiles(self, _button: widgets.Button) -> None:
        if not self.match_workbook:
            return
        self.profile_source = UploadedBytes(
            "advisor_matches.xlsx",
            self.match_workbook,
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        self.profile_source_label.value = "<b>Current source:</b> advisor_matches.xlsx (generated match workbook)"
        self.tabs.selected_index = 1
        self._analyze_profile_source()

    def _analyze_profile_upload(self, _button: widgets.Button) -> None:
        try:
            self.profile_source = uploaded_bytes(self.profile_upload)
            self.profile_source_label.value = f"<b>Current source:</b> {escape(self.profile_source.filename)}"
            self._analyze_profile_source()
        except Exception as exc:
            with self.profile_status:
                self.profile_status.clear_output()
                display(HTML(api_error_html(exc)))

    def _analyze_profile_source(self) -> None:
        self._busy(self.profile_analyze, True, "Analyze CRD column")
        try:
            if not self.profile_source:
                raise ValueError("Upload a CRD file or hand off a generated workbook.")
            source = self.profile_source
            analysis = self._client().map_profile(source.filename, source.content, source.content_type)
            self.profile_analysis = analysis
            render_profile_preview(analysis["profile"], self.profile_preview)
            self.profile_editor = MappingEditor(
                analysis["profile"],
                analysis["decision"].get("mapping"),
                crd_only=True,
            )
            notices = []
            if analysis["decision"].get("missing_crd_column"):
                notices.append('<div style="color:#b91c1c"><b>No plausible CRD column was found.</b></div>')
            if analysis["decision"].get("clarification_question"):
                notices.append(
                    f'<div style="color:#92400e"><b>Mapping review:</b> {escape(analysis["decision"]["clarification_question"])}</div>'
                )
            if analysis.get("validation_error"):
                notices.append(f'<div style="color:#92400e"><b>Validation:</b> {escape(analysis["validation_error"])}</div>')
            self.profile_form.children = (
                widgets.HTML("<h4>Confirm CRD mapping</h4>"),
                widgets.HTML("".join(notices)),
                self.profile_editor.ui,
            )
            self.profile_generate.disabled = False
            with self.profile_status:
                self.profile_status.clear_output()
                display(HTML(f'<div style="color:#15803d"><b>Analyzed:</b> {escape(source.filename)}</div>'))
        except Exception as exc:
            with self.profile_status:
                self.profile_status.clear_output()
                display(HTML(api_error_html(exc)))
        finally:
            self._busy(self.profile_analyze, False, "Analyze CRD column")

    def _generate_profile(self, _button: widgets.Button) -> None:
        self._busy(self.profile_generate, True, "Generate profile report")
        try:
            if not self.profile_source or not self.profile_analysis or not self.profile_editor:
                raise ValueError("Analyze a profile source first.")
            configuration = {
                "analyzed_source_sha256": self.profile_analysis["source"]["sha256"],
                "mapping": self.profile_editor.mapping(),
            }
            result = self._client().generate_profile(
                self.profile_source.filename,
                self.profile_source.content,
                configuration,
                self.profile_source.content_type,
            )
            path = write_download(result["filename"], result["html"])
            with self.profile_downloads:
                self.profile_downloads.clear_output()
                display(
                    HTML(
                        "<h4>Profile report complete</h4>"
                        f"<p><b>Input CRDs:</b> {result['input_crd_count']} &nbsp; "
                        f"<b>Unique:</b> {result['unique_crd_count']} &nbsp; "
                        f"<b>Blank:</b> {result['blank_crd_count']} &nbsp; "
                        f"<b>Duplicates:</b> {result['duplicate_crd_count']}</p>"
                        '<div style="border:1px solid #cbd5e1;padding:12px;margin:8px 0">'
                        "The version-1 report intentionally contains an empty HTML body."
                        "</div>"
                    )
                )
                display(HTML(result["html"]))
                display_download(path, "Download HTML report")
        except Exception as exc:
            with self.profile_downloads:
                self.profile_downloads.clear_output()
                display(HTML(api_error_html(exc)))
        finally:
            self._busy(self.profile_generate, False, "Generate profile report")
"""
    ),
    markdown(
        r"""
## Launch the interactive workflow

1. Confirm or change the API URL and select **Check API**.
2. Use the **Advisor matching** tab for upload → mapping → firm handling → workbook downloads.
3. Select **Use matched workbook for profiles** to switch tabs and analyze the generated workbook, or upload an independent CRD file in **Profile generation**.

API validation errors remain visible beside the relevant step. A `422` response preserves your form selections so you can correct the mapping or firm resolution and retry.
"""
    ),
    code(
        r"""
workflow = AdvisorMatchNotebook(API_BASE_URL)
display(workflow.ui)
"""
    ),
    markdown(
        r"""
## Optional programmatic access

The widget UI uses this same client. For automation or debugging, call it directly:

```python
client = AdvisorMatchAPIClient(API_BASE_URL)
analysis = client.map_advisors("input.csv", input_bytes, "text/csv")

configuration = {
    "analyzed_source_sha256": analysis["source"]["sha256"],
    "mapping": confirmed_mapping,
    "firm_resolution": "auto",
    "all_rows_firm": None,
}
result, workbook_bytes = client.match_advisors("input.csv", input_bytes, configuration, "text/csv")
```

Always reuse the exact original bytes between mapping and execution. A different byte sequence returns `409 SOURCE_CHANGED`. Profile mapping and generation follow the same resend-and-confirm pattern.

When finished, `stop_local_api()` stops only an API process launched by this notebook. Closing or restarting the kernel clears uploaded bytes and interactive state.
"""
    ),
]


def main() -> None:
    TARGET.parent.mkdir(parents=True, exist_ok=True)
    for index, cell in enumerate(CELLS):
        digest = hashlib.sha256(cell["source"].encode("utf-8")).hexdigest()[:8]
        cell["id"] = f"advisor-match-{index:02d}-{digest}"
    notebook = {
        "cells": CELLS,
        "metadata": {
            "kernelspec": {
                "display_name": "Python 3 (Advisor Match)",
                "language": "python",
                "name": "python3",
            },
            "language_info": {
                "name": "python",
                "version": "3.11",
                "mimetype": "text/x-python",
                "codemirror_mode": {"name": "ipython", "version": 3},
                "pygments_lexer": "ipython3",
                "nbconvert_exporter": "python",
                "file_extension": ".py",
            },
        },
        "nbformat": 4,
        "nbformat_minor": 5,
    }
    TARGET.write_text(json.dumps(notebook, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
