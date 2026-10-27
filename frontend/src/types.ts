/**
 * Mirrors backend/app/models.py exactly (DESIGN.md section 6).
 * Any change here needs the same change there.
 */

export type Severity = "critical" | "major" | "minor";
export type Category = "security" | "bug" | "performance" | "readability" | "style";
export type Source = "rule" | "ai";
export type Mode = "auto" | "snippet" | "diff";

export interface Finding {
  id: string;
  line: number;
  severity: Severity;
  category: Category;
  source: Source;
  title: string;
  why_it_matters: string;
  suggested_fix: string | null;
  fix_verified: boolean;
  concept: string | null;
  rule_id: string | null;
  confidence: number | null;
}

export interface Meta {
  is_partial: boolean;
  rule_count: number;
  ai_count: number;
  ai_dropped: number;
  ai_available: boolean;
  duration_ms: number;
}

export interface ReviewResponse {
  findings: Finding[];
  meta: Meta;
}

export interface ReviewRequest {
  input: string;
  mode: Mode;
}

/** Severity order used for grouping, matching DESIGN.md section 10. */
export const SEVERITY_ORDER: Severity[] = ["critical", "major", "minor"];
