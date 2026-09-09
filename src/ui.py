"""
Streamlit UI Components for Text-to-SQL Generator.
Provides:
  - Live natural language query input with quick-demo sample buttons.
  - SQL code viewer, safety guardrail feedback, and human-in-the-loop write approvals.
  - Interactive dataframe display with CSV download.
  - Schema & ERD Explorer tab using structured database introspection.
  - Architecture & 3-Layer Security Guardrail documentation tab.
"""

import streamlit as st

from src.engine import QueryResult, TextToSQLEngine
from src.schema import get_erd_data


def _clear_input():
    st.session_state["nl_prompt_textarea"] = ""
    st.session_state["last_query_result"] = None


def render_live_query_tab(engine: TextToSQLEngine, db_path: str) -> None:
    st.markdown("### 💬 Ask your database a question")
    st.caption("Ask in plain English. Read queries execute immediately in read-only isolation; write operations require your approval.")

    # Quick demo query buttons for quick presentation during jury evaluation
    st.markdown("##### 💡 Quick Demo Queries (Click to load)")
    q_col1, q_col2, q_col3, q_col4 = st.columns(4)
    with q_col1:
        if st.button("🏆 Top 5 Customers (JOIN)", use_container_width=True):
            st.session_state["nl_prompt_textarea"] = "What are the top 5 customers by total spending?"
            st.rerun()
    with q_col2:
        if st.button("💳 Revenue by Payment", use_container_width=True):
            st.session_state["nl_prompt_textarea"] = "Calculate the total revenue and number of orders for each payment method for delivered orders."
            st.rerun()
    with q_col3:
        if st.button("⚡ Electronics < $100", use_container_width=True):
            st.session_state["nl_prompt_textarea"] = "List all products in the 'Electronics' category with price under 100 sorted by price."
            st.rerun()
    with q_col4:
        if st.button("✍️ Add Product (CRUD)", use_container_width=True):
            st.session_state["nl_prompt_textarea"] = "Add a new product called 'Wireless Earbuds' in 'Electronics' with price 89.99, cost 40.00, stock 50, rating 4.6, is_active 1."
            st.rerun()

    user_prompt = st.text_area(
        "Natural-language request:",
        height=95,
        placeholder="e.g., What are the top 5 customers by total spending?",
        key="nl_prompt_textarea"
    )

    col_btn1, col_btn2, _ = st.columns([2, 2, 4])
    with col_btn1:
        run_clicked = st.button("🚀 Generate & Execute", type="primary", use_container_width=True)
    with col_btn2:
        st.button("🧹 Clear", on_click=_clear_input, use_container_width=True)

    if run_clicked and user_prompt.strip():
        with st.spinner("Translating natural language to SQL & verifying safety..."):
            st.session_state["last_query_result"] = engine.execute_query(user_prompt.strip())

    if st.session_state.get("last_query_result") is not None:
        _display_query_result(st.session_state["last_query_result"])


def _display_query_result(result: QueryResult) -> None:
    st.markdown("---")

    # Query Header Metrics
    m_col1, m_col2, m_col3 = st.columns([4, 2, 2])
    with m_col1:
        st.markdown("##### ⚡ Generated SQL Statement")
    with m_col2:
        st.caption(f"⏱️ **Latency:** `{result.execution_time_ms:.1f} ms`")
    with m_col3:
        status_badge = "🛡️ Safe (RO)" if result.is_safe else "⚠️ Flagged"
        st.caption(f"Status: **{status_badge}**")

    st.code(result.generated_sql or "-- [No SQL Generated]", language="sql")

    if not result.is_safe:
        st.error(f"❌ Operation Blocked by Security Guardrail: {result.guardrail_error}")
        return

    if result.error:
        if result.error.startswith("⚠️"):
            st.warning(result.error)
        else:
            st.error(f"Execution Error: {result.error}")
        return

    # Write Operation Human-in-the-Loop Confirmation
    if getattr(result, "needs_approval", False):
        st.warning("⚠️ **Write / DDL Mutation Detected!**")
        st.info(
            "This query will modify data or schema in the database (INSERT, UPDATE, DELETE, or DDL). "
            "Review the generated SQL statement above, then click **Approve & Execute** below to commit changes."
        )

        col_app1, col_app2 = st.columns([2, 5])
        with col_app1:
            if st.button("✅ Approve & Execute", type="primary", use_container_width=True):
                with st.spinner("Executing approved write transaction..."):
                    engine = st.session_state["sql_engine"]
                    approved_result = engine.execute_approved_query(result.generated_sql)
                    st.session_state["last_query_result"] = approved_result
                    st.rerun()
        return

    st.markdown("##### 📊 Query Results")

    # Handle write operation execution confirmation
    if hasattr(result, "row_count") and result.row_count is not None and not result.columns:
        st.success(f"✅ Write operation executed successfully. {result.row_count} row(s) affected.")
        return

    if result.dataframe is not None and not result.dataframe.empty:
        st.dataframe(result.dataframe, use_container_width=True, hide_index=True)
        csv_data = result.dataframe.to_csv(index=False)
        st.download_button(
            label="📥 Download CSV",
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
    st.markdown("### 🗄️ Database Schema & Relational Structure")
    st.caption("Inspect the 4 relational tables, column data types, foreign keys, and key business calculations.")

    erd_data = get_erd_data()
    tables = erd_data["tables"]
    relationships = erd_data["relationships"]

    # Table metadata cards
    table_tabs = st.tabs([f"📁 {t.capitalize()}" for t in tables])
    for idx, (tbl_name, tbl_info) in enumerate(tables.items()):
        with table_tabs[idx]:
            st.markdown(f"**Description:** {tbl_info['description']}")
            st.markdown(f"**Primary Key:** `{tbl_info['primary_key']}`")

            if tbl_info["foreign_keys"]:
                fks = [f"`{fk['column']}` → `{fk['references_table']}.{fk['references_column']}`" for fk in tbl_info["foreign_keys"]]
                st.markdown(f"**Foreign Keys:** {', '.join(fks)}")

            col_data = [
                {"Column": c["name"], "Data Type": c["type"], "Description": c["description"]}
                for c in tbl_info["columns"]
            ]
            st.dataframe(col_data, use_container_width=True, hide_index=True)

    # Relationships section
    st.markdown("---")
    st.markdown("##### 🔗 Relational Graph Relationships")
    for rel in relationships:
        st.markdown(
            f"• **{rel['from_table']}** (`{rel['from_column']}`) ➔ **{rel['to_table']}** (`{rel['to_column']}`) "
            f"— *[{rel['type']}]*: {rel['description']}"
        )


def render_architecture_tab() -> None:
    """Renders 3-layer architecture and defense-in-depth security overview."""
    st.markdown("### 🏛️ System Architecture & Defense-in-Depth Guardrails")
    st.caption("Version 1.0 Milestone for 7th Semester Generative AI Capstone Jury Evaluation.")

    col1, col2, col3 = st.columns(3)
    with col1:
        st.markdown("""
        #### 🛡️ Layer 1: Prompt Grounding
        - SQLite 3 dialect instruction
        - Embedded DDL & relationships
        - Multi-tier few-shot examples
        - Ambiguity & hallucination suppression
        """)
    with col2:
        st.markdown("""
        #### 🔍 Layer 2: AST Security Guardrail
        - Abstract Syntax Tree parsing via `sqlglot`
        - Stacked / chained statement rejection
        - Disallowed administrative command blocking (`ATTACH`, `PRAGMA`)
        - Read vs Write classification
        """)
    with col3:
        st.markdown("""
        #### 🔒 Layer 3: Engine C-Level Isolation
        - SQLite URI Read-Only mode (`mode=ro`)
        - `PRAGMA query_only = ON`
        - Runaway Cartesian product timeout guard
        - Strict Foreign Key checking on mutations
        """)

    st.markdown("---")
    st.markdown("""
    #### 🔄 Query Lifecycle
    1. **Natural Language Input**: User enters query in natural English or selects a quick demo chip.
    2. **Grounding & Generation**: Context (Schema DDL, Domain Rules, Dialect Guidelines) injected into prompt and sent to OpenRouter LLM (`meta-llama/llama-3.1-70b-instruct`).
    3. **SQL Extraction & Normalization**: Multi-pass regex strips markdown fences, comments, backticks, and applies `sqlglot` transpilation.
    4. **AST Validation (Layer 2)**: Query parsed into AST. Stacked queries and administrative commands are immediately rejected.
    5. **Security Gate**: Read queries (`SELECT`, `WITH`) execute on read-only SQLite (`mode=ro`). Write queries (`INSERT`, `UPDATE`, `DELETE`) require human approval.
    6. **Result Presentation**: Streamlit displays SQL code, execution latency, interactive dataframe, and CSV export.
    """)
