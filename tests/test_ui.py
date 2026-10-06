"""Streamlit page tests with AppTest and a scripted model."""

from pathlib import Path

import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

from tests.test_engine import ScriptedProvider
from text_to_sql.engine import TextToSQLEngine

APP = str(Path(__file__).resolve().parent.parent / "app.py")


@pytest.fixture
def app(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.setattr("text_to_sql.config.DEFAULT_DB_PATH", tmp_path / "ui_test.db")
    st.cache_resource.clear()  # ensure_database is cached per process
    at = AppTest.from_file(APP, default_timeout=30)
    at.run()
    return at


def _ask(at, *replies):
    from text_to_sql import config

    engine = TextToSQLEngine(db_path=config.DEFAULT_DB_PATH, api_key="test-key")
    engine.provider = ScriptedProvider(*replies)
    engine.provider.api_key = "test-key"
    at.session_state["sql_engine"] = engine
    at.text_area(key="nl_prompt_textarea").set_value("some question")
    [b for b in at.button if b.label == "Generate and run"][0].click()
    at.run()


def test_join_with_duplicate_columns_renders(app):
    _ask(app, "SELECT * FROM customers c JOIN orders o ON o.customer_id = c.customer_id")
    assert not app.exception
    assert len(app.dataframe) >= 1
    assert "customer_id_2" in app.dataframe[0].value.columns


def test_empty_question_shows_warning(app):
    [b for b in app.button if b.label == "Generate and run"][0].click()
    app.run()
    assert any("enter a question" in w.value.lower() for w in app.warning)
