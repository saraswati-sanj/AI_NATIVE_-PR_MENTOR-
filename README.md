# PR Mentor AI

> A code reviewer that teaches, not just criticizes.
> Paste a Python snippet or a diff, get prioritized findings that explain what is wrong, why it matters, how to fix it, and what to go and learn.

---

## What it is

Beginner developers get review comments that say *what* is wrong but not *why*. Pure AI reviewers have the opposite problem: they explain well, but they also hallucinate issues, cite lines that do not exist, and suggest fixes that do not run.

PR Mentor AI combines the two and labels every finding by where it came from:

- **Rule findings** come from `ast`, `ruff` and `bandit`. They are deterministic and limited in coverage, and they are shown exactly as the tools reported them.
- **AI findings** come from Gemini, which can reason about logic, edge cases and design. Everything it returns is checked by code before it reaches the screen.

Paste code, press Review, and get a severity-ranked list where each card carries a teaching explanation and a concept to learn next.

---



---

## Architecture

```
React frontend  ──POST /review──>  FastAPI backend
                                         │
                                   Diff parser          code + changed_lines + is_partial
                                    │        │
                            Rule engine ─────┼──> rule findings fed into the prompt
                            ast·ruff·bandit  │
                                    │   Gemini reviewer  structured JSON output
                                    │        │
                                Guardrails + ranker      filter · dedupe · verify fixes · sort
                                         │
                                   ranked findings + meta ──> React frontend
```




