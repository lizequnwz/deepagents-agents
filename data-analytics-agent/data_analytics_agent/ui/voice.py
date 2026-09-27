"""Dictation from the chat composer, with review before sending."""

import streamlit as st

from data_analytics_agent.ui.api_client import APIError


def prepare_voice_draft(client, chat_key):
    """Transcribe a submitted recording before rendering the editable composer."""
    prefix = f"voice_{chat_key}"
    pending = st.session_state.get(f"{prefix}_pending")
    if pending:
        error = st.session_state.get(f"{prefix}_error")
        retry = False
        if error:
            st.error(error)
            retry = st.button("Retry transcription", key=f"{prefix}_retry")
            if st.button("Discard recording", key=f"{prefix}_discard"):
                st.session_state[chat_key] = pending["text"]
                st.session_state.pop(f"{prefix}_pending")
                st.session_state.pop(f"{prefix}_error", None)
                st.rerun()
        if not error or retry:
            try:
                with st.spinner("Transcribing…"):
                    text = client.transcribe(pending["audio"])
            except APIError as exc:
                st.session_state[f"{prefix}_error"] = str(exc)
                st.rerun()
            else:
                st.session_state[f"{prefix}_text"] = "\n\n".join(
                    part for part in (pending["text"], text) if part
                )
                st.session_state.pop(f"{prefix}_pending")
                st.session_state.pop(f"{prefix}_error", None)
                st.rerun()
    if text := st.session_state.pop(f"{prefix}_text", None):
        st.session_state[chat_key] = text
        st.toast("Transcription ready. Review your question, then send.")
    files = st.session_state.get(f"{prefix}_files")
    if files and st.button(
        f"Remove attachment: {files[0].name}",
        icon=":material/close:",
        key=f"{prefix}_remove_file",
    ):
        st.session_state.pop(f"{prefix}_files")
        st.rerun()


def review_voice_submission(submission, chat_key):
    """Hold audio for transcription; release only explicitly submitted text/files."""
    if not submission:
        return None
    prefix = f"voice_{chat_key}"
    if submission.audio:
        st.session_state[f"{prefix}_pending"] = {
            "audio": submission.audio.getvalue(),
            "text": submission.text,
        }
        if submission.files:
            st.session_state[f"{prefix}_files"] = submission.files
        st.session_state.pop(f"{prefix}_error", None)
        st.rerun()
    # A new attachment replaces the one retained during transcription.
    files = st.session_state.pop(f"{prefix}_files", [])
    if not submission.files:
        submission.files = files
    st.session_state.pop(f"{prefix}_pending", None)
    st.session_state.pop(f"{prefix}_error", None)
    return submission
