"""
OpenRouter Cloud LLM Provider & Zero-Dependency SQL Extraction Module.

Implements:
  - BaseLLMProvider: Abstract base class for Text-to-SQL generation.
  - GenerationResult: Dataclass capturing generated SQL, token metrics, and execution metadata.
  - SQLExtractor: Multi-pass regex cleaner and AST normalizer for LLM-generated SQL.
  - OpenRouterProvider: Production Cloud LLM provider via standard library urllib.request.
  - FallbackOrchestrator: Orchestrator managing provider invocation, input sanitization, and error reporting.
"""

import abc
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
    """Standardized response from any LLM or Mock provider."""
    sql: str
    raw_response: str
    provider: str
    model: str
    latency_ms: float
    success: bool
    error: str | None = None
    fallback_triggered: bool = False
    fallback_reason: str | None = None
    retry_count: int = 0
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


class SQLExtractor:
    """Robust multi-pass extractor and sanitizer for LLM-generated SQL."""

    # Regex 1: Markdown code fences with optional 'sql' or 'SQL' tag
    FENCE_PATTERN = re.compile(r"```(?:sql|SQL)?\s*([\s\S]*?)\s*```", re.MULTILINE)

    # Regex 2: Raw statement fallback (matches first word followed by space, e.g. SELECT, INSERT, CREATE, DROP)
    RAW_SQL_PATTERN = re.compile(
        r"(?is)\b([A-Z]+\s+[\s\S]+?)(?:;\s*$|;\s*\n|\Z)"
    )

    @classmethod
    def clean_sql(cls, sql: str) -> str:
        """Sanitizes and formats SQL using sqlglot for dialect-clean SQLite 3."""
        if not sql:
            return ""
        cleaned = sql.strip()
        # Remove markdown fences if present
        if cleaned.startswith("```"):
            cleaned = re.sub(r"^```(?:sql|SQL)?\s*", "", cleaned)
            cleaned = re.sub(r"\s*```$", "", cleaned)
        cleaned = re.sub(r"`([a-zA-Z0-9_]+)`", r"\1", cleaned)
        cleaned = re.sub(r";+\s*$", "", cleaned).strip()

        # Try formatting through sqlglot for dialect normalization
        try:
            import sqlglot
            transpiled = sqlglot.transpile(cleaned, read="sqlite", write="sqlite", pretty=True)
            if transpiled and len(transpiled) == 1:
                return transpiled[0].strip()
        except Exception:
            pass

        return cleaned.strip()

    @classmethod
    def extract_sql(cls, text: str | None) -> str:
        """Extracts clean raw SQL from model output."""
        if not text or not str(text).strip():
            return ""

        raw = str(text).strip()

        # Pass 1: Extract from markdown code fence
        fence_matches = cls.FENCE_PATTERN.findall(raw)
        if fence_matches:
            # We just take the last matched block, which is typical for standard generation
            return cls.clean_sql(fence_matches[-1])

        # Pass 2: Search for raw statement boundary
        raw_match = cls.RAW_SQL_PATTERN.search(raw)
        if raw_match:
            return cls.clean_sql(raw_match.group(1))

        # Pass 3: Fallback cleaning of entire string
        return cls.clean_sql(raw)


class BaseLLMProvider(abc.ABC):
    """Abstract Base Class for all Text-to-SQL generation backends."""

    def __init__(self, model: str = "default", temperature: float = 0.0, timeout: float = 15.0):
        self.model = model
        self.temperature = temperature
        self.timeout = timeout

    @abc.abstractmethod
    def generate_sql(self, prompt: str, schema_info: str = "", **kwargs) -> GenerationResult:
        """
        Generates SQL query from user prompt and schema context.
        Returns GenerationResult. Must not raise unhandled network exceptions.
        """

    @abc.abstractmethod
    def is_available(self) -> bool:
        """Checks if provider backend is reachable and ready."""


class OpenRouterProvider(BaseLLMProvider):
    """
    Cloud LLM Provider for OpenRouter.ai (and OpenAI-compatible endpoints)
    using Python standard library urllib.request for zero external dependencies.
    """

    ENDPOINT = "https://openrouter.ai/api/v1/chat/completions"

    def __init__(
        self,
        api_key: str | None = None,
        model: str = "meta-llama/llama-3.1-70b-instruct",
        temperature: float = 0.0,
        timeout: float = 20.0
    ):
        super().__init__(model=model, temperature=temperature, timeout=timeout)
        self.api_key = api_key or os.environ.get("OPENROUTER_API_KEY")

    def is_available(self) -> bool:
        return bool(self.api_key and str(self.api_key).strip())

    def generate_sql(self, prompt: str, schema_info: str = "", **kwargs) -> GenerationResult:
        start_time = time.perf_counter()

        if not self.is_available():
            elapsed = (time.perf_counter() - start_time) * 1000.0
            return GenerationResult(
                sql="",
                raw_response="",
                provider="openrouter",
                model=self.model,
                latency_ms=elapsed,
                success=False,
                error="OpenRouter API key is missing or empty."
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
        }

        req_data = json.dumps(payload).encode("utf-8")
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://github.com/Krish3101/text-to-sql",
            "X-Title": "Text-to-SQL Generator",
            "User-Agent": "TextToSQL/1.0"
        }

        req = urllib.request.Request(self.ENDPOINT, data=req_data, headers=headers, method="POST")

        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                resp_bytes = resp.read()
                data = json.loads(resp_bytes.decode("utf-8"))

                raw_content = ""
                if "choices" in data and len(data["choices"]) > 0:
                    raw_content = data["choices"][0]["message"].get("content", "")

                extracted_sql = SQLExtractor.extract_sql(raw_content)
                elapsed = (time.perf_counter() - start_time) * 1000.0

                usage = data.get("usage", {})
                prompt_tokens = usage.get("prompt_tokens")
                completion_tokens = usage.get("completion_tokens")

                return GenerationResult(
                    sql=extracted_sql,
                    raw_response=raw_content,
                    provider="openrouter",
                    model=self.model,
                    latency_ms=elapsed,
                    success=True,
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                    metadata={"response_id": data.get("id")}
                )

        except urllib.error.HTTPError as e:
            elapsed = (time.perf_counter() - start_time) * 1000.0
            err_body = ""
            try:
                err_body = e.read().decode("utf-8")
            except Exception:
                pass
            return GenerationResult(
                sql="",
                raw_response=err_body,
                provider="openrouter",
                model=self.model,
                latency_ms=elapsed,
                success=False,
                error=f"OpenRouter HTTP {e.code} Error: {e.reason}. {err_body}"
            )
        except urllib.error.URLError as e:
            elapsed = (time.perf_counter() - start_time) * 1000.0
            return GenerationResult(
                sql="",
                raw_response="",
                provider="openrouter",
                model=self.model,
                latency_ms=elapsed,
                success=False,
                error=f"OpenRouter Connection Error: {e.reason!s}"
            )
        except Exception as e:
            elapsed = (time.perf_counter() - start_time) * 1000.0
            return GenerationResult(
                sql="",
                raw_response="",
                provider="openrouter",
                model=self.model,
                latency_ms=elapsed,
                success=False,
                error=f"OpenRouter Unexpected Error: {e!s}"
            )





class FallbackOrchestrator:
    """
    Direct Cloud LLM Provider Orchestrator with structured error propagation.
    """

    def __init__(
        self,
        primary_provider: BaseLLMProvider | None = None
    ):
        self.primary_provider = primary_provider or OpenRouterProvider()

    def generate(self, prompt: str, schema_info: str = "", **kwargs) -> GenerationResult:
        if not self.primary_provider or not self.primary_provider.is_available():
            return GenerationResult(
                sql="",
                raw_response="",
                provider="openrouter",
                model=getattr(self.primary_provider, "model", "meta-llama/llama-3.1-70b-instruct"),
                latency_ms=0.0,
                success=False,
                error="⚠️ OpenRouter API Key is missing. Please enter your API key in the sidebar to generate SQL."
            )

        res = self.primary_provider.generate_sql(prompt, schema_info, **kwargs)
        if res.success and res.sql.strip():
            res.sql = SQLExtractor.clean_sql(res.sql)
        return res
