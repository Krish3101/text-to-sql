"""
Text-to-SQL Generator (Version 1.0)
Author: Krish Kalya <krishkalya31012005@gmail.com>
"""

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
from src.ui import (
    render_architecture_tab,
    render_live_query_tab,
    render_schema_explorer_tab,
)

# ==============================================================================
# Streamlit Page Configuration & Custom CSS
# ==============================================================================

st.set_page_config(
    page_title="Text-to-SQL Generator",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded"
)

CUSTOM_CSS = """
<style>
    /* Metric Card Styling */
    div[data-testid="stMetricValue"] {
        font-size: 1.75rem !important;
        font-weight: 700 !important;
    }

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

    /* Badges */
    .badge {
        display: inline-block;
        padding: 4px 10px;
        border-radius: 6px;
        font-size: 0.8rem;
        font-weight: 600;
        background-color: #1e293b;
        color: #38bdf8;
        border: 1px solid #38bdf8;
        margin-bottom: 8px;
    }
</style>
"""
st.markdown(CUSTOM_CSS, unsafe_allow_html=True)


# ==============================================================================
# Database Initialization & Session State
# ==============================================================================

DB_PATH = "ecommerce.db"

# Ensure database exists and is seeded with deterministic mock records
if not Path(DB_PATH).exists():
    init_db(DB_PATH)

if "db_stats" not in st.session_state:
    try:
        st.session_state["db_stats"] = get_database_stats(DB_PATH)
    except Exception:
        st.session_state["db_stats"] = {"customers": 30, "products": 25, "orders": 75, "order_items": 180}


# ==============================================================================
# Sidebar Configuration & Model Selector
# ==============================================================================

with st.sidebar:
    st.markdown("## ⚡ System Configuration")
    st.caption("Version 1.0")

    st.markdown("### 🤖 Cloud LLM Backend")

    # Supported and recommended OpenRouter models
    MODEL_OPTIONS = [
        "meta-llama/llama-3.1-70b-instruct",
        "meta-llama/llama-3.3-70b-instruct",
        "qwen/qwen-2.5-coder-32b-instruct",
        "meta-llama/llama-3.1-8b-instruct:free",
        "Custom Model..."
    ]

    selected_option = st.selectbox(
        "OpenRouter Model:",
        options=MODEL_OPTIONS,
        index=0,
        help="Select a high-accuracy LLM for natural language to SQL generation"
    )

    if selected_option == "Custom Model...":
        selected_model = st.text_input("Enter model identifier:", value="meta-llama/llama-3.1-70b-instruct").strip()
    else:
        selected_model = selected_option

    env_key = os.environ.get("OPENROUTER_API_KEY", "")
    sidebar_key = st.text_input(
        "OpenRouter API Key:",
        value=env_key,
        type="password",
        placeholder="Enter your sk-or-v1-... key",
        help="OpenRouter API key used for live generation. Reads from .env by default."
    )
    api_key = sidebar_key.strip() if sidebar_key else env_key
    provider_key = "openrouter"

    st.markdown('<div class="sidebar-section"></div>', unsafe_allow_html=True)

    # Database Operations & Dynamic Live Status
    st.markdown("### 🗄️ Database Status")
    st.caption(f"📁 SQLite: `{DB_PATH}`")

    # Always fetch live stats dynamically from database
    stats = get_database_stats(DB_PATH)
    st.session_state["db_stats"] = stats

    for tbl_name, count in stats.items():
        st.text(f"• {tbl_name.capitalize()}: {count} rows")

    # Database Reset Button to easily restore clean state after testing write queries
    if st.button("🔄 Reset Database to Default", use_container_width=True, help="Wipes modifications and resets back to 30 customers, 25 products, 75 orders, 180 items"):
        with st.spinner("Resetting and re-seeding database..."):
            reset_database(DB_PATH)
            st.session_state["db_stats"] = get_database_stats(DB_PATH)
            st.session_state["last_query_result"] = None
            st.success("Database restored to default!")
            st.rerun()

    # Quick Table Inspector Dropdown
    if stats:
        with st.expander("🔍 Inspect Database Tables", expanded=False):
            selected_table = st.selectbox("Select table to preview:", options=list(stats.keys()), key="sidebar_table_inspect")
            if selected_table:
                try:
                    import pandas as pd

                    from src.database import execute_readonly_query
                    cols, rows = execute_readonly_query(f"SELECT * FROM `{selected_table}` LIMIT 10;", DB_PATH)
                    if rows:
                        df_preview = pd.DataFrame(rows, columns=cols)
                        st.dataframe(df_preview, use_container_width=True, hide_index=True)
                    else:
                        st.info("Table is empty.")
                except Exception as e:
                    st.caption(f"Could not preview table: {e}")


# ==============================================================================
# TextToSQLEngine Management
# ==============================================================================

# Maintain singleton TextToSQLEngine in session state
if "sql_engine" not in st.session_state:
    st.session_state["sql_engine"] = TextToSQLEngine(
        db_path=DB_PATH,
        provider=provider_key,
        api_key=api_key,
        model=selected_model
    )
else:
    engine = st.session_state["sql_engine"]
    if engine.provider_type != provider_key or engine.api_key != api_key or engine.model != selected_model:
        engine.set_provider(provider_type=provider_key, api_key=api_key, model=selected_model)

engine = st.session_state["sql_engine"]


# ==============================================================================
# Main Page Header & Multi-Tab Layout
# ==============================================================================

st.markdown("# ⚡ Text-to-SQL Generator (CRUD & Guardrails)")
st.markdown(
    "Translate natural language queries into safe, dialect-precise SQLite statements with "
    "**3-Layer Defense-in-Depth Security** and **Human-in-the-Loop Write Approval**."
)
st.markdown("<br>", unsafe_allow_html=True)

tab_query, tab_schema, tab_arch = st.tabs([
    "💬 Live Query & CRUD",
    "🗄️ Schema & ERD Explorer",
    "🏛️ Architecture & Security"
])

with tab_query:
    render_live_query_tab(engine=engine, db_path=DB_PATH)

with tab_schema:
    render_schema_explorer_tab(db_path=DB_PATH)

with tab_arch:
    render_architecture_tab()
