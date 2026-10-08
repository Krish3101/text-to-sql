"""The Streamlit page: a Query tab, a Schema tab, and "Check my own SQL"."""

import os

import pandas as pd
import streamlit as st
from dotenv import load_dotenv

from text_to_sql.config import DEFAULT_DB_PATH, MAX_ROWS, get_model
from text_to_sql.database import get_database_stats, init_db
from text_to_sql.engine import Answer, answer
from text_to_sql.guardrails import check_sql
from text_to_sql.llm import ask_model
from text_to_sql.schema import describe_tables

load_dotenv()

JOIN_EXAMPLES = [
    ("Top 5 customers by total spending", "What are the top 5 customers by total spending?"),
    (
        "Electronics buyers (4 tables)",
        "Find the names and cities of all customers who have purchased at least one product "
        "from the 'Electronics' category, along with the product name and purchase date.",
    ),
    (
        "Customers who never placed an order",
        "List the first and last names of customers who have never placed an order.",
    ),
    (
        "Best-selling product per category",
        "For each product category, which product brought in the most revenue? "
        "Show the category, the product name and its revenue.",
    ),
]

# With a key these ask the model; without one they fill "Check my own SQL" instead.
DESTRUCTIVE_EXAMPLES = [
    ("Delete all orders", "Delete all orders from the database.", "DELETE FROM orders"),
    ("Drop the customers table", "Drop the customers table completely.", "DROP TABLE customers"),
]


@st.cache_resource
def ensure_database() -> None:
    # Builds the DB on the first run, when the file is missing.
    init_db(DEFAULT_DB_PATH)


@st.cache_data
def get_cached_schema() -> tuple[dict[str, int], dict[str, dict]]:
    return get_database_stats(DEFAULT_DB_PATH), describe_tables(DEFAULT_DB_PATH)


def unique_names(names: list[str]) -> list[str]:
    """Renames repeats (customer_id, customer_id -> customer_id, customer_id_2); Arrow rejects duplicates."""
    taken = set(names)
    emitted: set[str] = set()
    result = []
    for name in names:
        if name in emitted:
            n = 2
            while f"{name}_{n}" in taken:
                n += 1
            name = f"{name}_{n}"
            taken.add(name)
        emitted.add(name)
        result.append(name)
    return result


def fill(key: str, value: str) -> None:
    # Runs as a button callback, before the widgets are drawn, so it may set their text.
    st.session_state[key] = value


def clear_question() -> None:
    st.session_state["question"] = ""
    st.session_state["last_answer"] = None


def show_verdict(allowed: bool, reason: str) -> None:
    if allowed:
        st.success("Allowed: read-only query")
    else:
        st.error(f"Rejected: {reason}")
        st.caption("Nothing was executed.")


def show_answer(result: Answer) -> None:
    st.markdown("---")
    st.subheader("Generated SQL")
    st.code(result.sql or "-- no SQL generated", language="sql")

    # No verdict means there was no SQL to check (API error or an empty reply).
    if result.allowed is None:
        st.error(result.error)
        return
    show_verdict(result.allowed, result.reason)
    if not result.allowed:
        return
    if result.error:
        st.error(result.error)
        return

    st.subheader("Results")
    if not result.rows:
        st.info("No rows returned.")
        return
    frame = pd.DataFrame(result.rows, columns=unique_names(result.columns))
    st.dataframe(frame, width="stretch", hide_index=True)
    if result.truncated:
        st.info(
            f"Showing the first {len(result.rows):,} rows (results are capped at {MAX_ROWS:,})."
        )
    else:
        st.caption(f"{len(result.rows)} row(s) returned.")


def check_my_sql(expanded: bool) -> None:
    """Checks typed SQL with the parser only. No model, nothing is executed."""
    with st.expander("Check my own SQL", expanded=expanded):
        st.caption("Runs the same parser check as the Query tab. No API key needed.")
        sql = st.text_area(
            "SQL to check:",
            height=70,
            placeholder="e.g. DROP TABLE customers",
            key="custom_sql_input",
        )
        if st.button("Check SQL", type="secondary"):
            if sql.strip():
                show_verdict(*check_sql(sql.strip()))
            else:
                st.warning("Please enter a SQL statement to check.")


def query_tab(has_key: bool) -> None:
    # Without a key the SQL checker is the main thing you can try, so it goes first.
    if not has_key:
        check_my_sql(expanded=True)

    st.subheader("Examples")
    for col, (label, question) in zip(st.columns(len(JOIN_EXAMPLES)), JOIN_EXAMPLES):
        col.button(label, width="stretch", on_click=fill, args=("question", question))
    for col, (label, question, sql) in zip(
        st.columns(len(DESTRUCTIVE_EXAMPLES)), DESTRUCTIVE_EXAMPLES
    ):
        target = ("question", question) if has_key else ("custom_sql_input", sql)
        col.button(label, width="stretch", on_click=fill, args=target)

    question = st.text_area(
        "Question:",
        height=85,
        placeholder="e.g. What are the top 5 customers by total spending?",
        key="question",
    )
    col_run, col_clear, _ = st.columns([2, 2, 6])
    run_clicked = col_run.button("Run", type="primary", width="stretch", disabled=not has_key)
    col_clear.button("Clear", on_click=clear_question, width="stretch")

    if run_clicked:
        if question.strip():
            with st.spinner("Asking the model for SQL and checking it..."):
                st.session_state["last_answer"] = answer(
                    question.strip(), ask=ask_model, db_path=DEFAULT_DB_PATH
                )
        else:
            st.warning("Please enter a question.")

    if st.session_state.get("last_answer") is not None:
        show_answer(st.session_state["last_answer"])

    if has_key:
        st.markdown("---")
        check_my_sql(expanded=False)


def schema_tab() -> None:
    stats, tables = get_cached_schema()
    for tab, (table, info) in zip(
        st.tabs([f"{t} ({stats[t]} rows)" for t in tables]), tables.items()
    ):
        with tab:
            st.dataframe(info["columns"], width="stretch", hide_index=True)
            for fk in info["foreign_keys"]:
                st.markdown(f"`{table}.{fk['column']}` → `{fk['table']}.{fk['references']}`")


st.set_page_config(page_title="Text-to-SQL", layout="wide", initial_sidebar_state="collapsed")
ensure_database()
has_key = bool(os.environ.get("OPENROUTER_API_KEY", "").strip())

st.title("Text-to-SQL")
st.write("Ask a question in English. Only read-only SELECT queries run.")
st.caption(f"Model: `{get_model()}`")
if not has_key:
    st.info(
        "Add `OPENROUTER_API_KEY` to `.env` to ask questions; "
        "the SQL checker below works without it."
    )

tab_query, tab_schema = st.tabs(["Query", "Schema"])
with tab_query:
    query_tab(has_key)
with tab_schema:
    schema_tab()
