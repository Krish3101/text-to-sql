"""Pulls the SQL out of a model reply, verbatim."""

import re

REFUSAL = "-- REFUSE: read-only"

# Matches standard markdown code fences with optional language tag (e.g. ```sql, ```sqlite, ```SQL)
FENCE_PATTERN = re.compile(r"```[A-Za-z]*\s*\n?([\s\S]*?)```")

# Matches bare statements starting from WITH or SELECT when no fence is present
RAW_SQL_PATTERN = re.compile(r"(?is)\b(WITH\b[\s\S]+|SELECT\b[\s\S]+)")


def is_refusal(text: str | None) -> bool:
    """True only when the whole reply (or its only code block) is the refusal line."""
    body = (text or "").strip()
    fence = FENCE_PATTERN.fullmatch(body)
    if fence:
        body = fence.group(1).strip()
    # The prompt shows the line in `inline code`, so allow the model to copy the backticks
    return body.strip("`").strip().lower() == REFUSAL.lower()


def extract_sql(text: str | None) -> str:
    """
    Extracts the SQL query from LLM generated response text.
    Handles code fences (taking the last fence if multiple exist),
    bare SELECT/WITH statements, and returns empty string if no valid SQL is found.
    The SQL itself is not changed; the guardrail copes with trailing semicolons and comments.
    """
    if not text or not str(text).strip():
        return ""

    raw = str(text).strip()

    # Look for markdown code fences first
    fence_matches = FENCE_PATTERN.findall(raw)
    if fence_matches:
        # Take the last fence block (in case the model printed intermediate reasoning blocks)
        candidate = fence_matches[-1].strip()
        if candidate:
            return candidate

    # Without a code fence, search for bare WITH or SELECT
    raw_match = RAW_SQL_PATTERN.search(raw)
    if raw_match:
        # Stop at a semicolon that ends a line, so prose after the query is dropped
        candidate = re.split(r"(?<=;)\s*\n", raw_match.group(1), maxsplit=1)[0]
        return candidate.strip()

    return ""
