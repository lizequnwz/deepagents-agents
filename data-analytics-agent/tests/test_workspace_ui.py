"""Native document inspection keeps table review separate from source context."""

import pytest
from streamlit.testing.v1 import AppTest


class DocumentClient:
    def __init__(self):
        self.imports = []

    def list_documents(self, thread_id):
        return [
            {
                "document_id": "doc",
                "filename": "annual.pdf",
                "page_count": 2,
                "table_count": 1,
            }
        ]

    def document_download_url(self, thread_id, document_id):
        return "http://localhost/documents/doc/download"

    def inspect_document(self, thread_id, document_id, page):
        return {
            "page": page,
            "text": "Amounts are in declared source units.",
            "tables": [
                {
                    "table_index": 0,
                    "row_count": 3,
                    "preview": [["year", "amount"], ["2025", "10"], ["2026", "20"]],
                }
            ],
        }

    def import_document_table(self, thread_id, document_id, table_index, header_row):
        self.imports.append((thread_id, document_id, table_index, header_row))


def workspace_view(is_file):
    import streamlit as st
    from data_analytics_agent.ui.workspace import render_workspace_documents

    render_workspace_documents(
        st.session_state.client,
        "thread",
        is_file=is_file,
        disabled=False,
    )


@pytest.mark.parametrize("is_file", [True, False])
def test_document_preview_and_explicit_table_review(is_file):
    client = DocumentClient()
    app = AppTest.from_function(workspace_view, args=(is_file,))
    app.session_state["client"] = client
    app.run()
    assert not app.exception
    assert not app.get("file_uploader")
    assert all(item.label != "Add data and documents" for item in app.expander)
    next(
        button
        for button in app.button
        if button.label == "Show page and extracted tables"
    ).click().run()
    assert not app.exception
    assert "declared source units" in app.text[0].value
    review = [
        button
        for button in app.button
        if button.label == "Review this table for analysis"
    ]
    assert bool(review) == is_file
    if is_file:
        next(
            field
            for field in app.number_input
            if field.label == "Column names are on table row"
        ).set_value(2)
        review[0].click().run()
        assert not app.exception
        assert client.imports == [("thread", "doc", 0, 1)]
    else:
        assert not client.imports


def test_composer_accepts_text_corrections_with_stable_attachment_controls():
    app = AppTest.from_string("""
import streamlit as st
from data_analytics_agent.ui.uploads import chat_submission
submission = chat_submission(
    "Add a correction", key="correction", max_bytes=1000,
    client=None,
)
if submission:
    st.session_state["sent"] = (submission.text, submission.files)
""").run()
    assert not app.exception
    assert app.chat_input[0].proto.accept_file
    assert app.chat_input[0].proto.accept_audio
    app.chat_input[0].set_value("Use the full year").run()
    assert not app.exception
    assert app.session_state["sent"] == ("Use the full year", [])


def test_composer_reviews_audio_corrections_with_attachment_controls(monkeypatch):
    from types import SimpleNamespace

    import streamlit as st

    native = st.chat_input

    def recorded(*args, **kwargs):
        value = native(*args, **kwargs)
        if not st.session_state.get("recording_delivered"):
            st.session_state["recording_delivered"] = True
            return SimpleNamespace(
                audio=SimpleNamespace(getvalue=lambda: b"recorded wav"),
                text="",
                files=[],
            )
        return value

    monkeypatch.setattr(st, "chat_input", recorded)
    app = AppTest.from_string("""
import streamlit as st
from data_analytics_agent.ui.uploads import chat_submission
class Client:
    def transcribe(self, content):
        st.session_state["transcribed"] = content
        return "Use source units"
submission = chat_submission(
    "Add a correction", key="correction", max_bytes=1000,
    client=Client(),
)
if submission:
    st.session_state["sent"] = (submission.text, submission.files)
""").run()
    assert not app.exception
    assert app.session_state["transcribed"] == b"recorded wav"
    assert app.chat_input[0].proto.value == "Use source units"
    assert "sent" not in app.session_state
    app.chat_input[0].set_value("Use the declared source units").run()
    assert not app.exception
    assert app.session_state["sent"] == ("Use the declared source units", [])
