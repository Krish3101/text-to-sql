"""The OpenRouter request, and pulling the SQL out of the model's reply."""

import json
import os
import re
import time
import urllib.error
import urllib.request

from text_to_sql.config import get_model

ENDPOINT = "https://openrouter.ai/api/v1/chat/completions"

# Shown when OpenRouter still answers 429 after the retries. The eval stops on it.
RATE_LIMITED = (
    "OpenRouter is rate-limiting this key (free models allow about 50 requests a day). "
    "Wait a minute and try again, or try tomorrow."
)

# A markdown code fence with an optional language tag (```sql, ```sqlite, ```SQL)
FENCE_PATTERN = re.compile(r"```[A-Za-z]*\s*\n?([\s\S]*?)```")

# A bare statement starting at WITH or SELECT, for replies without a fence
RAW_SQL_PATTERN = re.compile(r"(?is)\b(WITH\b[\s\S]+|SELECT\b[\s\S]+)")


def extract_sql(text: str | None) -> str:
    """The SQL in a reply, unchanged: the last code fence, else a bare SELECT/WITH, else ""."""
    raw = (text or "").strip()
    if not raw:
        return ""

    fences = FENCE_PATTERN.findall(raw)
    # The last fence wins, in case the model printed intermediate blocks first.
    if fences and fences[-1].strip():
        return fences[-1].strip()

    match = RAW_SQL_PATTERN.search(raw)
    if match:
        # Stop at a semicolon that ends a line, so prose after the query is dropped
        return re.split(r"(?<=;)\s*\n", match.group(1), maxsplit=1)[0].strip()
    return ""


def ask_model(system_prompt: str, question: str, timeout: float = 60.0) -> str:
    """Sends one chat request and returns the SQL from the reply.

    Raises RuntimeError with a one-line message for the page on any failure.
    """
    key = os.environ.get("OPENROUTER_API_KEY", "").strip()
    if not key:
        raise RuntimeError("No OpenRouter API key found. Add OPENROUTER_API_KEY to .env.")

    payload = {
        "model": get_model(),
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": question.strip()},
        ],
        "temperature": 0.0,
        "max_tokens": 1000,
        "reasoning": {"enabled": False},
    }
    request = urllib.request.Request(
        ENDPOINT,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://github.com/Krish3101/text-to-sql",
            "X-Title": "Text-to-SQL",
        },
        method="POST",
    )

    for attempt in range(3):
        try:
            with urllib.request.urlopen(request, timeout=timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            if e.code == 429 and attempt < 2:
                time.sleep(5 * (attempt + 1))
                continue
            if e.code == 401:
                raise RuntimeError(
                    "OpenRouter rejected the API key. Please check that your key is valid."
                ) from e
            if e.code == 429:
                raise RuntimeError(RATE_LIMITED) from e
            raise RuntimeError(f"OpenRouter returned HTTP {e.code}: {e.reason}.") from e
        except urllib.error.URLError as e:
            raise RuntimeError(f"Could not reach OpenRouter: {e.reason!s}") from e
        except TimeoutError as e:
            raise RuntimeError(f"OpenRouter did not answer within {timeout:.0f} s.") from e
        except json.JSONDecodeError as e:
            raise RuntimeError("OpenRouter sent a reply that is not JSON.") from e

        if "error" in data:
            error = data["error"]
            message = error.get("message", str(error)) if isinstance(error, dict) else error
            raise RuntimeError(f"OpenRouter error: {message}")

        choice = (data.get("choices") or [{}])[0]
        if choice.get("finish_reason") == "length":
            raise RuntimeError("The model response was truncated (token limit reached).")
        return extract_sql(choice.get("message", {}).get("content"))

    raise RuntimeError(RATE_LIMITED)
