"""Pydantic models matching DESIGN.md section 6 exactly."""

from __future__ import annotations

from pydantic import BaseModel, Field
from typing import Literal


# ── Finding ──────────────────────────────────────────────────────────

class Finding(BaseModel):
    id: str                                                     # e.g. "r1", "a3"
    line: int                                                   # line in reconstructed new code
    severity: Literal["critical", "major", "minor"]
    category: Literal["security", "bug", "performance", "readability", "style"]
    source: Literal["rule", "ai"]
    title: str                                                  # one-line summary
    why_it_matters: str                                         # teaching explanation
    suggested_fix: str | None = None                            # code
    fix_verified: bool = False                                  # ast.parse passed
    concept: str | None = None                                  # what to learn next
    rule_id: str | None = None                                  # e.g. "B608" (rule only)
    confidence: float | None = Field(default=None, ge=0, le=1)  # AI only, 0-1


# ── Request / Response ───────────────────────────────────────────────

class ReviewRequest(BaseModel):
    input: str
    mode: Literal["auto", "snippet", "diff"] = "auto"


class Meta(BaseModel):
    is_partial: bool
    rule_count: int
    ai_count: int
    ai_dropped: int
    ai_available: bool
    duration_ms: int


class ReviewResponse(BaseModel):
    findings: list[Finding]
    meta: Meta
