"""Calls OpenRouter to turn a question into SQL, and pulls the SQL back out of the reply.

Models wrap SQL in markdown fences, add a sentence of explanation, or quote identifiers
in backticks, so the response needs unwrapping before anything else can use it.
"""

import json
import os
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any

from src.prompt import get_sqlite_prompt


@dataclass
class GenerationResult:
    sql: str
    raw_response: str
    provider: str
    model: str
    latency_ms: float
    success: bool
    error: str | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


class SQLExtractor:
    """Pulls SQL out of a model reply and normalises it to SQLite."""

    FENCE_PATTERN = re.compile(r"```(?:sql|SQL)?\s*([\s\S]*?)\s*```", re.MULTILINE)

    # Matches a bare statement when the model didn't use a fence: a leading keyword,
    # then everything up to a semicolon or the end of the reply.
    RAW_SQL_PATTERN = re.compile(
        r"(?is)\b([A-Z]+\s+[\s\S]+?)(?:;\s*$|;\s*\n|\Z)"
    )

    @classmethod
    def clean_sql(cls, sql: str) -> str:
        if not sql:
            return ""
        cleaned = sql.strip()
        if cleaned.startswith("```"):
            cleaned = re.sub(r"^```(?:sql|SQL)?\s*", "", cleaned)
            cleaned = re.sub(r"\s*```$", "", cleaned)
        cleaned = re.sub(r"`([a-zA-Z0-9_]+)`", r"\1", cleaned)
        cleaned = re.sub(r";+\s*$", "", cleaned).strip()

        try:
            import sqlglot
            transpiled = sqlglot.transpile(cleaned, read="sqlite", write="sqlite", pretty=True)
            if transpiled and len(transpiled) == 1:
                return transpiled[0].strip()
        except Exception:
            # An unparseable string still goes to the guardrails, which reject it properly.
            pass

        return cleaned.strip()

    @classmethod
    def extract_sql(cls, text: str | None) -> str:
        if not text or not str(text).strip():
            return ""

        raw = str(text).strip()

        fence_matches = cls.FENCE_PATTERN.findall(raw)
        if fence_matches:
            # The last block, since a model that shows its working puts the answer last.
            return cls.clean_sql(fence_matches[-1])

        raw_match = cls.RAW_SQL_PATTERN.search(raw)
        if raw_match:
            return cls.clean_sql(raw_match.group(1))

        return cls.clean_sql(raw)


class OpenRouterProvider:
    """OpenRouter chat completions over urllib, so there's no HTTP dependency to install."""

    ENDPOINT = "https://openrouter.ai/api/v1/chat/completions"
    # Free on OpenRouter. If OpenRouter retires it, this is the one line to change.
    DEFAULT_MODEL = "nvidia/nemotron-3-super-120b-a12b:free"

    def __init__(
        self,
        api_key: str | None = None,
        model: str = DEFAULT_MODEL,
        temperature: float = 0.0,
        timeout: float = 60.0  # free models can take 15+ seconds
    ):
        self.api_key = api_key or os.environ.get("OPENROUTER_API_KEY")
        self.model = model
        self.temperature = temperature
        self.timeout = timeout

    def is_available(self) -> bool:
        return bool(self.api_key and str(self.api_key).strip())

    def _failed(self, start_time: float, error: str, raw_response: str = "") -> GenerationResult:
        return GenerationResult(
            sql="",
            raw_response=raw_response,
            provider="openrouter",
            model=self.model,
            latency_ms=(time.perf_counter() - start_time) * 1000.0,
            success=False,
            error=error,
        )

    def generate_sql(self, prompt: str, schema_info: str = "", **kwargs) -> GenerationResult:
        """Ask the model for SQL. Network and API errors come back as a failed result,
        never as an exception, because the caller renders the error in the UI."""
        start_time = time.perf_counter()

        if not self.is_available():
            return self._failed(
                start_time,
                "No OpenRouter API key. Add OPENROUTER_API_KEY to .env or enter one in the sidebar."
            )

        system_prompt, user_prompt = get_sqlite_prompt(prompt, schema_info)
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            "temperature": self.temperature,
            "max_tokens": 1000,
            # Thinking is slow and can use up max_tokens before any SQL is written.
            "reasoning": {"enabled": False},
        }

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://github.com/Krish3101/text-to-sql",
            "X-Title": "Text-to-SQL",
        }

        req = urllib.request.Request(
            self.ENDPOINT,
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST",
        )

        for attempt in range(3):
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    data = json.loads(resp.read().decode("utf-8"))

                    raw_content = ""
                    if data.get("choices"):
                        raw_content = data["choices"][0]["message"].get("content", "")

                    usage = data.get("usage", {})
                    return GenerationResult(
                        sql=SQLExtractor.extract_sql(raw_content),
                        raw_response=raw_content,
                        provider="openrouter",
                        model=self.model,
                        latency_ms=(time.perf_counter() - start_time) * 1000.0,
                        success=True,
                        prompt_tokens=usage.get("prompt_tokens"),
                        completion_tokens=usage.get("completion_tokens"),
                        metadata={"response_id": data.get("id")}
                    )

            except urllib.error.HTTPError as e:
                # Free models share a pool that OpenRouter throttles for a few seconds at a time.
                if e.code == 429 and attempt < 2:
                    time.sleep(5 * (attempt + 1))
                    continue
                try:
                    err_body = e.read().decode("utf-8")
                except Exception:
                    err_body = ""
                return self._failed(start_time, f"OpenRouter returned HTTP {e.code}: {e.reason}. {err_body}", err_body)
            except urllib.error.URLError as e:
                return self._failed(start_time, f"Could not reach OpenRouter: {e.reason!s}")
            except Exception as e:
                return self._failed(start_time, f"Unexpected error calling OpenRouter: {e!s}")
