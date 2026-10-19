"""Inspect attached documents and review extracted tables for analysis."""

import streamlit as st

from data_analytics_agent.ui.api_client import APIError


def render_workspace_documents(client, thread_id, *, is_file, disabled):
    documents = client.list_documents(thread_id)
    if not documents:
        return
    with st.expander(f"Reference documents · {len(documents)}"):
        by_id = {doc["document_id"]: doc for doc in documents}
        selected = st.selectbox(
            "Document",
            list(by_id),
            format_func=lambda key: by_id[key]["filename"],
            key=f"document_{thread_id}",
        )
        doc = by_id[selected]
        st.caption(
            f"{doc['page_count']} pages · {doc['table_count']} extracted tables. Content is unreviewed context."
        )
        st.link_button(
            "Download original document",
            client.document_download_url(thread_id, selected),
        )
        with st.form(f"document_page_{selected}"):
            page = st.number_input(
                "Page", min_value=1, max_value=doc["page_count"], value=1
            )
            inspect = st.form_submit_button("Show page and extracted tables")
        preview_key = f"document_preview_{selected}"
        if inspect:
            try:
                st.session_state[preview_key] = client.inspect_document(
                    thread_id, selected, page
                )
            except APIError as exc:
                st.error(str(exc))
        if preview := st.session_state.get(preview_key):
            st.caption(f"Page {preview['page']}")
            st.text("\n".join(preview["text"].splitlines()[:10]))
            for table in preview["tables"]:
                st.write(
                    f"Table {table['table_index'] + 1} · {table['row_count']} rows including headers"
                )
                st.dataframe(table["preview"], hide_index=True)
                if is_file:
                    with st.form(f"document_table_{selected}_{table['table_index']}"):
                        header = st.number_input(
                            "Column names are on table row",
                            min_value=1,
                            max_value=table["row_count"] - 1,
                            value=1,
                        )
                        use = st.form_submit_button(
                            "Review this table for analysis", disabled=disabled
                        )
                    if use:
                        try:
                            client.import_document_table(
                                thread_id, selected, table["table_index"], header - 1
                            )
                        except APIError as exc:
                            st.error(str(exc))
                        else:
                            st.rerun()
