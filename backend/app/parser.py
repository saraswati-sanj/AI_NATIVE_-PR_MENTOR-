"""Diff / snippet detection and parsing.

Detects whether input is a unified diff or plain code snippet,
extracts the reconstructed new code, and tracks which lines were changed.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass

from unidiff import PatchSet, UnidiffParseError

# unidiff line type for "\ No newline at end of file" markers
_NO_NEWLINE_MARKER = "\\"


@dataclass
class ParseResult:
    code: str
    changed_lines: set[int]       # 1-based line numbers in rebuilt code
    is_partial: bool
    line_map: dict[int, int]      # rebuilt line number → real new-file line number


def _is_diff(text: str) -> bool:
    """Detect unified diff by 'diff --git' header or @@ hunk markers."""
    if "diff --git" in text:
        return True
    return any(line.startswith("@@") for line in text.splitlines())


def _check_partial(code: str) -> bool:
    """True if code is not parseable as complete, valid Python."""
    try:
        ast.parse(code)
        return False
    except SyntaxError:
        return True


def _parse_diff(text: str) -> ParseResult:
    """Parse unified diff: rebuild new-side code from added + context lines.

    changed_lines contains 1-based positions in the rebuilt code.
    line_map maps each rebuilt position to its real line in the new file.
    Raises ValueError if the diff touches more than one file.
    """
    patch = PatchSet(text)

    if len(patch) > 1:
        raise ValueError("Please review one file per diff.")

    code_lines: list[str] = []
    changed_lines: set[int] = set()
    line_map: dict[int, int] = {}

    for patched_file in patch:
        for hunk in patched_file:
            for line in hunk:
                # Skip removed lines and "no newline at end of file" markers
                if line.is_removed or line.line_type == _NO_NEWLINE_MARKER:
                    continue
                if line.is_added or line.is_context:
                    code_lines.append(line.value.rstrip("\n"))
                    rebuilt_num = len(code_lines)
                    line_map[rebuilt_num] = line.target_line_no
                    if line.is_added:
                        changed_lines.add(rebuilt_num)

    code = "\n".join(code_lines)
    return ParseResult(
        code=code,
        changed_lines=changed_lines,
        is_partial=_check_partial(code),
        line_map=line_map,
    )


def _parse_snippet(text: str) -> ParseResult:
    """Plain code snippet: every line is treated as changed, line_map is identity."""
    lines = text.splitlines()
    changed_lines = set(range(1, len(lines) + 1))
    line_map = {i: i for i in range(1, len(lines) + 1)}
    return ParseResult(
        code=text,
        changed_lines=changed_lines,
        is_partial=_check_partial(text),
        line_map=line_map,
    )


def parse_input(text: str, mode: str = "auto") -> ParseResult:
    """Main entry point — detect input type and parse accordingly.

    Falls back to snippet parsing if the diff cannot be parsed by unidiff.
    Raises ValueError for multi-file diffs.
    """
    use_diff = mode == "diff" or (mode == "auto" and _is_diff(text))

    if use_diff:
        try:
            return _parse_diff(text)
        except ValueError:
            raise  # Multi-file error must propagate
        except (UnidiffParseError, Exception):
            # Malformed diff that looks like one but isn't → treat as snippet
            return _parse_snippet(text)

    return _parse_snippet(text)
