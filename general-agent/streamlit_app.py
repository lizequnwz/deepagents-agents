"""Entry point for the general assistant and repository workbench."""

import streamlit as st

st.set_page_config(page_title="Deep Agent", page_icon=":material/assistant:",
                   layout="wide", initial_sidebar_state="expanded")

st.navigation([
    st.Page("app_pages/general.py", title="General assistant", icon=":material/assistant:", default=True),
    st.Page("app_pages/coding.py", title="Coding workbench", icon=":material/code:"),
]).run()
