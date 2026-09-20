"""Native file entry and explicit schema/grain review before analytical work."""

import streamlit as st
from data_analytics_agent.ui.api_client import APIError
from data_analytics_agent.uploads import TYPE_LABELS


def chat_submission(placeholder, *, key, max_bytes):
    """Native single-file attachment and text composer."""
    return st.chat_input(
        placeholder,
        key=key,
        accept_file=True,
        file_type=["csv", "parquet"],
        max_upload_size=max(1, (max_bytes + 1_048_575) // 1_048_576),
        submit_mode="disable",
    )


def stage_attachment(client, submission, max_bytes):
    """Stage only the attached file; its question waits for schema confirmation."""
    uploaded = submission.files[0]
    if uploaded.size > max_bytes:
        raise APIError(f"File exceeds the {max_bytes:,}-byte upload limit.")
    return client.upload_file(uploaded.name, uploaded.getvalue())


def render_upload_review(client, upload):
    st.subheader("Review uploaded data")
    st.caption(
        f"{upload['filename']} · {upload['row_count']:,} rows · {len(upload['columns'])} columns"
    )
    st.info(
        "Types describe file structure. They do not establish business meaning. Keep identifiers as text and choose date formats explicitly."
    )
    st.dataframe(
        upload["sample_rows"],
        hide_index=True,
        key=f"upload_preview_{upload['thread_id']}",
    )
    st.caption(
        "Preview: at most 10 rows. Type checks and declared key checks use the entire file."
    )
    names = [column["name"] for column in upload["columns"]]
    with st.form(f"review_upload_{upload['thread_id']}"):
        selected = st.data_editor(
            [
                {
                    "Column": c["name"],
                    "Stored type": c["stored_type"],
                    "Use as": TYPE_LABELS[c["suggested_type"]],
                    "Missing": c["null_count"],
                    "Distinct": c["distinct_count"],
                    "Review note": c["warning"],
                }
                for c in upload["columns"]
            ],
            hide_index=True,
            disabled=["Column", "Stored type", "Missing", "Distinct", "Review note"],
            column_config={
                "Use as": st.column_config.SelectboxColumn(
                    options=list(TYPE_LABELS.values()), required=True
                )
            },
            key=f"upload_types_{upload['thread_id']}",
        )
        grain = st.text_input(
            "What does one row represent? (optional)",
            max_chars=500,
            placeholder="For example, one order line; leave blank if unknown",
        )
        keys = st.multiselect(
            "Columns that uniquely identify a row (optional)",
            names,
            help="Declared keys must be unique and nonempty across the complete file. Rows are never silently deduplicated.",
        )
        submitted = st.form_submit_button(
            "Confirm schema and start conversation", type="primary"
        )
    if submitted:
        try:
            with st.spinner("Checking all rows and saving reviewed data…"):
                client.confirm_upload(
                    upload["thread_id"],
                    {
                        "types": {
                            row["Column"]: {
                                label: kind for kind, label in TYPE_LABELS.items()
                            }[row["Use as"]]
                            for row in selected
                        },
                        "grain": grain,
                        "key_columns": keys,
                    },
                )
        except APIError as exc:
            st.error(str(exc))
            return
        st.rerun()
