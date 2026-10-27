"""Orchestration, guardrails and ranking (DESIGN.md sections 4, 9 and 10).

This is where the design's central principle lives: rule findings are trusted
and passed through, while AI findings must survive the guardrails below before
anyone sees them. Everything the guardrails reject is counted into
meta.ai_dropped so the UI can show that the verification actually happened.
"""

from __future__ import annotations

import ast
import textwrap
import time

# Imported as a module, not as a function, so tests can monkeypatch
# ai_review.review without this module holding a stale reference to it.
from . import ai_review
from .models import Finding, Meta, ReviewResponse
from .parser import parse_input
from .rules import run_rules

# DESIGN.md section 10: severity, then category, then source, then line.
_SEVERITY_ORDER = {"critical": 0, "major": 1, "minor": 2}
_CATEGORY_ORDER = {"security": 0, "bug": 1, "performance": 2, "readability": 3, "style": 4}
_SOURCE_ORDER = {"rule": 0, "ai": 1}


def _fix_parses(fix: str | None) -> bool:
    """True if a suggested fix is valid Python on its own.

    The fix is dedented first: a replacement for an indented block arrives with
    its original indentation, which would fail to parse for a reason that has
    nothing to do with whether the fix is correct.
    """
    if not fix or not fix.strip():
        return False
    try:
        ast.parse(textwrap.dedent(fix))
    except (SyntaxError, ValueError):
        return False
    return True


def _apply_guardrails(
    ai_findings: list[Finding],
    rule_findings: list[Finding],
    code: str,
    changed_lines: set[int],
) -> tuple[list[Finding], int]:
    """Verify AI findings per DESIGN.md section 9.

    Returns (kept, dropped_count). Fixes on kept findings are marked verified
    or not; dropped findings are only counted, never shown.
    """
    total_lines = len(code.splitlines())
    rule_keys = {(f.line, f.category) for f in rule_findings}

    kept: list[Finding] = []
    dropped = 0

    for finding in ai_findings:
        if not 1 <= finding.line <= total_lines:
            dropped += 1          # line number outside the code
            continue
        if finding.line not in changed_lines:
            dropped += 1          # unchanged or context line
            continue
        if (finding.line, finding.category) in rule_keys:
            dropped += 1          # restates what a linter already reported
            continue

        finding.fix_verified = _fix_parses(finding.suggested_fix)
        kept.append(finding)

    return kept, dropped


def _rank(findings: list[Finding]) -> list[Finding]:
    """Sort by severity, then category, then rule-before-AI, then line."""
    return sorted(
        findings,
        key=lambda f: (
            _SEVERITY_ORDER[f.severity],
            _CATEGORY_ORDER[f.category],
            _SOURCE_ORDER[f.source],
            f.line,
        ),
    )


def run_review(text: str, mode: str = "auto") -> ReviewResponse:
    """parse -> rules -> AI -> guardrails -> rank (DESIGN.md section 4).

    Raises ValueError for input the parser rejects, such as a multi-file diff.
    """
    started = time.perf_counter()

    parsed = parse_input(text, mode)
    rule_findings = run_rules(parsed.code, parsed.changed_lines)

    # Rule findings go into the prompt so the AI covers what rules cannot.
    ai_findings, ai_available = ai_review.review(
        parsed.code, parsed.changed_lines, rule_findings
    )
    kept_ai, ai_dropped = _apply_guardrails(
        ai_findings, rule_findings, parsed.code, parsed.changed_lines
    )

    return ReviewResponse(
        findings=_rank(rule_findings + kept_ai),
        meta=Meta(
            is_partial=parsed.is_partial,
            rule_count=len(rule_findings),
            ai_count=len(kept_ai),
            ai_dropped=ai_dropped,
            ai_available=ai_available,
            duration_ms=int((time.perf_counter() - started) * 1000),
        ),
    )
