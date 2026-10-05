"""Streamlit UI components for Text-to-SQL."""

from pathlib import Path

import streamlit as st

from text_to_sql.config import MAX_ROWS
from text_to_sql.database import get_database_stats
from text_to_sql.engine import QueryResult, TextToSQLEngine
from text_to_sql.guardrails import validate_sql
from text_to_sql.schema import describe_tables

EXAMPLES_JOINS = [
    {
        "label": "Top 5 customers by total spending",
        "prompt": "What are the top 5 customers by total spending?",
        "help": "2-table join between customers and orders with aggregation",
    },
    {
        "label": "Electronics buyers (4 tables)",
        "prompt": "Find the names and cities of all customers who have purchased at least one product from the 'Electronics' category, along with the product name and purchase date.",
        "help": "4-table join spanning customers, orders, order_items, and products",
    },
    {
        "label": "Customers who never placed an order",
        "prompt": "List the first and last names of customers who have never placed an order.",
        "help": "Anti-join identifying customers with zero orders",
    },
    {
        "label": "Best-selling product per category",
        "prompt": "For each product category, which product brought in the most revenue? Show the category, the product name and its revenue.",
        "help": "Join with a revenue calculation, then the top product inside each category",
    },
]

# With a key these ask the model; without one they fill "Check my own SQL" instead.
EXAMPLES_GUARDRAIL = [
    {
        "label": "Delete all orders",
        "prompt": "Delete all orders from the database.",
        "sql": "DELETE FROM orders",
        "help": "A destructive request: the guardrail must stop it",
    },
    {
        "label": "Drop the customers table",
        "prompt": "Drop the customers table completely.",
        "sql": "DROP TABLE customers",
        "help": "A destructive request: the guardrail must stop it",
    },
]


def _fill(key: str, value: str) -> None:
    # Runs as a button callback, before the widgets are drawn, so it may set their text.
    st.session_state[key] = value


def _clear_input():
    st.session_state["nl_prompt_textarea"] = ""
    st.session_state["last_query_result"] = None


def render_verdict_banner(allowed: bool, reason: str | None, executed: bool) -> None:
    """Shows the guardrail verdict and which checks ran."""
    if allowed:
        st.success("Allowed: read-only query")
        where = (
            "ran on a read-only connection" if executed else "would run on a read-only connection"
        )
        st.caption(f"✓ 1 statement  •  ✓ parsed as SELECT  •  ✓ no ATTACH/PRAGMA  •  ✓ {where}")
    else:
        st.error(f"Rejected by guardrails: {reason}")
        st.caption("Nothing was executed.")


def render_live_query_tab(engine: TextToSQLEngine, has_key: bool) -> None:
    # Without a key the SQL checker is the main thing you can try, so it goes first.
    if not has_key:
        _render_check_my_sql(expanded=True)

    st.subheader("Examples")

    st.caption("Joins & Aggregations:")
    cols_joins = st.columns(len(EXAMPLES_JOINS))
    for idx, ex in enumerate(EXAMPLES_JOINS):
        with cols_joins[idx]:
            st.button(
                ex["label"],
                help=ex["help"],
                width="stretch",
                on_click=_fill,
                args=("nl_prompt_textarea", ex["prompt"]),
            )

    st.caption("Guardrail Probes (destructive requests):")
    cols_guard = st.columns(len(EXAMPLES_GUARDRAIL))
    for idx, ex in enumerate(EXAMPLES_GUARDRAIL):
        with cols_guard[idx]:
            target = (
                ("nl_prompt_textarea", ex["prompt"]) if has_key else ("custom_sql_input", ex["sql"])
            )
            st.button(
                ex["label"],
                help=ex["help"],
                width="stretch",
                on_click=_fill,
                args=target,
            )

    user_prompt = st.text_area(
        "Natural-language question:",
        height=85,
        placeholder="e.g. What are the top 5 customers by total spending?",
        key="nl_prompt_textarea",
    )

    col_btn1, col_btn2, _ = st.columns([2, 2, 6])
    with col_btn1:
        run_clicked = st.button(
            "Generate and run",
            type="primary",
            width="stretch",
            disabled=not has_key,
        )
    with col_btn2:
        st.button("Clear", on_click=_clear_input, width="stretch")

    if run_clicked and user_prompt.strip():
        with st.spinner("Asking the model for SQL and checking it. This can take about 20 s..."):
            st.session_state["last_query_result"] = engine.execute_query(user_prompt.strip())

    if st.session_state.get("last_query_result") is not None:
        _display_query_result(st.session_state["last_query_result"])

    if has_key:
        st.markdown("---")
        _render_check_my_sql(expanded=False)


def _display_query_result(result: QueryResult) -> None:
    st.markdown("---")

    col_head, col_time = st.columns([6, 2])
    with col_head:
        st.subheader("Generated SQL")
    with col_time:
        st.caption(f"{result.execution_time_ms:.1f} ms")

    st.code(result.generated_sql or "-- no SQL generated", language="sql")

    if result.refused:
        st.warning("Refused: The request asks to change data. Only read-only SELECT queries run.")
        return

    # No verdict means there was no SQL to check (API error or an empty reply).
    if result.verdict is None:
        st.error(result.error)
        return

    render_verdict_banner(result.verdict.allowed, result.verdict.reason, executed=True)
    if not result.verdict.allowed:
        return

    if result.error:
        st.error(result.error)
        return

    st.subheader("Results")

    if result.dataframe is not None and not result.dataframe.empty:
        st.dataframe(result.dataframe, width="stretch", hide_index=True)
        if result.truncated:
            st.info(
                f"Showing the first {result.row_count:,} rows (results are capped at {MAX_ROWS:,})."
            )
        else:
            st.caption(f"{result.row_count} row(s) returned.")
    elif result.columns and len(result.rows) == 0:
        st.info("Query executed successfully, but returned 0 matching records.")
    else:
        st.info("No records returned.")


def _render_check_my_sql(expanded: bool) -> None:
    """Checks typed SQL against the AST guardrail only. No model, nothing is executed."""
    with st.expander("Check my own SQL (test guardrail without LLM)", expanded=expanded):
        st.caption("Test any custom SQL against the AST allowlist. No API key or model needed.")
        custom_sql = st.text_area(
            "SQL query to validate:",
            height=70,
            placeholder="e.g. DROP TABLE customers; or SELECT * FROM orders; -- note",
            key="custom_sql_input",
        )
        if st.button("Check SQL", type="secondary"):
            if custom_sql.strip():
                verdict = validate_sql(custom_sql.strip())
                render_verdict_banner(verdict.allowed, verdict.reason, executed=False)
            else:
                st.warning("Please enter a SQL statement to check.")


def render_schema_explorer_tab(db_path: Path | str) -> None:
    st.subheader("Database Schema")
    st.caption("Read from the database itself (PRAGMA table_info and foreign_key_list).")

    try:
        stats = get_database_stats(db_path)
    except Exception:
        stats = {}

    tables = describe_tables(db_path)
    table_tabs = st.tabs([f"{t} ({stats.get(t, '?')} rows)" for t in tables])

    for tab, (table, info) in zip(table_tabs, tables.items()):
        with tab:
            st.dataframe(info["columns"], width="stretch", hide_index=True)
            for fk in info["foreign_keys"]:
                st.markdown(f"`{table}.{fk['column']}` → `{fk['table']}.{fk['references']}`")
