import os
from pathlib import Path

import streamlit as st

# Attempt to load environment variables from .env if present
try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

from src.database import get_database_stats, init_db, reset_database
from src.engine import TextToSQLEngine
from src.providers import OpenRouterProvider
from src.ui import (
    render_architecture_tab,
    render_live_query_tab,
    render_schema_explorer_tab,
)

st.set_page_config(page_title="Text-to-SQL", layout="wide", initial_sidebar_state="expanded")

CUSTOM_CSS = """
<style>
    /* Code Blocks */
    .stCodeBlock {
        border-radius: 8px !important;
    }

    /* Sidebar Section Divider */
    .sidebar-section {
        margin-top: 15px;
        margin-bottom: 15px;
        border-top: 1px solid #334155;
    }
</style>
"""
st.markdown(CUSTOM_CSS, unsafe_allow_html=True)


DB_PATH = "ecommerce.db"

# Ensure database exists and is seeded with deterministic mock records
if not Path(DB_PATH).exists():
    init_db(DB_PATH)


with st.sidebar:
    st.markdown("## Configuration")

    st.markdown("### Model")
    st.caption(f"`{OpenRouterProvider.DEFAULT_MODEL}` (free on OpenRouter)")

    env_key = os.environ.get("OPENROUTER_API_KEY", "")
    sidebar_key = st.text_input(
        "OpenRouter API Key:",
        value=env_key,
        type="password",
        placeholder="Enter your sk-or-v1-... key",
        help="OpenRouter API key used for live generation. Reads from .env by default.",
    )
    api_key = sidebar_key.strip() if sidebar_key else env_key

    st.markdown('<div class="sidebar-section"></div>', unsafe_allow_html=True)

    st.markdown("### Database")
    st.caption(f"`{DB_PATH}`")

    stats = get_database_stats(DB_PATH)

    for tbl_name, count in stats.items():
        st.text(f"• {tbl_name.capitalize()}: {count} rows")

    if st.button(
        "Reset database",
        width="stretch",
        help="Drops any writes you approved and re-seeds from scratch",
    ):
        with st.spinner("Resetting and re-seeding database..."):
            reset_database(DB_PATH)
            st.session_state["last_query_result"] = None
            st.success("Database re-seeded.")
            st.rerun()

    if stats:
        with st.expander("Browse tables", expanded=False):
            selected_table = st.selectbox(
                "Select table to preview:", options=list(stats.keys()), key="sidebar_table_inspect"
            )
            if selected_table:
                try:
                    import pandas as pd

                    from src.database import execute_readonly_query

                    cols, rows = execute_readonly_query(
                        f"SELECT * FROM `{selected_table}` LIMIT 10;", DB_PATH
                    )
                    if rows:
                        df_preview = pd.DataFrame(rows, columns=cols)
                        st.dataframe(df_preview, width="stretch", hide_index=True)
                    else:
                        st.info("Table is empty.")
                except Exception as e:
                    st.caption(f"Could not preview table: {e}")


# One engine per browser session. A new key typed into the sidebar replaces its provider.
if "sql_engine" not in st.session_state:
    st.session_state["sql_engine"] = TextToSQLEngine(db_path=DB_PATH, api_key=api_key)
engine = st.session_state["sql_engine"]
if engine.provider.api_key != api_key:
    engine.provider = OpenRouterProvider(api_key=api_key)


st.markdown("# Text-to-SQL")
st.markdown(
    "Ask a question in plain English and get a SQLite query back. Every query is checked "
    "before it runs, and anything that writes needs your approval first."
)
st.markdown("<br>", unsafe_allow_html=True)

tab_query, tab_schema, tab_arch = st.tabs(["Query", "Schema", "How it works"])

with tab_query:
    render_live_query_tab(engine=engine, db_path=DB_PATH)

with tab_schema:
    render_schema_explorer_tab(db_path=DB_PATH)

with tab_arch:
    render_architecture_tab()
