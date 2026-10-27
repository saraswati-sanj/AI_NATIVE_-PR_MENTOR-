# PR Mentor AI — System Design & Architecture

> A code reviewer that teaches, not just criticizes.
> Paste a Python snippet or diff → get prioritized findings, each explaining what's wrong, why it matters, how to fix it, and what concept to learn.

---

## 1. Goal and scope

**Problem:** Beginner developers get code review comments that say *what* is wrong but not *why*. Pure AI reviewers also hallucinate issues, cite wrong lines and suggest broken fixes.

**Solution:** Combine **deterministic static analysis** (always correct, limited coverage) with **LLM review** (broad coverage, can be wrong), label every finding by source, and **verify the AI's output with code** before showing it.

### In scope (6 hours)
- Python only
- Pasted code snippet **or** pasted unified diff
- Rule-based checks: syntax (`ast`), lint/bugs (`ruff`), security (`bandit`)
- AI review via Gemini with structured JSON output
- Guardrails: changed-lines filter, dedupe, fix validation
- Severity-ranked results UI with teaching explanations
- Deployed frontend + backend

### Out of scope (deliberate cuts)
| Cut | Reason |
|---|---|
| GitHub PR integration | OAuth + webhooks would eat the time budget |
| Accounts / history / database | Stateless review needs no persistence; avoids storing users' code |
| Languages other than Python | Rule tooling differs per language |
| Executing user code | Security risk; parsing and linting is enough |
| Model training / fine-tuning | Not feasible in 6h; pretrained LLM + guardrails instead |

---

## 2. Core design decision

**Separate deterministic checks from AI opinions.**

| | Rule engine | AI reviewer |
|---|---|---|
| Source label | `rule` | `ai` |
| Accuracy | Certain | Can be wrong |
| Coverage | Known patterns only | Logic, intent, edge cases, design |
| Cost / speed | Free, ~1s | API cost, ~3–8s |
| Trust handling | Shown as-is | Verified by guardrails first |

Rule findings are **passed into the AI prompt** so the AI focuses on what rules cannot catch instead of repeating them.

**Principle: rules are trusted, AI is verified.**

---

## 3. High-level architecture

```
┌──────────────────────┐
│   React frontend     │  paste box · examples · findings list
└──────────┬───────────┘
           │ POST /review (JSON)
┌──────────▼───────────┐
│   FastAPI backend    │  validation · rate limit · orchestration
└──────────┬───────────┘
           │
┌──────────▼───────────┐
│     Diff parser      │  diff/snippet → code + changed_lines + is_partial
└───────┬──────────┬───┘
        │          │
┌───────▼──────┐   │
│ Rule engine  │───┼──── rule findings fed into prompt
│ ast·ruff·    │   │
│ bandit       │ ┌─▼────────────────┐
└───────┬──────┘ │ Gemini reviewer  │  structured JSON output
        │        └─┬────────────────┘
┌───────▼──────────▼───┐
│ Guardrails + ranker  │  filter · dedupe · validate fixes · sort
└──────────┬───────────┘
           │ ranked findings + meta
           ▼
       React frontend
```

---

## 4. Request lifecycle

1. User pastes code/diff and clicks **Review**.
2. Frontend sends `POST /review`.
3. Backend validates input (non-empty, ≤ 300 lines, ≤ 20 KB) and applies rate limit.
4. **Parser** detects diff vs snippet, extracts `changed_lines`, rebuilds code, sets `is_partial` if `ast.parse` fails.
5. **Rule engine** writes code to a temp file, runs `ruff` and `bandit` (JSON output), maps results to `Finding`, keeps only changed lines, deletes temp file.
6. **AI reviewer** sends line-numbered code + changed lines + rule findings to Gemini; receives schema-validated findings (retry once on invalid output; on failure continue without AI).
7. **Guardrails** drop AI findings on unchanged lines, drop duplicates of rule findings, `ast.parse` each suggested fix → `fix_verified`.
8. **Ranker** sorts by severity → category → line.
9. Response returned with `findings` + `meta`; frontend renders cards and banners.

---

## 5. Components

### 5.1 Frontend (React + Vite + TypeScript + Tailwind)
| Component | Responsibility |
|---|---|
| `App` | Page state: idle / loading / results / error |
| `CodeInput` | Textarea, example buttons, Review button, input limits |
| `FindingsList` | Group by severity, Rule/AI filter, summary counts |
| `FindingCard` | Title, source badge, line, why it matters, fix (+copy), concept, verified flag |
| `Banner` | Partial-code, AI-unavailable, AI-dropped notices |
| `api.ts` | Typed `review()` call, timeout, error mapping |
| `examples.ts` | Built-in buggy example snippets for demos |

### 5.2 Backend (FastAPI, Python 3.11+)
| Module | Responsibility |
|---|---|
| `main.py` | App, CORS, rate limit, `POST /review`, `GET /health` |
| `models.py` | Pydantic models: `Finding`, `ReviewRequest`, `ReviewResponse`, `Meta` |
| `parser.py` | Diff/snippet detection, `changed_lines`, code reconstruction |
| `rules.py` | Run `ast`, `ruff`, `bandit`; map to `Finding(source="rule")` |
| `ai_review.py` | Prompt building, Gemini call, schema validation, retry, timeout |
| `pipeline.py` | Orchestration, guardrails, dedupe, ranking |

### 5.3 External services
- **Gemini API** (`google-genai` SDK) — structured output via `response_schema`, temperature ≈ 0.2.

---

## 6. Data model

### Finding
| Field | Type | Notes |
|---|---|---|
| `id` | str | e.g. `r1`, `a3` |
| `line` | int | Line in the reconstructed new code |
| `severity` | `critical` \| `major` \| `minor` | |
| `category` | `security` \| `bug` \| `performance` \| `readability` \| `style` | |
| `source` | `rule` \| `ai` | |
| `title` | str | One-line summary |
| `why_it_matters` | str | Teaching explanation |
| `suggested_fix` | str \| null | Code |
| `fix_verified` | bool | `ast.parse` passed |
| `concept` | str \| null | What to learn next |
| `rule_id` | str \| null | e.g. `B008`, `B608` (rule findings only) |
| `confidence` | float \| null | AI findings only, 0–1 |

### ReviewRequest
```json
{ "input": "string", "mode": "auto | snippet | diff" }
```

### ReviewResponse
```json
{
  "findings": [ /* Finding[] */ ],
  "meta": {
    "is_partial": false,
    "rule_count": 3,
    "ai_count": 4,
    "ai_dropped": 2,
    "ai_available": true,
    "duration_ms": 4120
  }
}
```

---

## 7. API

| Method | Path | Purpose | Errors |
|---|---|---|---|
| `POST` | `/review` | Run full review pipeline | `400` invalid input · `413` too large · `429` rate limited · `500` unexpected |
| `GET` | `/health` | Liveness check for deploy | — |

---

## 8. AI reviewer design

**Prompt inputs**
- Code with explicit line-number prefixes (`12 | cursor.execute(...)`)
- List of changed line numbers
- Rule findings already reported (do not repeat)

**Prompt instructions (summary)**
- Act as a senior Python reviewer mentoring a junior developer.
- Review **only** changed lines; focus on logic bugs, edge cases, error handling, design.
- For each issue: severity, category, line, title, why it matters, minimal fix, concept to learn.
- Return an empty list if the code is fine — do not invent issues.

**Controls**
- `response_schema` = list of AI finding fields
- Temperature ≈ 0.2
- Timeout 20s, one retry on invalid JSON
- On failure: `ai_available=false`, return rule findings only

---

## 9. Guardrails (AI verification)

| Guardrail | Catches |
|---|---|
| Changed-lines filter | AI commenting on unchanged/context lines |
| Line-range check | Line numbers outside the code |
| Dedupe vs rules (same line + category) | AI restating lint warnings |
| `ast.parse(suggested_fix)` | Fixes that aren't valid Python |
| Count of dropped findings → `meta.ai_dropped` | Makes guardrails visible in UI |

---

## 10. Ranking

1. Severity: `critical` > `major` > `minor`
2. Category: `security` > `bug` > `performance` > `readability` > `style`
3. Source: `rule` before `ai` (on ties)
4. Line number ascending

---

## 11. Error handling and edge cases

| Case | Behavior |
|---|---|
| Empty / oversized input | `400` / `413` with clear message |
| Partial diff hunk (not valid Python alone) | Rules run where possible, `is_partial=true`, UI banner |
| Gemini timeout / error / bad JSON twice | Rule findings only, `ai_available=false`, UI banner |
| ruff/bandit crash | Log, skip that tool, continue |
| No findings | Friendly "No issues found" empty state |
| Rate limit exceeded | `429`, UI shows retry message |

---

## 12. Security

- User code is **never executed** — only parsed and linted.
- Temp files written to a per-request temp dir and deleted after use.
- `GEMINI_API_KEY` only in environment variables; `.env.example` committed, `.env` gitignored.
- CORS restricted to the frontend origin.
- Input size limits and per-IP rate limiting (`slowapi`).

---

## 13. Tech stack

| Layer | Choice |
|---|---|
| Frontend | React, Vite, TypeScript, Tailwind CSS |
| Backend | FastAPI, Uvicorn, Pydantic v2 |
| Static analysis | Python `ast`, `ruff`, `bandit` |
| Diff parsing | `unidiff` |
| LLM | Gemini via `google-genai` SDK |
| Rate limiting | `slowapi` |
| Tests | `pytest` |
| Hosting | Vercel (frontend), Render or Railway (backend) |

---

## 14. Folder structure

```
pr-mentor-ai/
├── backend/
│   ├── app/
│   │   ├── main.py
│   │   ├── models.py
│   │   ├── parser.py
│   │   ├── rules.py
│   │   ├── ai_review.py
│   │   └── pipeline.py
│   ├── tests/
│   │   └── test_pipeline.py
│   ├── requirements.txt
│   └── .env.example
├── frontend/
│   ├── src/
│   │   ├── App.tsx
│   │   ├── api.ts
│   │   ├── examples.ts
│   │   ├── types.ts
│   │   └── components/
│   │       ├── CodeInput.tsx
│   │       ├── FindingsList.tsx
│   │       ├── FindingCard.tsx
│   │       └── Banner.tsx
│   └── .env.example
├── DESIGN.md
└── README.md
```

---

## 15. Deployment

| Piece | Platform | Config |
|---|---|---|
| Frontend | Vercel | `VITE_API_URL` = backend URL |
| Backend | Render / Railway | Start: `uvicorn app.main:app --host 0.0.0.0 --port $PORT`; env `GEMINI_API_KEY`, `FRONTEND_ORIGIN` |

Deploy a hello-world version of both early so deployment problems surface before the end.

---

## 16. Evaluation (instead of training)

No model is trained. Quality is measured with a small evaluation set of snippets with **planted bugs**:

| Snippet | Expected catch | Expected source |
|---|---|---|
| SQL built with string concatenation | SQL injection | rule (bandit) |
| `def f(items=[])` | Mutable default argument | rule (ruff) |
| Bare `except:` | Swallowed errors | rule (ruff) |
| `range(len(x) + 1)` indexing | Off-by-one / IndexError | ai |
| Missing `None` check on input | Unhandled edge case | ai |
| File opened without `with` | Resource leak | rule or ai |
| Clean, correct function | No findings | — (false-positive check) |

Report: bugs caught / planted, and false positives on clean code.

---

## 17. Build order (6 hours)

| Time | Milestone |
|---|---|
| 0:00–0:30 | Repo, README skeleton, evaluation snippets |
| 0:30–2:00 | `models`, `parser`, `rules` — working without AI |
| 2:00–3:15 | `ai_review`, `pipeline` guardrails + ranking |
| 3:15–4:30 | Frontend, deploy both, live end-to-end test |
| 4:30–5:15 | Fix issues, `pytest` tests, run evaluation set |
| 5:15–5:40 | README: setup, architecture, cuts, AI-written vs changed |
| 5:40–6:00 | Record demo on live URL, verify links |

**Cut first if behind:** confidence scores → source filter → copy button → backend deploy (demo locally and say so).
**Never cut:** rule/AI separation and the changed-lines guardrail.

---

## 18. Future work

- GitHub PR integration (comment directly on PRs)
- More languages
- Review history and accounts
- Learn from mentor feedback on which findings were useful
