"""OpenRouter LLM client for generating SQL from natural language."""

import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass

from text_to_sql.config import DEFAULT_MODEL
from text_to_sql.extract import REFUSAL, extract_sql, is_refusal
from text_to_sql.prompt import get_sqlite_prompt

# Shown when OpenRouter still answers 429 after the retries. The eval stops on it.
RATE_LIMITED = (
    "OpenRouter is rate-limiting this key (free models allow about 50 requests a day). "
    "Wait a minute and try again, or try tomorrow."
)


@dataclass
class GenerationResult:
    sql: str
    raw_response: str
    success: bool
    error: str | None = None
    refused: bool = False


class OpenRouterProvider:
    """Calls OpenRouter chat completions over urllib with rate-limit retries."""

    ENDPOINT = "https://openrouter.ai/api/v1/chat/completions"
    DEFAULT_MODEL = DEFAULT_MODEL

    def __init__(
        self,
        api_key: str | None = None,
        model: str = DEFAULT_MODEL,
        temperature: float = 0.0,
        timeout: float = 60.0,
    ):
        self.api_key = api_key or os.environ.get("OPENROUTER_API_KEY")
        self.model = model
        self.temperature = temperature
        self.timeout = timeout

    def is_available(self) -> bool:
        return bool(self.api_key and str(self.api_key).strip())

    def _failed(self, error: str, raw_response: str = "") -> GenerationResult:
        return GenerationResult(
            sql="",
            raw_response=raw_response,
            success=False,
            error=error,
            refused=False,
        )

    def generate_sql(self, prompt: str, schema_info: str) -> GenerationResult:
        """Asks the model for SQL. Returns GenerationResult."""
        if not self.is_available():
            return self._failed(
                "No OpenRouter API key found. Add OPENROUTER_API_KEY to .env or enter one above."
            )

        system_prompt, user_prompt = get_sqlite_prompt(prompt, schema_info)
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": self.temperature,
            "max_tokens": 1000,
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

                    if "error" in data:
                        error = data["error"]
                        err_msg = (
                            error.get("message", str(error)) if isinstance(error, dict) else error
                        )
                        return self._failed(f"OpenRouter error: {err_msg}")

                    raw_content = ""
                    finish_reason = ""
                    if data.get("choices"):
                        choice = data["choices"][0]
                        finish_reason = choice.get("finish_reason", "")
                        raw_content = choice.get("message", {}).get("content", "") or ""

                    if finish_reason == "length":
                        return self._failed(
                            "The model response was truncated (token limit reached)."
                        )

                    if is_refusal(raw_content):
                        return GenerationResult(
                            sql=REFUSAL,
                            raw_response=raw_content,
                            success=True,
                            refused=True,
                        )

                    extracted = extract_sql(raw_content)
                    return GenerationResult(
                        sql=extracted,
                        raw_response=raw_content,
                        success=True,
                        refused=False,
                    )

            except urllib.error.HTTPError as e:
                if e.code == 429 and attempt < 2:
                    time.sleep(5 * (attempt + 1))
                    continue

                if e.code == 401:
                    return self._failed(
                        "OpenRouter rejected the API key. Please check that your key is valid."
                    )
                if e.code == 429:
                    return self._failed(RATE_LIMITED)

                try:
                    err_body = e.read().decode("utf-8")
                except (OSError, UnicodeDecodeError):
                    err_body = ""
                return self._failed(
                    f"OpenRouter returned HTTP {e.code}: {e.reason}. {err_body}", err_body
                )
            except urllib.error.URLError as e:
                return self._failed(f"Could not reach OpenRouter: {e.reason!s}")
            except TimeoutError:
                return self._failed(f"OpenRouter did not answer within {self.timeout:.0f} s.")
            except json.JSONDecodeError:
                return self._failed("OpenRouter sent a reply that is not JSON.")
            except Exception as e:
                return self._failed(f"Unexpected error calling OpenRouter: {e!s}")

        return self._failed("Request timed out after retries.")
