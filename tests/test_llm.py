"""Tests for the OpenRouter client and the eval's exit codes, with a fake urlopen (no network)."""

import io
import json
import urllib.error
import urllib.request

import pytest

import scripts.eval as run_eval
from text_to_sql import llm
from text_to_sql.llm import RATE_LIMITED, OpenRouterProvider


def http_error(code, body=b"{}"):
    return urllib.error.HTTPError(OpenRouterProvider.ENDPOINT, code, "error", {}, io.BytesIO(body))


@pytest.fixture
def no_sleep(monkeypatch):
    monkeypatch.setattr(llm.time, "sleep", lambda s: None)


def fake_urlopen(monkeypatch, *responses):
    """Each response is an HTTPError to raise or a dict to return as the JSON body."""
    calls = []
    replies = list(responses)

    def urlopen(req, timeout=None):
        calls.append(json.loads(req.data))
        reply = replies.pop(0) if len(replies) > 1 else replies[0]
        if isinstance(reply, Exception):
            raise reply
        return io.BytesIO(json.dumps(reply).encode())

    monkeypatch.setattr(urllib.request, "urlopen", urlopen)
    return calls


def test_eval_exits_2_without_a_key(monkeypatch):
    monkeypatch.setattr(run_eval, "load_dotenv", lambda *a, **k: None)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    with pytest.raises(SystemExit) as exit_info:
        run_eval.main()
    assert exit_info.value.code == 2


def test_eval_exits_3_when_the_quota_is_used_up(monkeypatch, tmp_path, no_sleep, capsys):
    monkeypatch.setattr(run_eval, "load_dotenv", lambda *a, **k: None)
    monkeypatch.setattr(run_eval.tempfile, "mkdtemp", lambda: str(tmp_path))
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    calls = fake_urlopen(monkeypatch, http_error(429))

    with pytest.raises(SystemExit) as exit_info:
        run_eval.main()

    assert exit_info.value.code == 3
    assert len(calls) == 3  # first try plus two backoff retries, then it stops
    assert "Stopped at question 1" in capsys.readouterr().err


def ask(monkeypatch, *responses):
    calls = fake_urlopen(monkeypatch, *responses)
    result = OpenRouterProvider(api_key="test-key").generate_sql("question", schema_info="schema")
    return result, calls


def reply(content, finish_reason="stop"):
    return {"choices": [{"finish_reason": finish_reason, "message": {"content": content}}]}


def test_good_reply_returns_the_sql(monkeypatch):
    result, calls = ask(monkeypatch, reply("```sql\nSELECT COUNT(*) FROM orders;\n```"))
    assert result.success and not result.refused
    assert result.sql == "SELECT COUNT(*) FROM orders;"
    assert calls[0]["messages"][0]["role"] == "system"
    assert "schema" in calls[0]["messages"][0]["content"]


def test_401_says_the_key_was_rejected(monkeypatch):
    result, calls = ask(monkeypatch, http_error(401))
    assert not result.success
    assert result.error == "OpenRouter rejected the API key. Please check that your key is valid."
    assert len(calls) == 1


def test_429_is_retried_then_reported(monkeypatch, no_sleep):
    result, calls = ask(monkeypatch, http_error(429))
    assert not result.success
    assert result.error == RATE_LIMITED
    assert len(calls) == 3


def test_429_then_success(monkeypatch, no_sleep):
    result, calls = ask(monkeypatch, http_error(429), reply("SELECT 1"))
    assert result.success and result.sql == "SELECT 1"
    assert len(calls) == 2


def test_error_inside_a_200_body(monkeypatch):
    result, _ = ask(monkeypatch, {"error": {"message": "Provider returned error", "code": 502}})
    assert not result.success
    assert result.error == "OpenRouter error: Provider returned error"


def test_plain_string_error_inside_a_200_body(monkeypatch):
    result, _ = ask(monkeypatch, {"error": "Model is overloaded"})
    assert not result.success
    assert result.error == "OpenRouter error: Model is overloaded"


def test_read_timeout(monkeypatch):
    result, _ = ask(monkeypatch, TimeoutError("timed out"))
    assert not result.success
    assert result.error == "OpenRouter did not answer within 60 s."


def test_truncated_reply(monkeypatch):
    result, _ = ask(monkeypatch, reply("SELECT customer_id, first", finish_reason="length"))
    assert not result.success
    assert result.error == "The model response was truncated (token limit reached)."


def test_network_error(monkeypatch):
    result, _ = ask(monkeypatch, urllib.error.URLError("no route to host"))
    assert not result.success
    assert result.error == "Could not reach OpenRouter: no route to host"


def test_whole_reply_refusal_is_a_refusal(monkeypatch):
    result, _ = ask(monkeypatch, reply("-- REFUSE: read-only"))
    assert result.refused and result.success
    assert result.sql == "-- REFUSE: read-only"


def test_refusal_text_in_a_query_comment_is_not_a_refusal(monkeypatch):
    result, _ = ask(monkeypatch, reply("```sql\nSELECT 1 -- REFUSE: read-only\n```"))
    assert not result.refused
    assert result.sql == "SELECT 1 -- REFUSE: read-only"


def test_no_key_means_no_request(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    calls = fake_urlopen(monkeypatch, reply("SELECT 1"))
    result = OpenRouterProvider(api_key="").generate_sql("question", schema_info="schema")
    assert not result.success
    assert "No OpenRouter API key" in result.error
    assert calls == []
