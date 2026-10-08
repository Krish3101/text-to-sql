"""check_sql against the attack list: what may reach SQLite and what must not."""

from pathlib import Path

import pytest
import yaml

from text_to_sql.guardrails import check_sql

CASES = yaml.safe_load((Path(__file__).parent / "attacks.yaml").read_text())


@pytest.mark.parametrize("case", CASES, ids=[c["id"] for c in CASES])
def test_attack_list(case):
    allowed, reason = check_sql(case["sql"])
    assert ("ALLOW" if allowed else "REJECT") == case["expected"], reason
