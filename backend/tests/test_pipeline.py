"""Tests for the parser, the guardrails and the ranker (DESIGN.md sections 4, 9, 10).

No test makes a real Gemini call: ai_review.review is monkeypatched everywhere.
The rule engine does run for real, so these also cover ruff and bandit.
"""

import sys
from pathlib import Path

# backend/ on sys.path so `app` imports. Rule 1 does not allow a conftest.py,
# which is where this would normally live; `python -m pytest` also works.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import ai_review  # noqa: E402
from app.models import Finding  # noqa: E402
from app.parser import parse_input  # noqa: E402
from app.pipeline import _apply_guardrails, run_review  # noqa: E402

# A diff whose only added line is line 3 of the rebuilt file.
DIFF = """--- a/calc.py
+++ b/calc.py
@@ -1,3 +1,4 @@
 def total(items):
     result = 0
+    result = sum(items)
     return result
"""

# Bare `except:` on line 4, which ruff reports as E722 in the "bug" category.
BARE_EXCEPT = """def read_count(path):
    try:
        return int(open(path).read())
    except:
        return 0
"""

# No rule findings, so ranking tests see only what the stub returns.
CLEAN = """def average(numbers):
    if not numbers:
        raise ValueError("numbers must not be empty")
    return sum(numbers) / len(numbers)
"""


def ai_finding(
    line: int,
    severity: str = "major",
    category: str = "bug",
    fix: str | None = None,
    title: str = "AI issue",
) -> Finding:
    """Build an AI finding as ai_review would return it, before guardrails."""
    return Finding(
        id=f"a{line}",
        line=line,
        severity=severity,
        category=category,
        source="ai",
        title=title,
        why_it_matters="Explanation for the junior developer.",
        suggested_fix=fix,
        fix_verified=False,
        concept="Some concept",
        confidence=0.8,
    )


def stub_ai(monkeypatch, findings: list[Finding], available: bool = True) -> None:
    """Replace the Gemini call with a fixed result."""
    monkeypatch.setattr(
        ai_review,
        "review",
        lambda code, changed_lines, rule_findings: (list(findings), available),
    )


# -- 1. Parser: diff --------------------------------------------------

def test_diff_marks_only_added_lines_as_changed():
    parsed = parse_input(DIFF, "diff")

    assert parsed.changed_lines == {3}
    assert parsed.code.splitlines()[2].strip() == "result = sum(items)"
    assert parsed.is_partial is False


# -- 2. Parser: snippet -----------------------------------------------

def test_snippet_marks_every_line_as_changed():
    parsed = parse_input("a = 1\nb = 2\nc = 3\n", "snippet")

    assert parsed.changed_lines == {1, 2, 3}
    assert parsed.is_partial is False


# -- 3. Guardrail: changed-lines filter -------------------------------

def test_ai_finding_on_unchanged_line_is_dropped(monkeypatch):
    # Line 1 is context in DIFF, so the AI must not be allowed to comment on it.
    stub_ai(monkeypatch, [ai_finding(line=1)])

    response = run_review(DIFF, "diff")

    assert response.meta.ai_count == 0
    assert response.meta.ai_dropped == 1
    assert all(f.source == "rule" for f in response.findings)


def test_line_outside_the_code_is_dropped_even_when_marked_changed():
    """Cover the line-range guardrail (DESIGN.md section 9) in isolation.

    parse_input never puts an out-of-range line into changed_lines, so going
    through run_review would only exercise the changed-lines filter. This calls
    the guardrail directly with a hallucinated line number.
    """
    kept, dropped = _apply_guardrails(
        [ai_finding(line=99)], [], "a = 1\nb = 2\n", {1, 2, 99}
    )

    assert kept == []
    assert dropped == 1


# -- 4. Guardrail: dedupe against rule findings -----------------------

def test_ai_finding_duplicating_a_rule_finding_is_dropped(monkeypatch):
    # ruff reports E722 ("bug") on line 4, so an AI "bug" on line 4 is a repeat.
    stub_ai(monkeypatch, [ai_finding(line=4, category="bug")])

    response = run_review(BARE_EXCEPT, "snippet")

    rule_lines = {(f.line, f.category) for f in response.findings if f.source == "rule"}
    assert (4, "bug") in rule_lines, "expected ruff E722 on line 4"
    assert response.meta.ai_count == 0
    assert response.meta.ai_dropped == 1


def test_ai_finding_on_same_line_but_different_category_is_kept(monkeypatch):
    # Dedupe is line AND category, so a different category is not a duplicate.
    stub_ai(monkeypatch, [ai_finding(line=4, category="performance")])

    response = run_review(BARE_EXCEPT, "snippet")

    assert response.meta.ai_count == 1
    assert response.meta.ai_dropped == 0


# -- 5. Guardrail: fix verification -----------------------------------

def test_invalid_suggested_fix_is_not_verified(monkeypatch):
    stub_ai(monkeypatch, [ai_finding(line=2, fix="result = ((")])

    response = run_review(CLEAN, "snippet")
    ai_findings = [f for f in response.findings if f.source == "ai"]

    assert len(ai_findings) == 1
    assert ai_findings[0].fix_verified is False


def test_valid_suggested_fix_is_verified(monkeypatch):
    stub_ai(monkeypatch, [ai_finding(line=2, fix="result = sum(items)")])

    response = run_review(CLEAN, "snippet")
    ai_findings = [f for f in response.findings if f.source == "ai"]

    assert len(ai_findings) == 1
    assert ai_findings[0].fix_verified is True


# -- 6. Ranking -------------------------------------------------------

def test_critical_security_ranks_before_minor_style(monkeypatch):
    stub_ai(
        monkeypatch,
        [
            ai_finding(line=4, severity="minor", category="style", title="style issue"),
            ai_finding(line=2, severity="critical", category="security", title="security hole"),
        ],
    )

    response = run_review(CLEAN, "snippet")

    assert [f.title for f in response.findings] == ["security hole", "style issue"]


# -- 7. AI failure still returns rule findings ------------------------

def test_rule_findings_survive_when_ai_is_unavailable(monkeypatch):
    stub_ai(monkeypatch, [], available=False)

    response = run_review(BARE_EXCEPT, "snippet")

    assert response.meta.ai_available is False
    assert response.meta.ai_count == 0
    assert response.meta.rule_count > 0
    assert any(f.rule_id == "E722" for f in response.findings)
