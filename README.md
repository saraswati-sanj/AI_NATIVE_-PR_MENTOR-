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

## Live demo

| Piece | URL |
|---|---|
| Frontend | _(to fill in)_ |
| Backend | _(to fill in)_ |

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

| Layer | Modules |
|---|---|
| Backend | `main.py` · `models.py` · `parser.py` · `rules.py` · `ai_review.py` · `pipeline.py` |
| Frontend | `App.tsx` · `api.ts` · `types.ts` · `examples.ts` · `components/` |

The full design, including the data model, the guardrail table and the ranking rules, is in [DESIGN.md](DESIGN.md).

---

## Core design decision

**Deterministic checks and AI opinions are kept apart, and only one of them is trusted.**

| | Rule engine | AI reviewer |
|---|---|---|
| Source label | `rule` | `ai` |
| Accuracy | Certain | Can be wrong |
| Coverage | Known patterns only | Logic, intent, edge cases, design |
| Cost and speed | Free, about 1s | API cost, about 3-8s |
| Trust handling | Shown as reported | Verified before display |

Rule findings are passed **into** the AI prompt, so the model spends its attention on what linters cannot catch instead of restating them.

Every AI finding must survive four checks before it is shown:

1. It must sit on a line that actually changed.
2. Its line number must exist in the code.
3. It must not repeat a rule finding on the same line and category.
4. Its suggested fix is parsed with `ast.parse`; if it does not parse, the card says so.

Findings rejected by these checks are counted and surfaced in the UI as *"N AI findings were discarded by the guardrails"* — so the verification is visible rather than silent.

**The principle: rules are trusted, AI is verified.**

---

## Setup

Requires Python 3.11+ and Node 18, 20, or 22+ (the range Vite 6 supports).

### Backend

```bash
cd backend
python -m venv venv
```

Activate it — on Windows:

```bash
venv\Scripts\activate
```

On macOS or Linux:

```bash
source venv/bin/activate
```

Then install and run:

```bash
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

Copy `backend/.env.example` to `backend/.env` and fill it in:

| Variable | Purpose |
|---|---|
| `GEMINI_API_KEY` | Gemini API key from [Google AI Studio](https://ai.google.dev). Without it the app still runs, using rule findings only. |
| `GEMINI_MODEL` | The Gemini model name to call, e.g. a current Flash model. |
| `FRONTEND_ORIGIN` | The single origin allowed by CORS. Defaults to `http://localhost:5173`. |

To load that file, add `--env-file .env` to the `uvicorn` command. (`python-dotenv` ships with `uvicorn[standard]`, so this needs no extra dependency.)

### Frontend

```bash
cd frontend
npm install
npm run dev
```

Copy `frontend/.env.example` to `frontend/.env` if your backend is not on the default address:

| Variable | Purpose |
|---|---|
| `VITE_API_URL` | Backend base URL. Defaults to `http://127.0.0.1:8000`. |

With both running, open `http://localhost:5173`. The defaults for `VITE_API_URL` and `FRONTEND_ORIGIN` already match, so local development needs no `.env` at all.

---

## Running tests

```bash
cd backend && python -m pytest tests/ -v
```

The tests monkeypatch the Gemini call, so they make no network requests and need no API key. The rule engine runs for real, so `ruff` and `bandit` are exercised too.

They cover: changed-line extraction from a diff, snippet mode, each of the four guardrails, fix verification in both directions, ranking order, and the fallback to rule-only results when the AI is unavailable.

---

## Evaluation results

No model is trained. Quality is measured against a small set of snippets with planted bugs. The expected catches below come from the design; **the result columns are not yet filled in.**

Run each snippet through the deployed app with a valid `GEMINI_API_KEY` and record what came back.

| Snippet | Expected catch | Expected source | Caught? | Actual source |
|---|---|---|---|---|
| SQL built with string concatenation | SQL injection | rule (bandit) | | |
| `def f(items=[])` | Mutable default argument | rule (ruff) | | |
| Bare `except:` | Swallowed errors | rule (ruff) | | |
| `range(len(x) + 1)` indexing | Off-by-one / IndexError | ai | | |
| Missing `None` check on input | Unhandled edge case | ai | | |
| File opened without `with` | Resource leak | rule or ai | | |
| Clean, correct function | No findings | — | | |

**Bugs caught:** _(to fill in)_ of 6
**False positives on clean code:** _(to fill in)_

> The first three rows and the resource-leak row are caught by the rule engine, which runs without an API key. The two `ai` rows require a working Gemini key to evaluate at all.

---

## What was cut and why

| Cut | Reason |
|---|---|
| GitHub PR integration | OAuth and webhooks would have eaten the whole time budget. |
| Accounts, history, database | A stateless review needs no persistence, and it avoids storing users' code. |
| Languages other than Python | The rule tooling differs per language. |
| Executing user code | A security risk with no upside; parsing and linting is enough. |
| Model training or fine-tuning | Not feasible in the time available. A pretrained model with guardrails is the better trade. |

Two things were deliberately **not** cut, because they are the point of the project: the rule/AI separation, and the changed-lines guardrail.

User code is never executed. It is written to a temporary directory that `ruff` and `bandit` only parse, and the directory is deleted when the request ends.

---

## How AI was used

### What the AI wrote

_(to fill in)_

### What I changed

_(to fill in)_

### What the AI got wrong

_(to fill in)_

---

## Future work

- GitHub PR integration, commenting directly on pull requests
- More languages, starting with the ones whose linters have JSON output
- Review history and accounts, so progress on a concept can be tracked
- Learning from mentor feedback on which findings were actually useful
- Caching identical snippets to cut API cost on repeated demos
