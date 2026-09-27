"""Native record/stop control: dictation fills the composer, never submits it."""

from hashlib import sha256

import streamlit as st

from data_analytics_agent.ui.api_client import APIError


def render_voice_input(client, chat_key):
    prefix = f"voice_{chat_key}"
    generation = st.session_state.get(prefix, 0)
    audio = st.audio_input(
        "Record a question",
        key=f"{prefix}_{generation}",
        label_visibility="collapsed",
        sample_rate=16000,
        help="Allow microphone access, record, then stop. Review the transcription in the question box before sending. Microphone access requires localhost or HTTPS.",
    )
    notice = st.empty()
    if not audio:
        return
    digest = sha256(audio.getvalue()).hexdigest()
    attempted = st.session_state.get(f"{prefix}_attempt") == digest
    retry = False
    if attempted and (error := st.session_state.get(f"{prefix}_error")):
        notice.error(error)
        retry = st.button("Retry transcription", key=f"{prefix}_retry")
    if attempted and not retry:
        return
    st.session_state[f"{prefix}_attempt"] = digest
    try:
        with st.spinner("Transcribing…"):
            text = client.transcribe(audio.getvalue())
    except APIError as exc:
        st.session_state[f"{prefix}_error"] = str(exc)
        st.rerun()
    else:
        notice.empty()
        st.session_state[f"{prefix}_text"] = text
        st.session_state.pop(f"{prefix}_error", None)
        st.session_state.pop(f"{prefix}_attempt", None)
        # Replacing the recording widget releases its audio; no audio is persisted.
        st.session_state[prefix] = generation + 1
        st.rerun()
