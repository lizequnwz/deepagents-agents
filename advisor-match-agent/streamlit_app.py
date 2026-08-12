"""Two-workflow Streamlit UI for the stateless Advisor Match API."""

from __future__ import annotations

import hashlib
import os
from typing import Any

import streamlit as st

from advisor_match.ui.api_client import APIError, AdvisorMatchAPIClient

MATCH_FIELDS = (
    ("crd_number", "Advisor CRD"),
    ("firm_name", "Firm"),
    ("email", "Email"),
    ("city", "City"),
    ("state", "State"),
    ("zip_code", "ZIP code"),
)

st.set_page_config(page_title="Advisor Match", page_icon=":material/group:", layout="wide")


@st.cache_resource
def api_client(base_url: str) -> AdvisorMatchAPIClient:
    return AdvisorMatchAPIClient(base_url)


def _initialize_state() -> None:
    defaults = {
        "match_source": None,
        "match_analysis": None,
        "match_result": None,
        "match_workbook": None,
        "match_error": None,
        "profile_source": None,
        "profile_analysis": None,
        "profile_result": None,
        "profile_error": None,
        "profile_auto_analyze": False,
        "profile_handoff_notice": False,
    }
    for key, value in defaults.items():
        st.session_state.setdefault(key, value)


def _source_value(upload: Any) -> dict[str, Any]:
    content = upload.getvalue()
    return {
        "filename": upload.name,
        "content": content,
        "content_type": getattr(upload, "type", None),
        "sha256": hashlib.sha256(content).hexdigest(),
        "origin": "upload",
    }


def _set_source(kind: str, source: dict[str, Any]) -> None:
    key = f"{kind}_source"
    prior = st.session_state.get(key)
    if prior and (
        prior.get("sha256"), prior.get("filename"), prior.get("origin")
    ) == (source["sha256"], source["filename"], source.get("origin")):
        return
    st.session_state[key] = source
    st.session_state[f"{kind}_analysis"] = None
    st.session_state[f"{kind}_result"] = None
    st.session_state[f"{kind}_error"] = None
    if kind == "match":
        st.session_state.match_workbook = None


def _clear_source(kind: str) -> None:
    st.session_state[f"{kind}_source"] = None
    st.session_state[f"{kind}_analysis"] = None
    st.session_state[f"{kind}_result"] = None
    st.session_state[f"{kind}_error"] = None
    if kind == "match":
        st.session_state.match_workbook = None


def _analyze_match(client: AdvisorMatchAPIClient) -> None:
    source = st.session_state.match_source
    if not source:
        return
    try:
        st.session_state.match_analysis = client.map_advisors(
            source["filename"], source["content"], source["content_type"]
        )
        st.session_state.match_error = None
    except APIError as exc:
        st.session_state.match_error = exc


def _analyze_profile(client: AdvisorMatchAPIClient) -> None:
    source = st.session_state.profile_source
    if not source:
        return
    try:
        st.session_state.profile_analysis = client.map_profile(
            source["filename"], source["content"], source["content_type"]
        )
        st.session_state.profile_error = None
    except APIError as exc:
        st.session_state.profile_error = exc


def _continue_to_profile_generation() -> None:
    """Hand the generated workbook to the profile tab before the next rerun."""

    workbook = st.session_state.match_workbook
    if not workbook:
        return
    st.session_state.pop("profile_upload", None)
    _set_source(
        "profile",
        {
            "filename": "advisor_matches.xlsx",
            "content": workbook,
            "content_type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            "sha256": hashlib.sha256(workbook).hexdigest(),
            "origin": "handoff",
        },
    )
    st.session_state.profile_auto_analyze = True
    st.session_state.profile_handoff_notice = True
    st.session_state.workflow_tabs = "Profile Generation"


def _render_match_tab(client: AdvisorMatchAPIClient, max_upload_mb: int) -> None:
    st.subheader("Advisor Matching")
    st.caption("Upload and configure one file, then run deterministic matching.")
    upload = st.file_uploader(
        "Advisor CSV or Excel file",
        type=["csv", "xlsx"],
        key="match_upload",
        max_upload_size=max_upload_mb,
    )
    if upload is not None:
        _set_source("match", _source_value(upload))
    elif st.session_state.match_source is not None:
        _clear_source("match")
    source = st.session_state.match_source
    if source and st.button(
        "Analyze columns", icon=":material/schema:", type="primary", key="match_analyze"
    ):
        with st.spinner("Inspecting the file and proposing column mappings…"):
            _analyze_match(client)
    _render_api_error(st.session_state.match_error)

    analysis = st.session_state.match_analysis
    if not analysis:
        return
    _render_profile_preview(analysis["profile"])
    decision = analysis["decision"]
    if decision.get("clarification_question"):
        st.warning(decision["clarification_question"], icon=":material/help:")
    if analysis.get("validation_error"):
        st.warning(analysis["validation_error"], icon=":material/warning:")
    validation = analysis.get("validation") or {}
    for warning in validation.get("warnings") or []:
        st.info(warning, icon=":material/info:")

    st.markdown("#### Confirm column mapping")
    name_mode = _name_mapping_mode(analysis)
    with st.form("match_configuration"):
        mapping = _match_mapping_form(analysis, name_mode)
        st.markdown("#### Firm handling")
        firm_options = {
            "Automatic policy handling": "auto",
            "Keep firms from the mapped column": "use_source",
            "Apply one firm to every row": "override_all",
            "Continue without firm information": "continue_without_firm",
        }
        firm_label = st.selectbox("Resolution", list(firm_options), key="firm_resolution")
        firm_resolution = firm_options[firm_label]
        all_rows_firm = (
            st.text_input("Firm applied to every row", max_chars=200).strip()
            if firm_resolution == "override_all"
            else None
        )
        submitted = st.form_submit_button(
            "Start matching", icon=":material/play_arrow:", type="primary"
        )
    if submitted:
        if mapping is None:
            st.error("Map CRD, email, full name, or both first and last name.")
        elif firm_resolution == "override_all" and not all_rows_firm:
            st.error("Enter the firm that applies to every row.")
        else:
            configuration = {
                "analyzed_source_sha256": analysis["source"]["sha256"],
                "mapping": mapping,
                "firm_resolution": firm_resolution,
                "all_rows_firm": all_rows_firm,
            }
            try:
                with st.spinner("Matching advisors and building the workbook…"):
                    result, workbook = client.match_advisors(
                        source["filename"],
                        source["content"],
                        configuration,
                        source["content_type"],
                    )
                st.session_state.match_result = result
                st.session_state.match_workbook = workbook
                st.session_state.match_error = None
            except APIError as exc:
                st.session_state.match_error = exc
                st.session_state.match_result = None
                st.session_state.match_workbook = None
            st.rerun()

    _render_match_result()


def _render_match_result() -> None:
    result = st.session_state.match_result
    workbook = st.session_state.match_workbook
    if not result or not workbook:
        return
    st.success("Advisor matching is complete.", icon=":material/check_circle:")
    counts = result["counts"]
    columns = st.columns(3)
    columns[0].metric("Matched", counts["matched"])
    columns[1].metric("Ambiguous", counts["ambiguous_match"])
    columns[2].metric("No match", counts["no_match"])
    for warning in result.get("warnings") or []:
        st.warning(warning, icon=":material/warning:")
    with st.container(horizontal=True):
        st.download_button(
            "Download advisor_matches.xlsx",
            data=workbook,
            file_name="advisor_matches.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            icon=":material/download:",
            type="primary",
        )
        st.button(
            "Continue to profile generation",
            icon=":material/description:",
            key="continue_to_profiles",
            on_click=_continue_to_profile_generation,
        )


def _render_profile_tab(client: AdvisorMatchAPIClient, max_upload_mb: int) -> None:
    st.subheader("Profile Generation")
    st.caption("Confirm one CRD column and generate a placeholder HTML report.")
    upload = st.file_uploader(
        "CRD CSV or Excel file",
        type=["csv", "xlsx"],
        key="profile_upload",
        max_upload_size=max_upload_mb,
    )
    if upload is not None:
        _set_source("profile", _source_value(upload))
    elif (
        st.session_state.profile_source
        and st.session_state.profile_source.get("origin") == "upload"
    ):
        _clear_source("profile")
    source = st.session_state.profile_source
    if source:
        st.caption(f"Current source: {source['filename']}")
    if source and st.button(
        "Analyze CRD column",
        icon=":material/schema:",
        type="primary",
        key="profile_analyze",
    ):
        with st.spinner("Inspecting the file and locating the CRD column…"):
            _analyze_profile(client)
    if source and st.session_state.pop("profile_auto_analyze", False):
        with st.spinner("Inspecting the matched-advisor workbook…"):
            _analyze_profile(client)

    _render_api_error(st.session_state.profile_error)
    analysis = st.session_state.profile_analysis
    if not analysis:
        return
    _render_profile_preview(analysis["profile"])
    decision = analysis["decision"]
    if decision.get("missing_crd_column"):
        st.error("No plausible CRD column was found in this file.")
    if decision.get("clarification_question"):
        st.warning(decision["clarification_question"], icon=":material/help:")
    if analysis.get("validation_error"):
        st.warning(analysis["validation_error"], icon=":material/warning:")

    with st.form("profile_configuration"):
        st.markdown("#### Confirm CRD mapping")
        mapping = _profile_mapping_form(analysis)
        submitted = st.form_submit_button(
            "Generate profile report", icon=":material/description:", type="primary"
        )
    if submitted:
        if mapping is None:
            st.error("Select the exact column containing advisor CRDs.")
        else:
            try:
                with st.spinner("Generating the profile report…"):
                    st.session_state.profile_result = client.generate_profile(
                        source["filename"],
                        source["content"],
                        {
                            "analyzed_source_sha256": analysis["source"]["sha256"],
                            "mapping": mapping,
                        },
                        source["content_type"],
                    )
                st.session_state.profile_error = None
            except APIError as exc:
                st.session_state.profile_error = exc
                st.session_state.profile_result = None
            st.rerun()
    _render_profile_result()


def _name_mapping_mode(analysis: dict[str, Any]) -> str:
    """Render the name-layout control outside the form so it reruns immediately."""

    proposal = analysis["decision"].get("mapping") or {}
    full_name_mode = "One full-name column"
    split_name_mode = "Separate first and last name columns"
    default = full_name_mode if proposal.get("full_name") else split_name_mode
    return st.segmented_control(
        "Name mapping",
        [full_name_mode, split_name_mode],
        default=default,
        required=True,
        key="match_name_mode",
        help=(
            "Choose one full-name column when the complete advisor name is stored in "
            "a single column. Choose separate columns when first and last names are "
            "stored in two columns."
        ),
    )


def _match_mapping_form(
    analysis: dict[str, Any], name_mode: str
) -> dict[str, Any] | None:
    proposal = analysis["decision"].get("mapping") or {}
    sheet_name, header_row, columns = _table_selection(
        analysis["profile"], proposal, "match"
    )
    column_by_index = {int(column["index"]): column for column in columns}

    result: dict[str, Any] = {"sheet_name": sheet_name, "header_row": header_row}
    for field, label in MATCH_FIELDS:
        selected = _column_selector(
            label, columns, _proposal_index(proposal, field), f"match_{field}"
        )
        if selected is not None:
            result[field] = _column_ref(column_by_index[selected], header_row)
    if name_mode == "One full-name column":
        selected = _column_selector(
            "Advisor full name",
            columns,
            _proposal_index(proposal, "full_name"),
            "match_full_name",
        )
        if selected is not None:
            result["full_name"] = _column_ref(column_by_index[selected], header_row)
    else:
        for field, label in (("first_name", "First name"), ("last_name", "Last name")):
            selected = _column_selector(
                label, columns, _proposal_index(proposal, field), f"match_{field}"
            )
            if selected is not None:
                result[field] = _column_ref(column_by_index[selected], header_row)
    has_name = bool(result.get("full_name") or (result.get("first_name") and result.get("last_name")))
    return result if result.get("crd_number") or result.get("email") or has_name else None


def _profile_mapping_form(analysis: dict[str, Any]) -> dict[str, Any] | None:
    proposal = analysis["decision"].get("mapping") or {}
    sheet_name, header_row, columns = _table_selection(
        analysis["profile"], proposal, "profile"
    )
    selected = _column_selector(
        "Advisor CRD",
        columns,
        _proposal_index(proposal, "crd_number"),
        "profile_crd_number",
    )
    if selected is None:
        return None
    column = next(item for item in columns if int(item["index"]) == selected)
    return {
        "sheet_name": sheet_name,
        "header_row": header_row,
        "crd_number": _column_ref(column, header_row),
    }


def _table_selection(
    profile: dict[str, Any], proposal: dict[str, Any], prefix: str
) -> tuple[str | None, int | None, list[dict[str, Any]]]:
    sheets = profile["sheets"]
    names = [sheet.get("name") for sheet in sheets]
    proposed_sheet = proposal.get("sheet_name")
    sheet_index = names.index(proposed_sheet) if proposed_sheet in names else 0
    selected_name = st.selectbox(
        "Worksheet",
        names,
        index=sheet_index,
        format_func=lambda value: value or "CSV / first worksheet",
        key=f"{prefix}_sheet",
    )
    sheet = next(item for item in sheets if item.get("name") == selected_name)
    header_options = [item["row_number"] for item in sheet["header_candidates"]] + [None]
    proposed_header = proposal.get("header_row", 1)
    header_index = header_options.index(proposed_header) if proposed_header in header_options else 0
    header_row = st.selectbox(
        "Header row",
        header_options,
        index=header_index,
        format_func=lambda value: "Headerless" if value is None else f"Row {value}",
        key=f"{prefix}_header",
    )
    if header_row is None:
        columns = sheet["headerless"]["columns"]
    else:
        candidate = next(
            item for item in sheet["header_candidates"] if item["row_number"] == header_row
        )
        columns = candidate["columns"]
    return selected_name, header_row, columns


def _column_selector(
    label: str,
    columns: list[dict[str, Any]],
    proposed_index: int | None,
    key: str,
) -> int | None:
    options: list[int | None] = [None] + [int(item["index"]) for item in columns]
    selected_index = options.index(proposed_index) if proposed_index in options else 0
    by_index = {int(item["index"]): item for item in columns}
    return st.selectbox(
        label,
        options,
        index=selected_index,
        format_func=lambda value: "Not mapped"
        if value is None
        else f"{by_index[value]['label']} (column {value + 1})",
        key=key,
    )


def _column_ref(column: dict[str, Any], header_row: int | None) -> dict[str, Any]:
    return {
        "index": int(column["index"]),
        "header": column.get("header") if header_row is not None else None,
    }


def _proposal_index(proposal: dict[str, Any], field: str) -> int | None:
    reference = proposal.get(field)
    return int(reference["index"]) if reference else None


def _render_profile_preview(profile: dict[str, Any]) -> None:
    with st.expander("File preview", icon=":material/table_view:"):
        for sheet in profile.get("sheets") or []:
            st.markdown(f"**{sheet.get('name') or 'CSV'}**")
            preview = sheet.get("preview_rows") or []
            if preview:
                st.dataframe(
                    [
                        {"Source row": row["row_number"], "Values": " | ".join(row["values"])}
                        for row in preview
                    ],
                    hide_index=True,
                    width="stretch",
                )


def _render_profile_result() -> None:
    result = st.session_state.profile_result
    if not result:
        return
    st.success(
        f"Profile report generated for {result['unique_crd_count']} unique CRDs.",
        icon=":material/check_circle:",
    )
    html = result["html"]
    st.html(html, unsafe_allow_javascript=False)
    st.download_button(
        "Download advisor_profile_report.html",
        data=html.encode("utf-8"),
        file_name=result["filename"],
        mime=result["media_type"],
        icon=":material/download:",
        type="primary",
    )


def _render_api_error(error: APIError | None) -> None:
    if error is None:
        return
    st.error(str(error), icon=":material/error:")
    if error.details:
        st.json(error.details, expanded=False)


_initialize_state()
client = api_client(os.getenv("API_BASE_URL", "http://127.0.0.1:8001"))
try:
    health = client.health()
except APIError as exc:
    st.error(str(exc), icon=":material/cloud_off:")
    st.stop()

st.title("Advisor Match")
st.caption("Stateless advisor matching and placeholder profile generation")

match_tab, profile_tab = st.tabs(
    ["Advisor Matching", "Profile Generation"],
    key="workflow_tabs",
    default="Advisor Matching",
    on_change="rerun",
)
if st.session_state.pop("profile_handoff_notice", False):
    st.toast(
        "Matched workbook loaded. Confirm the CRD mapping to generate profiles.",
        icon=":material/check_circle:",
    )
max_upload_mb = int(os.getenv("MAX_UPLOAD_MB", "100"))
with match_tab:
    _render_match_tab(client, max_upload_mb)
with profile_tab:
    _render_profile_tab(client, max_upload_mb)

st.caption(f"API {health['version']} · In-progress files exist only in this browser session.")
