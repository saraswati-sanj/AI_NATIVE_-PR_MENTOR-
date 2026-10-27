"""Deterministic rule engine: `ast`, `ruff` and `bandit` -> Finding(source="rule").

The user's code is never executed. It is written to a file inside a temporary
directory that ruff and bandit only *parse*; the directory and its contents are
deleted when the context manager exits.
"""

from __future__ import annotations

import ast
import json
import logging
import subprocess
import sys
import tempfile
from pathlib import Path

from .models import Finding

log = logging.getLogger(__name__)

# A hard timeout so a pathological snippet cannot hang a request.
_TIMEOUT_SECONDS = 20

# Fixed, neutral filename: `python -m` would otherwise let a snippet named
# e.g. "json.py" shadow a stdlib import inside the tool's own subprocess.
_TARGET_FILENAME = "review_target.py"

# ruff's default rules (E4, E7, E9, F) plus bug, comprehension and performance
# rules. Cosmetic pycodestyle rules (E501 line length, W2xx whitespace) are
# deliberately excluded - they teach a beginner nothing and crowd out real bugs.
_RUFF_SELECT = "E4,E7,E9,F,B,C4,SIM,PERF"

# ruff no longer has a dedicated syntax-error code; we label our own ast finding.
_SYNTAX_RULE_ID = "E999"

_BANDIT_SEVERITY = {"HIGH": "critical", "MEDIUM": "major", "LOW": "minor"}

# ruff codes that signal a real defect rather than a style preference.
_RUFF_BUG_CODES = {"F821", "F811", "F632", "F702", "E711", "E712", "E713", "E714", "E722"}


# -- Teaching explanations -------------------------------------------

# rule_id -> (why_it_matters, concept). Anything not listed falls back to the
# tool's own message plus a category-level concept.
_EXPLANATIONS: dict[str, tuple[str, str]] = {
    # ruff - bugs
    "B006": (
        "A list or dict used as a default argument is created once, when the function is "
        "defined - not on every call. Changes to it leak into later calls, so the function "
        "quietly remembers data from previous callers. Default to None and build the real "
        "value inside the function.",
        "Mutable default arguments",
    ),
    "B008": (
        "A function call in a default argument runs once at definition time, so every call "
        "reuses that first result. A default of datetime.now() freezes the time the module "
        "was imported.",
        "Evaluation time of default arguments",
    ),
    "B007": (
        "A loop variable that is never used usually means the loop body was meant to use it. "
        "Rename it to _ if it is genuinely unused, so the intent is obvious.",
        "Loop variables and intent",
    ),
    "B011": (
        "assert False is removed when Python runs with -O, so the check silently disappears "
        "in optimised builds. Raise AssertionError explicitly instead.",
        "Assertions are not a control-flow tool",
    ),
    "B023": (
        "A function defined inside a loop closes over the variable, not its value, so every "
        "function ends up seeing the final iteration's value. Bind it with a default argument.",
        "Closures and late binding",
    ),
    "B904": (
        "Raising inside an except block without from hides the original error, losing the "
        "traceback that explains what actually went wrong. Use raise ... from exc.",
        "Exception chaining",
    ),
    "E711": (
        "None is a singleton, so compare with is None rather than == None. Equality can be "
        "overridden by a class and give a surprising answer.",
        "Identity vs equality",
    ),
    "E712": (
        "Comparing to True or False with == is redundant and breaks on truthy values that are "
        "not literally True. Test the value directly.",
        "Truthiness in Python",
    ),
    "E722": (
        "A bare except: catches everything, including KeyboardInterrupt, SystemExit and typos "
        "in your own code. Real failures get swallowed and the program carries on with bad "
        "state. Catch the specific exception you can actually handle.",
        "Targeted exception handling",
    ),
    "E731": (
        "Assigning a lambda to a name gives you a function with no useful name in tracebacks. "
        "Use def - it is the same length and debuggable.",
        "When to use lambda",
    ),
    "E741": (
        "The names l, I and O are nearly indistinguishable from 1 and 0 in most fonts, which "
        "makes review and debugging harder than it needs to be.",
        "Naming for readability",
    ),
    "F401": (
        "An unused import still runs at import time, slows startup and misleads the next "
        "reader into thinking the module is needed. It is also often the leftover of a "
        "half-finished edit.",
        "Keeping imports honest",
    ),
    "F811": (
        "Redefining a name silently discards the first definition, so one of the two is dead "
        "code and the loss is easy to miss in review.",
        "Name shadowing",
    ),
    "F821": (
        "This name is not defined anywhere in scope, so the line raises NameError the moment "
        "it runs. Usually a typo or a missing import.",
        "Python scoping rules",
    ),
    "F841": (
        "A variable that is assigned and never read means the computed value is thrown away - "
        "often a sign the wrong name was used further down.",
        "Dead code",
    ),
    "F632": (
        "is compares identity, not value, so comparing against a literal with is depends on "
        "interpreter internals and can flip between versions. Use ==.",
        "Identity vs equality",
    ),
    "SIM105": (
        "try/except/pass hides which error you expected to ignore. contextlib.suppress names "
        "it, so the intent survives into review.",
        "Expressing intent in error handling",
    ),
    "SIM115": (
        "A file opened without with stays open if an exception is raised before close(), "
        "leaking a file handle and possibly losing buffered writes. with closes it on every "
        "path, including errors.",
        "Context managers and resource cleanup",
    ),
    "SIM117": (
        "Nested with statements can be combined into one, which keeps the cleanup logic for "
        "related resources in a single place.",
        "Context managers",
    ),
    "C401": (
        "Building a set from a generator with set() is slower and noisier than a set "
        "comprehension, which the interpreter can optimise directly.",
        "Comprehensions",
    ),
    "C416": (
        "A comprehension that only copies its input can be replaced with the constructor, "
        "which is both faster and clearer about what it does.",
        "Comprehensions",
    ),
    "PERF401": (
        "Appending to a list inside a loop re-runs the attribute lookup and method call on "
        "every iteration. A list comprehension expresses the same thing and runs faster.",
        "List comprehensions vs loops",
    ),
    "PERF203": (
        "A try/except inside a loop sets up exception handling on every iteration. Moving it "
        "outside the loop, where possible, avoids that repeated cost.",
        "Exception handling cost",
    ),
    # bandit - security
    "B101": (
        "assert is stripped out when Python runs with -O, so an assert used as a security or "
        "validation check silently disappears in production. Raise a real exception instead.",
        "Assertions are not validation",
    ),
    "B104": (
        "Binding to 0.0.0.0 exposes the service on every network interface, including public "
        "ones. Bind to 127.0.0.1 unless you genuinely intend to be reachable from outside.",
        "Network interface binding",
    ),
    "B105": (
        "A password or secret written into source code ends up in git history, in every clone "
        "and in every build artifact - rotating it later does not remove it. Read secrets from "
        "environment variables.",
        "Secret management",
    ),
    "B106": (
        "A secret passed as a hardcoded argument is still a secret committed to the "
        "repository. Load it from the environment at call time.",
        "Secret management",
    ),
    "B107": (
        "A hardcoded default password is the one every deployment forgets to change, which "
        "makes it the first thing an attacker tries.",
        "Secret management",
    ),
    "B108": (
        "A hardcoded path under /tmp is world-writable and predictable, so another process can "
        "pre-create or swap the file between your check and your write. Use tempfile, which "
        "creates the file securely.",
        "Insecure temporary files",
    ),
    "B110": (
        "try/except/pass on a broad exception discards the error entirely, so a real failure "
        "looks exactly like success and the bug surfaces much later, somewhere else.",
        "Silent failure",
    ),
    "B112": (
        "try/except/continue swallows the error and moves to the next iteration, so a loop can "
        "quietly process nothing at all and still report success.",
        "Silent failure",
    ),
    "B301": (
        "pickle executes arbitrary code while loading, so unpickling data you did not create "
        "is equivalent to running a stranger's script. Use JSON for untrusted input.",
        "Deserialisation attacks",
    ),
    "B307": (
        "eval runs whatever string it is given, so any user-controlled part of that string is "
        "code execution. Use ast.literal_eval for data, or an explicit parser.",
        "Code injection",
    ),
    "B311": (
        "The random module is predictable by design and must not be used for tokens, passwords "
        "or anything an attacker could try to guess. Use the secrets module.",
        "Cryptographically secure randomness",
    ),
    "B324": (
        "MD5 and SHA1 are broken for security purposes - collisions are cheap to produce. Use "
        "SHA-256, or pass usedforsecurity=False if the hash is only a cache key.",
        "Choosing a hash function",
    ),
    "B501": (
        "Disabling TLS certificate verification removes the only check that you are talking to "
        "the real server, which makes a man-in-the-middle attack trivial.",
        "TLS certificate verification",
    ),
    "B602": (
        "subprocess with shell=True passes the command through the shell, so any user-supplied "
        "text can inject extra commands with ; or |. Pass a list of arguments instead.",
        "Shell injection",
    ),
    "B603": (
        "Launching a subprocess with user-influenced arguments can run unintended programs. "
        "Validate the input and never build the command from raw user text.",
        "Command injection",
    ),
    "B605": (
        "os.system hands the whole string to the shell, so any user-controlled part of it can "
        "run arbitrary commands. Use subprocess with an argument list.",
        "Shell injection",
    ),
    "B608": (
        "Building SQL by concatenating or formatting strings lets user input change the query "
        "itself - the classic SQL injection. Use parameterised queries (placeholders plus a "
        "values tuple) so the database treats input strictly as data.",
        "SQL injection and parameterised queries",
    ),
}

# Used when a rule has no curated explanation above.
_FALLBACK_CONCEPTS = {
    "security": "Secure coding basics",
    "bug": "Reading static analysis output",
    "performance": "Writing efficient Python",
    "readability": "Writing readable Python",
    "style": "Python style conventions",
}


# -- Classification --------------------------------------------------

def _ruff_category(code: str) -> str:
    """Map a ruff rule code to a Finding category."""
    if code in _RUFF_BUG_CODES:
        return "bug"
    if code.startswith(("B0", "B9", "E9")):
        return "bug"
    if code.startswith(("C4", "PERF")):
        return "performance"
    if code.startswith(("SIM", "F4", "F8")):
        return "readability"
    return "style"


def _ruff_severity(category: str) -> str:
    """Security and bug rules are major; everything else is minor."""
    return "major" if category in ("security", "bug") else "minor"


def _explain(rule_id: str, message: str, category: str) -> tuple[str, str]:
    """Return (why_it_matters, concept) for a rule, falling back to its message."""
    if rule_id in _EXPLANATIONS:
        return _EXPLANATIONS[rule_id]
    detail = message.strip().rstrip(".")
    why = (
        f"{detail}. Static analysis flags this pattern as a likely source of bugs or "
        f"confusion; look up rule {rule_id} to see the reasoning behind it."
    )
    return why, _FALLBACK_CONCEPTS[category]


# -- Tool execution --------------------------------------------------

def _run_tool(argv: list[str], label: str) -> object | None:
    """Run a static-analysis tool and return its parsed JSON output, or None.

    A non-zero exit code is not a failure signal: both ruff and bandit exit 1
    when they simply have findings. Missing or unparseable stdout is the real
    failure, and it is logged and skipped so the other tool still runs.
    """
    try:
        proc = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            timeout=_TIMEOUT_SECONDS,
            check=False,
        )
    except (subprocess.TimeoutExpired, OSError) as exc:
        log.warning("%s did not run: %s", label, exc)
        return None

    if not proc.stdout.strip():
        log.warning(
            "%s produced no output (exit %s): %s",
            label,
            proc.returncode,
            proc.stderr.strip()[:200],
        )
        return None

    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        log.warning("%s produced invalid JSON: %s", label, exc)
        return None


def _ruff_findings(target: Path) -> list[Finding]:
    """Run ruff over the target file and map its JSON output to Findings."""
    payload = _run_tool(
        [
            sys.executable,
            "-I",                      # isolated: no PYTHONPATH, no cwd on sys.path
            "-m",
            "ruff",
            "check",
            "--isolated",              # ignore any pyproject.toml near the temp file
            "--no-cache",
            f"--select={_RUFF_SELECT}",
            "--output-format=json",
            str(target),
        ],
        "ruff",
    )
    if not isinstance(payload, list):
        return []

    findings: list[Finding] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        code = item.get("code")
        # ruff reports syntax errors with code=None; ast.parse already produced
        # a finding for those, so skip them rather than report the same thing twice.
        if not code:
            continue
        line = (item.get("location") or {}).get("row")
        if not isinstance(line, int):
            continue

        message = item.get("message") or code
        category = _ruff_category(code)
        why, concept = _explain(code, message, category)
        findings.append(
            Finding(
                id="",                 # real ids are assigned after filtering
                line=line,
                severity=_ruff_severity(category),
                category=category,
                source="rule",
                title=message,
                why_it_matters=why,
                concept=concept,
                rule_id=code,
            )
        )
    return findings


def _bandit_findings(target: Path) -> list[Finding]:
    """Run bandit over the target file and map its JSON output to Findings."""
    payload = _run_tool(
        [sys.executable, "-I", "-m", "bandit", "-f", "json", "-q", str(target)],
        "bandit",
    )
    if not isinstance(payload, dict):
        return []

    findings: list[Finding] = []
    for item in payload.get("results") or []:
        if not isinstance(item, dict):
            continue
        line = item.get("line_number")
        code = item.get("test_id")
        if not isinstance(line, int) or not code:
            continue

        message = (item.get("issue_text") or code).strip()
        why, concept = _explain(code, message, "security")
        findings.append(
            Finding(
                id="",
                line=line,
                severity=_BANDIT_SEVERITY.get(item.get("issue_severity", ""), "major"),
                category="security",
                source="rule",
                title=message,
                why_it_matters=why,
                concept=concept,
                rule_id=code,
            )
        )
    return findings


def _syntax_finding(code: str, total_lines: int) -> Finding | None:
    """Return a critical Finding if the code does not parse, else None."""
    try:
        ast.parse(code)
        return None
    except SyntaxError as exc:
        # "unexpected EOF" can point one line past the end of the snippet.
        line = min(max(exc.lineno or 1, 1), max(total_lines, 1))
        detail = (exc.msg or "invalid syntax").strip()
    except ValueError as exc:
        # e.g. source containing null bytes, which SyntaxError does not cover.
        line = 1
        detail = str(exc)

    return Finding(
        id="",
        line=line,
        severity="critical",
        category="bug",
        source="rule",
        title=f"Syntax error: {detail}",
        why_it_matters=(
            "Python cannot parse this code, so it will not run at all and no other check "
            "can see past the error. If you pasted part of a diff, this may just be a "
            "fragment rather than a real mistake - otherwise look for an unclosed bracket, "
            "a missing colon or a bad indent at or just before this line."
        ),
        concept="Reading Python syntax errors",
        rule_id=_SYNTAX_RULE_ID,
    )


# -- Entry point -----------------------------------------------------

def run_rules(code: str, changed_lines: set[int]) -> list[Finding]:
    """Run ast, ruff and bandit over `code`; keep findings on changed lines.

    The code is never executed - only parsed and linted. Returned findings are
    sorted by line and given ids r1..rN.
    """
    total_lines = len(code.splitlines())
    findings: list[Finding] = []

    syntax = _syntax_finding(code, total_lines)
    if syntax is not None:
        findings.append(syntax)

    with tempfile.TemporaryDirectory(prefix="pr_mentor_") as tmpdir:
        target = Path(tmpdir) / _TARGET_FILENAME
        target.write_text(code, encoding="utf-8")
        findings.extend(_ruff_findings(target))
        findings.extend(_bandit_findings(target))

    kept = [f for f in findings if 1 <= f.line <= total_lines and f.line in changed_lines]
    kept.sort(key=lambda f: (f.line, f.rule_id or ""))
    for number, finding in enumerate(kept, start=1):
        finding.id = f"r{number}"
    return kept
