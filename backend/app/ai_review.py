"""Gemini-backed AI reviewer (DESIGN.md section 8).

Returns (findings, ai_available). This module never raises to its caller: any
failure - missing configuration, transport error, timeout, or output that does
not match the schema twice - degrades to ([], False) so the pipeline can still
return the rule findings on their own.

Guardrails are deliberately NOT applied here. Filtering to changed lines,
deduping against rule findings and verifying fixes with ast.parse all belong to
pipeline.py (DESIGN.md section 9), so that the raw AI output stays inspectable.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Literal

from google import genai
from google.genai import types
from pydantic import BaseModel, Field, ValidationError

from .models import Finding

log = logging.getLogger(__name__)

_TIMEOUT_MS = 20_000      # DESIGN.md section 8: 20 second timeout (SDK wants ms)
_TEMPERATURE = 0.2
_MAX_ATTEMPTS = 2         # the initial call plus one retry on invalid output

_SYSTEM_INSTRUCTION = """\
You are a senior Python engineer reviewing a change for a junior developer you \
are mentoring. Your job is to teach, not just to criticise.

Rules you must follow:
- Review ONLY the lines listed as changed. Every other line is context; never \
report an issue on a line that is not in the changed list.
- Focus on what static analysis cannot see: logic bugs, off-by-one errors, \
unhandled edge cases (empty input, None, zero, boundary values), missing or \
incorrect error handling, wrong assumptions, and design or naming problems that \
will cause real trouble later.
- Do not repeat any issue already reported by static analysis, and do not report \
pure formatting or style preferences.
- Report at most one finding per line, and prefer a few valuable findings over \
many trivial ones.
- If the changed lines are correct, return an empty list. Never invent an issue \
in order to seem useful.

For each finding provide:
- line: the number from the line prefix. It must be one of the changed lines.
- severity: critical (security hole, data loss, or a crash on ordinary input), \
major (wrong behaviour in a realistic case), minor (works, but should improve).
- category: security, bug, performance, readability or style.
- title: one short sentence naming the problem.
- why_it_matters: two or three sentences giving the consequence and the \
reasoning, written for someone who has not met this problem before. Explain the \
why, not just the what.
- suggested_fix: the minimal corrected Python for that line or block. Code only \
- no prose, no markdown fences. Omit it if you cannot give a concrete fix.
- concept: the name of the idea to go and learn, for example "Off-by-one errors" \
or "Guard clauses".
- confidence: 0 to 1, how certain you are that the issue is real. Use less than \
0.5 when you are unsure."""


class _AIFinding(BaseModel):
    """The subset of Finding fields Gemini is asked to produce.

    `id`, `source` and `fix_verified` are owned by the backend, so they are kept
    out of the schema rather than letting the model guess at them.
    """

    line: int
    severity: Literal["critical", "major", "minor"]
    category: Literal["security", "bug", "performance", "readability", "style"]
    title: str
    why_it_matters: str
    suggested_fix: str | None = None
    concept: str | None = None
    confidence: float = Field(ge=0, le=1)


# -- Prompt building -------------------------------------------------

def _number_lines(code: str) -> str:
    """Prefix each line with its number, as '12 | cursor.execute(...)'."""
    lines = code.splitlines()
    width = len(str(len(lines))) if lines else 1
    return "\n".join(f"{n:>{width}} | {line}" for n, line in enumerate(lines, start=1))


def _format_line_ranges(changed_lines: set[int]) -> str:
    """Collapse line numbers into ranges, so '1,2,3,7' becomes '1-3, 7'."""
    if not changed_lines:
        return "none"

    ordered = sorted(changed_lines)
    ranges: list[tuple[int, int]] = [(ordered[0], ordered[0])]
    for line in ordered[1:]:
        start, end = ranges[-1]
        if line == end + 1:
            ranges[-1] = (start, line)
        else:
            ranges.append((line, line))

    return ", ".join(str(a) if a == b else f"{a}-{b}" for a, b in ranges)


def _rule_findings_block(rule_findings: list[Finding]) -> str:
    """List what the linters already found, so the AI does not restate it."""
    if not rule_findings:
        return (
            "ALREADY REPORTED BY STATIC ANALYSIS: nothing.\n"
            "Look for the problems a linter cannot detect."
        )

    lines = []
    for finding in rule_findings:
        rule = f" ({finding.rule_id})" if finding.rule_id else ""
        lines.append(f"- line {finding.line} [{finding.category}] {finding.title}{rule}")

    return (
        "ALREADY REPORTED BY STATIC ANALYSIS (do not repeat any of these):\n"
        + "\n".join(lines)
    )


def _build_prompt(code: str, changed_lines: set[int], rule_findings: list[Finding]) -> str:
    return "\n\n".join(
        [
            "Review the changed lines of this Python code.",
            "CODE (line number | source):\n" + _number_lines(code),
            "CHANGED LINES (review only these): " + _format_line_ranges(changed_lines),
            _rule_findings_block(rule_findings),
        ]
    )


# -- Model call ------------------------------------------------------

def _response_text(response: object) -> str | None:
    """Pull the text out of a response, tolerating blocked or empty candidates."""
    try:
        return response.text
    except Exception as exc:  # noqa: BLE001 - a malformed response must not raise
        log.warning("Gemini response had no readable text: %s", exc)
        return None


def _call_gemini(client: genai.Client, model: str, prompt: str) -> str | None:
    """One Gemini call with structured output. Raises on transport failure."""
    response = client.models.generate_content(
        model=model,
        contents=prompt,
        config=types.GenerateContentConfig(
            system_instruction=_SYSTEM_INSTRUCTION,
            temperature=_TEMPERATURE,
            response_mime_type="application/json",
            response_schema=list[_AIFinding],
            http_options=types.HttpOptions(timeout=_TIMEOUT_MS),
        ),
    )
    return _response_text(response)


def _parse(text: str | None) -> list[_AIFinding] | None:
    """Validate the model's JSON against the schema. None means unusable."""
    if not text or not text.strip():
        log.warning("Gemini returned empty output")
        return None

    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        log.warning("Gemini returned invalid JSON: %s", exc)
        return None

    if not isinstance(payload, list):
        log.warning("Gemini returned %s, expected a list of findings", type(payload).__name__)
        return None

    try:
        return [_AIFinding.model_validate(item) for item in payload]
    except ValidationError as exc:
        log.warning("Gemini output did not match the schema: %s", exc.error_count())
        return None


def _to_findings(items: list[_AIFinding]) -> list[Finding]:
    """Convert validated model output into Findings with source="ai"."""
    return [
        Finding(
            id=f"a{number}",
            line=item.line,
            severity=item.severity,
            category=item.category,
            source="ai",
            title=item.title,
            why_it_matters=item.why_it_matters,
            suggested_fix=item.suggested_fix,
            fix_verified=False,     # pipeline.py verifies fixes (DESIGN.md section 9)
            concept=item.concept,
            confidence=item.confidence,
        )
        for number, item in enumerate(items, start=1)
    ]


# -- Entry point -----------------------------------------------------

def review(
    code: str,
    changed_lines: set[int],
    rule_findings: list[Finding],
) -> tuple[list[Finding], bool]:
    """Ask Gemini to review the changed lines.

    Returns (findings, ai_available). On any failure the result is ([], False)
    and the caller continues with rule findings alone.
    """
    api_key = os.environ.get("GEMINI_API_KEY", "").strip()
    model = os.environ.get("GEMINI_MODEL", "").strip()
    if not api_key or not model:
        log.warning("AI review skipped: GEMINI_API_KEY and GEMINI_MODEL must both be set")
        return [], False

    try:
        client = genai.Client(api_key=api_key)
    except Exception as exc:  # noqa: BLE001 - configuration errors must not raise
        log.warning("Could not create the Gemini client: %s", exc)
        return [], False

    prompt = _build_prompt(code, changed_lines, rule_findings)

    for attempt in range(1, _MAX_ATTEMPTS + 1):
        try:
            text = _call_gemini(client, model, prompt)
        except Exception as exc:  # noqa: BLE001 - timeout, auth, quota, network
            # Not retried: a retry after a 20s timeout would blow the frontend's
            # own request budget, and auth or quota errors will not fix themselves.
            log.warning("Gemini call failed: %s: %s", type(exc).__name__, exc)
            return [], False

        findings = _parse(text)
        if findings is not None:
            # An empty list is a valid answer: the code is fine.
            return _to_findings(findings), True

        log.warning("Unusable Gemini output on attempt %s of %s", attempt, _MAX_ATTEMPTS)

    return [], False
