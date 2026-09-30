"""The three Streamlit tabs: asking a question, browsing the schema, and how it works."""

import streamlit as st

from src.engine import QueryResult, TextToSQLEngine
from src.schema import get_erd_data


def _clear_input():
    st.session_state["nl_prompt_textarea"] = ""
    st.session_state["last_query_result"] = None


def render_live_query_tab(engine: TextToSQLEngine, db_path: str) -> None:
    st.markdown("### Ask your database a question")
    st.caption(
        "Ask in plain English. Read queries execute immediately in read-only isolation; write operations require your approval."
    )

    # Quick demo query buttons for one-click testing
    st.markdown("##### Examples")
    q_col1, q_col2, q_col3, q_col4 = st.columns(4)
    with q_col1:
        if st.button("Top 5 customers", width="stretch"):
            st.session_state["nl_prompt_textarea"] = (
                "What are the top 5 customers by total spending?"
            )
            st.rerun()
    with q_col2:
        if st.button("Revenue by payment", width="stretch"):
            st.session_state["nl_prompt_textarea"] = (
                "Calculate the total revenue and number of orders for each payment method for delivered orders."
            )
            st.rerun()
    with q_col3:
        if st.button("Electronics under $100", width="stretch"):
            st.session_state["nl_prompt_textarea"] = (
                "List all products in the 'Electronics' category with price under 100 sorted by price."
            )
            st.rerun()
    with q_col4:
        if st.button("Add a product", width="stretch"):
            st.session_state["nl_prompt_textarea"] = (
                "Add a new product called 'Wireless Earbuds' in 'Electronics' with price 89.99, cost 40.00, stock 50, rating 4.6, is_active 1."
            )
            st.rerun()

    user_prompt = st.text_area(
        "Natural-language request:",
        height=95,
        placeholder="e.g., What are the top 5 customers by total spending?",
        key="nl_prompt_textarea",
    )

    col_btn1, col_btn2, _ = st.columns([2, 2, 4])
    with col_btn1:
        run_clicked = st.button("Generate and run", type="primary", width="stretch")
    with col_btn2:
        st.button("Clear", on_click=_clear_input, width="stretch")

    if run_clicked and user_prompt.strip():
        with st.spinner("Translating natural language to SQL & verifying safety..."):
            st.session_state["last_query_result"] = engine.execute_query(user_prompt.strip())

    if st.session_state.get("last_query_result") is not None:
        _display_query_result(st.session_state["last_query_result"])


def _display_query_result(result: QueryResult) -> None:
    st.markdown("---")

    m_col1, m_col2, m_col3 = st.columns([4, 2, 2])
    with m_col1:
        st.markdown("##### Generated SQL")
    with m_col2:
        st.caption(f"{result.execution_time_ms:.1f} ms")
    with m_col3:
        if not result.is_safe:
            status = "blocked"
        elif result.needs_approval:
            status = "write, needs approval"
        elif result.wrote:
            status = "write, approved"
        else:
            status = "read-only"
        st.caption(f"Status: **{status}**")

    st.code(result.generated_sql or "-- no SQL generated", language="sql")

    if not result.is_safe:
        st.error(f"Blocked by the guardrails: {result.guardrail_error}")
        return

    if result.error:
        engine = st.session_state.get("sql_engine")
        if engine is not None and not engine.provider.is_available():
            st.warning(result.error)
        else:
            st.error(f"Execution error: {result.error}")
        return

    if result.needs_approval:
        st.warning("This query writes to the database.")
        st.info("Read the SQL above before approving it. Nothing runs until you do.")

        col_app1, _ = st.columns([2, 5])
        with col_app1:
            if st.button("Approve and run", type="primary", width="stretch"):
                with st.spinner("Executing approved write transaction..."):
                    engine = st.session_state["sql_engine"]
                    approved_result = engine.execute_approved_query(result.generated_sql)
                    st.session_state["last_query_result"] = approved_result
                    st.rerun()
        return

    st.markdown("##### Results")

    if result.wrote and not result.columns:
        st.success(f"Done. {result.row_count} row(s) affected.")
        return

    if result.dataframe is not None and not result.dataframe.empty:
        st.dataframe(result.dataframe, width="stretch", hide_index=True)
        csv_data = result.dataframe.to_csv(index=False)
        st.download_button(
            label="Download CSV",
            data=csv_data,
            file_name="query_results.csv",
            mime="text/csv",
        )
    elif result.columns and len(result.rows) == 0:
        st.info("Query executed successfully, but returned 0 matching records.")
    else:
        st.info("No records returned.")


def render_schema_explorer_tab(db_path: str) -> None:
    """Renders interactive schema, ERD definitions, and table dictionaries."""
    st.markdown("### Schema")
    st.caption(
        "Inspect the 4 relational tables, column data types, foreign keys, and key business calculations."
    )

    erd_data = get_erd_data()
    tables = erd_data["tables"]
    relationships = erd_data["relationships"]

    # Table metadata cards
    table_tabs = st.tabs([f"{t.capitalize()}" for t in tables])
    for idx, (tbl_name, tbl_info) in enumerate(tables.items()):
        with table_tabs[idx]:
            st.markdown(f"**Description:** {tbl_info['description']}")
            st.markdown(f"**Primary Key:** `{tbl_info['primary_key']}`")

            if tbl_info["foreign_keys"]:
                fks = [
                    f"`{fk['column']}` → `{fk['references_table']}.{fk['references_column']}`"
                    for fk in tbl_info["foreign_keys"]
                ]
                st.markdown(f"**Foreign Keys:** {', '.join(fks)}")

            col_data = [
                {"Column": c["name"], "Data Type": c["type"], "Description": c["description"]}
                for c in tbl_info["columns"]
            ]
            st.dataframe(col_data, width="stretch", hide_index=True)

    # Relationships section
    st.markdown("---")
    st.markdown("##### Relationships")
    for rel in relationships:
        st.markdown(
            f"• **{rel['from_table']}** (`{rel['from_column']}`) → **{rel['to_table']}** (`{rel['to_column']}`) "
            f"— *[{rel['type']}]*: {rel['description']}"
        )


def render_architecture_tab() -> None:
    """How a question becomes a result."""
    st.markdown("### How it works")

    st.markdown("""
    The model writes the SQL, but it doesn't decide whether the SQL runs.

    1. Your question goes to OpenRouter along with the database schema and a few
       worked examples, so the model knows what the tables and columns are called.
    2. The reply comes back as prose around a code fence, so the SQL is pulled out
       and normalised to SQLite with `sqlglot`.
    3. That SQL is parsed into a syntax tree. Anything with more than one statement
       is rejected, as are `ATTACH`, `DETACH` and `PRAGMA writable_schema`. Parsing
       it beats scanning for banned words, which is easy to slip past.
    4. Reads run on a connection opened with `mode=ro` and `PRAGMA query_only`, so
       SQLite refuses a write itself even if one got this far.
    5. Writes are shown to you first and only run once you approve them.

    If the query has a syntax error, the error is sent back to the model with the
    original question attached. A model told what it got wrong usually fixes a
    mistyped column on the next try.
    """)
