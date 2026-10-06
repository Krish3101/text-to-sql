"""Streamlit application entry point for Text-to-SQL."""

import os

import streamlit as st
from dotenv import load_dotenv

from text_to_sql.config import DEFAULT_DB_PATH, get_model
from text_to_sql.database import init_db
from text_to_sql.engine import TextToSQLEngine
from text_to_sql.llm import OpenRouterProvider
from ui import render_live_query_tab, render_schema_explorer_tab

load_dotenv()

st.set_page_config(
    page_title="Text-to-SQL",
    layout="wide",
    initial_sidebar_state="collapsed",
)


@st.cache_resource
def ensure_database() -> None:
    # Builds the DB if it is missing or was built from an older seed (user_version check).
    init_db(DEFAULT_DB_PATH)


ensure_database()

# Retrieve API key without leaking it to browser UI
env_key = os.environ.get("OPENROUTER_API_KEY", "").strip()
session_key = st.session_state.get("user_api_key", "").strip()
active_key = session_key or env_key

# Page Title & Subtitle
st.title("Text-to-SQL")
st.write(
    "Ask a question in English. Only read-only SELECT queries run; anything that changes data is rejected."
)

# If no API key is available, render inline setup banner
if not active_key:
    st.info("Add a free OpenRouter key to generate SQL. You can still test the guardrail below.")
    inline_key = st.text_input(
        "OpenRouter API Key:",
        type="password",
        placeholder="Enter your sk-or-v1-... key",
        help="Used to call the free model. Keys are never saved or committed.",
        key="inline_api_key_input",
    )
    if inline_key.strip():
        st.session_state["user_api_key"] = inline_key.strip()
        st.rerun()
else:
    col_info, col_ovr = st.columns([5, 3])
    with col_info:
        model_msg = f"Model: `{get_model()}`"
        source_msg = (
            " (using key from `.env`)" if not session_key and env_key else " (session key active)"
        )
        st.caption(f"{model_msg}{source_msg}")
    with col_ovr:
        with st.expander("Change API key", expanded=False):
            new_key = st.text_input("Override API Key:", type="password", key="override_key_input")
            if st.button("Apply Key"):
                st.session_state["user_api_key"] = new_key.strip()
                st.rerun()

# Engine instance per browser session
if "sql_engine" not in st.session_state:
    st.session_state["sql_engine"] = TextToSQLEngine(db_path=DEFAULT_DB_PATH, api_key=active_key)
engine = st.session_state["sql_engine"]
if (engine.provider.api_key or "") != (active_key or ""):
    engine.provider = OpenRouterProvider(api_key=active_key)

tab_query, tab_schema = st.tabs(["Query", "Schema"])

with tab_query:
    render_live_query_tab(engine=engine, has_key=engine.provider.is_available())

with tab_schema:
    render_schema_explorer_tab(db_path=DEFAULT_DB_PATH)
