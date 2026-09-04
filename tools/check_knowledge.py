"""Reject the three shapes Constitution Principle I forbids, before review rather than during it.

The contribution this guards against is a helpful one: a dictionary of field names is small,
correct on the day it lands, and silently wrong on every library release after it. A reviewer's
attention is the thing least likely to be there, so FR-025 puts a machine in front of it.

Three shapes are recognised, and only three:

1. a collection of string literals shaped like object types or field names,
2. a pattern literal applied to model text,
3. arithmetic deriving an element from a text offset.

This is a shape check, not a knowledge check. It cannot recognise knowledge in general and it does
not try to; research.md R9 is explicit about that, and about why the suppression path exists. A
false positive costs one sentence: `# check-knowledge: allow <reason>` on the line or the line
above. The reason is required so that suppressions stay countable, and the count is printed on
success so nobody has to grep for them.

Two exemptions, both by name:

- ``model-server/src/positions.ts`` is exempt from all three shapes. It is the single declared
  exception recorded in the Complexity Tracking table of plan.md: the protocol demands positions in
  a unit the language service does not speak, so the conversion is on this side by construction.
- a suppression comment carrying a reason suppresses the one finding on its line.
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING

from ._common import Report, repository_root

if TYPE_CHECKING:
    from pathlib import Path

# The trees this check owns. Everything else in the repository is tooling, tests, or declared
# records, none of which an editor ever reads an answer out of.
SCANNED_ROOTS: tuple[str, ...] = ("server/src", "model-server/src", "client/src")

# The single declared exception, named rather than inferred. plan.md Complexity Tracking.
EXEMPT_FILE = "model-server/src/positions.ts"

_SKIP_DIRS = frozenset({"__pycache__", "node_modules", "dist", "out", ".venv", "coverage"})
_PYTHON_SUFFIXES = frozenset({".py", ".pyi"})
_TYPESCRIPT_SUFFIXES = frozenset({".ts", ".tsx", ".mts", ".cts", ".js", ".mjs", ".cjs"})


class Language(Enum):
    """Which comment syntax a file uses, which is all the suppression scanner needs to know."""

    PYTHON = "#"
    TYPESCRIPT = "//"

    @property
    def comment(self) -> str:
        return self.value


class Shape(Enum):
    """The forbidden shapes, plus the one defect in the suppression mechanism itself."""

    LITERAL_TABLE = "a collection of string literals shaped like object types or field names"
    PATTERN_LITERAL = "a pattern literal applied to model text"
    OFFSET_ARITHMETIC = "arithmetic deriving an element from a text offset"
    BARE_SUPPRESSION = "a suppression comment with no reason after `allow`"

    @property
    def description(self) -> str:
        return self.value


@dataclass(frozen=True)
class Finding:
    """One rejected line: where it is, which shape matched, and what matched."""

    path: str
    line: int
    shape: Shape
    detail: str
    language: Language

    def rule(self) -> str:
        if self.shape is Shape.BARE_SUPPRESSION:
            return (
                f"{self.shape.description}. Write the reason after `allow`, on the same line, "
                "so the suppression says why it is there."
            )
        return (
            f"{self.shape.description}: {self.detail}. Read it from the library that owns the "
            f"question, or suppress this one line with "
            f"`{self.language.comment} check-knowledge: allow <reason>` on it or the line above."
        )


@dataclass(frozen=True)
class ScanResult:
    """Everything one pass over a tree learned, so callers decide what to do about it."""

    findings: tuple[Finding, ...]
    suppressions: int
    exempt_present: bool
    unparsable: tuple[str, ...]

    @property
    def ok(self) -> bool:
        return not self.findings and not self.unparsable


# ---------------------------------------------------------------------------
# What a name has to look like
# ---------------------------------------------------------------------------

# An object type: two alphanumeric runs with a colon between them, or title case with spaces.
_OBJECT_TYPE = re.compile(r"[A-Za-z0-9]:[A-Za-z0-9]|^[A-Z][A-Za-z0-9]*(?: [A-Z][A-Za-z0-9]*)+$")

# A schema field name: two or more lowercase words joined by underscores or spaces.
_FIELD_NAME = re.compile(r"^[a-z][a-z0-9]*(?:[_ ][a-z0-9]+)+$")

_MIN_LITERALS = 5


def _looks_like_schema_name(value: str) -> bool:
    return bool(_OBJECT_TYPE.search(value) or _FIELD_NAME.match(value))


def _is_literal_table(values: list[str]) -> bool:
    """A display is a table when it is big enough and mostly made of schema-shaped names."""
    if len(values) < _MIN_LITERALS:
        return False
    shaped = sum(1 for value in values if _looks_like_schema_name(value))
    return shaped * 2 > len(values)


# ---------------------------------------------------------------------------
# What counts as model text
# ---------------------------------------------------------------------------

# Every file in the model server serves model text. Elsewhere a file has to say so: importing
# `idfkit` is not handling model text, and the source server's regexes read first-language source
# lines, which is its job. The word boundaries matter, so `docs.idfkit.com` and `load_epjson` do
# not drag a file into this rule.
_MODEL_TEXT_MARKER = re.compile(
    r"\.idf\b|\.epjson\b|\bepjson\b|\bidf\b|model text|energyplus-idf",
    re.IGNORECASE,
)


def _handles_model_text(relative_path: str, text: str) -> bool:
    if relative_path.startswith("model-server/src/"):
        return True
    return bool(_MODEL_TEXT_MARKER.search(text))


# ---------------------------------------------------------------------------
# Offset arithmetic, scanned the same way in both languages
# ---------------------------------------------------------------------------

_OFFSET_IDENT = re.compile(
    r"\b(offset|offsets|col|cols|column|columns|position|positions"
    r"|index|indexes|indices|cursor|cursors|char|chars)\b"
)

# A separator or terminator, quoted as a one-character literal. Whether a field ends is the
# language service's answer to give, and deriving it here is how a grammar gets rebuilt by hand.
_SEPARATOR_LITERAL = re.compile(r"""(['"`])[,;!]\1""")

# The window standing in for "the same short function": far enough to catch a helper that splits
# the identifier and the separator across a couple of lines, near enough not to pair strangers.
_WINDOW = 4

_ARROWS = re.compile(r"->|=>")


def _scan_offset_arithmetic(
    relative_path: str,
    raw_lines: list[str],
    code_lines: list[str],
    language: Language,
) -> list[Finding]:
    findings: list[Finding] = []
    for number, code in enumerate(code_lines, start=1):
        stripped = _ARROWS.sub("  ", code)
        identifier = _OFFSET_IDENT.search(stripped)
        if not identifier or not re.search(r"[+\-]", stripped):
            continue
        low = max(0, number - 1 - _WINDOW)
        high = min(len(raw_lines), number + _WINDOW)
        separator = None
        for neighbour in raw_lines[low:high]:
            separator = _SEPARATOR_LITERAL.search(neighbour)
            if separator:
                break
        if not separator:
            continue
        findings.append(
            Finding(
                path=relative_path,
                line=number,
                shape=Shape.OFFSET_ARITHMETIC,
                detail=(
                    f"`{identifier.group(0)}` is added to or subtracted from near the literal "
                    f"{separator.group(0)}"
                ),
                language=language,
            )
        )
    return findings


# ---------------------------------------------------------------------------
# Python
# ---------------------------------------------------------------------------

_RE_FUNCTIONS = frozenset(
    # The four the task names, plus the siblings of the same shape. A pattern handed to
    # `finditer` is no less a grammar than one handed to `search`.
    {"compile", "match", "fullmatch", "search", "sub", "subn", "split", "findall", "finditer"}
)

_REGEX_METACHARACTERS = re.compile(r"[\\()\[\]{}*+?|^$]")
_MIN_METACHARACTERS = 2


class _PythonVisitor(ast.NodeVisitor):
    """One pass for the two shapes an AST answers better than a line scan."""

    def __init__(self, relative_path: str, model_text: bool) -> None:
        self.relative_path = relative_path
        self.model_text = model_text
        self.findings: list[Finding] = []

    def _record(self, line: int, shape: Shape, detail: str) -> None:
        self.findings.append(
            Finding(
                path=self.relative_path,
                line=line,
                shape=shape,
                detail=detail,
                language=Language.PYTHON,
            )
        )

    def _check_display(self, node: ast.AST, values: list[str]) -> None:
        if _is_literal_table(values):
            shown = ", ".join(repr(value) for value in values[:3])
            self._record(
                getattr(node, "lineno", 1),
                Shape.LITERAL_TABLE,
                f"{len(values)} string literals including {shown}",
            )

    @staticmethod
    def _strings(nodes: list[ast.expr]) -> list[str]:
        return [n.value for n in nodes if isinstance(n, ast.Constant) and isinstance(n.value, str)]

    def visit_List(self, node: ast.List) -> None:
        self._check_display(node, self._strings(node.elts))
        self.generic_visit(node)

    def visit_Tuple(self, node: ast.Tuple) -> None:
        self._check_display(node, self._strings(node.elts))
        self.generic_visit(node)

    def visit_Set(self, node: ast.Set) -> None:
        self._check_display(node, self._strings(node.elts))
        self.generic_visit(node)

    def visit_Dict(self, node: ast.Dict) -> None:
        keys = [key for key in node.keys if key is not None]
        self._check_display(node, self._strings(keys))
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        if self.model_text and isinstance(node.func, ast.Attribute):
            owner = node.func.value
            if isinstance(owner, ast.Name) and owner.id == "re":
                if node.func.attr in _RE_FUNCTIONS:
                    self._record(
                        node.lineno,
                        Shape.PATTERN_LITERAL,
                        f"`re.{node.func.attr}` in a module that handles model text",
                    )
        self.generic_visit(node)

    def visit_Assign(self, node: ast.Assign) -> None:
        self._check_pattern_constant(node.value)
        self.generic_visit(node)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        if node.value is not None:
            self._check_pattern_constant(node.value)
        self.generic_visit(node)

    def _check_pattern_constant(self, value: ast.expr) -> None:
        if not self.model_text:
            return
        if not isinstance(value, ast.Constant) or not isinstance(value.value, str):
            return
        if len(_REGEX_METACHARACTERS.findall(value.value)) < _MIN_METACHARACTERS:
            return
        self._record(
            value.lineno,
            Shape.PATTERN_LITERAL,
            "a pattern constant in a module that handles model text",
        )


_PY_COMMENT = re.compile(r"#.*$")


def _scan_python(relative_path: str, text: str) -> tuple[list[Finding], bool]:
    """Return the findings for one Python file, and whether it could be parsed at all."""
    raw_lines = text.splitlines()
    code_lines = [_PY_COMMENT.sub("", line) for line in raw_lines]
    findings = _scan_offset_arithmetic(relative_path, raw_lines, code_lines, Language.PYTHON)
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return findings, False
    visitor = _PythonVisitor(relative_path, _handles_model_text(relative_path, text))
    visitor.visit(tree)
    return findings + visitor.findings, True


# ---------------------------------------------------------------------------
# TypeScript
# ---------------------------------------------------------------------------
#
# This side is a shape scan and not a parse. No TypeScript parser is available to this check, and
# adding one would make the check heavier than the rule it enforces. What follows masks strings and
# comments so that braces, operators, and slashes are read as code, then reasons about the masked
# text. It will miss things a parser would catch, and the reason a suppression is one comment long
# is that it will also occasionally catch something a parser would not.


@dataclass(frozen=True)
class _MaskedSource:
    """The file with strings and comments blanked out, plus the strings that were removed."""

    code: str
    strings: tuple[tuple[int, str], ...]  # (offset of the opening quote, contents)


def _mask_typescript(text: str) -> _MaskedSource:
    out: list[str] = []
    strings: list[tuple[int, str]] = []
    index = 0
    length = len(text)
    while index < length:
        char = text[index]
        if char in "'\"`":
            quote = char
            start = index
            index += 1
            body: list[str] = []
            while index < length:
                if text[index] == "\\" and index + 1 < length:
                    body.append(text[index : index + 2])
                    index += 2
                    continue
                if text[index] == quote:
                    index += 1
                    break
                body.append(text[index])
                index += 1
            removed = "".join(body)
            strings.append((start, removed))
            # Keep newlines so line numbers survive the mask.
            out.append(quote + re.sub(r"[^\n]", " ", removed) + quote)
            continue
        if text.startswith("//", index):
            end = text.find("\n", index)
            end = length if end == -1 else end
            out.append(" " * (end - index))
            index = end
            continue
        if text.startswith("/*", index):
            end = text.find("*/", index + 2)
            end = length if end == -1 else end + 2
            out.append(re.sub(r"[^\n]", " ", text[index:end]))
            index = end
            continue
        out.append(char)
        index += 1
    return _MaskedSource(code="".join(out), strings=tuple(strings))


_OPENS_A_LITERAL = frozenset("=:(,[{")
_RETURN = re.compile(r"\breturn\s*$")


def _opens_a_literal(code: str, position: int) -> bool:
    """True when the bracket at *position* starts data rather than a body.

    A function body, an `if` block, and a class body are all preceded by `)` or an identifier. A
    literal is preceded by an assignment, a call, a key, or another literal.
    """
    before = code[:position].rstrip()
    if not before:
        return True
    return before[-1] in _OPENS_A_LITERAL or bool(_RETURN.search(before))


def _typescript_literal_tables(relative_path: str, masked: _MaskedSource) -> list[Finding]:
    findings: list[Finding] = []
    code = masked.code
    depth = 0
    start = -1
    for position, char in enumerate(code):
        if char in "[{":
            if depth == 0:
                start = position if _opens_a_literal(code, position) else -1
            depth += 1
            continue
        if char in "]}":
            depth = max(0, depth - 1)
            if depth == 0 and start >= 0:
                values = [value for offset, value in masked.strings if start < offset < position]
                if _is_literal_table(values):
                    shown = ", ".join(repr(value) for value in values[:3])
                    findings.append(
                        Finding(
                            path=relative_path,
                            line=code.count("\n", 0, start) + 1,
                            shape=Shape.LITERAL_TABLE,
                            detail=f"{len(values)} string literals including {shown}",
                            language=Language.TYPESCRIPT,
                        )
                    )
                start = -1
    return findings


_NEW_REGEXP = re.compile(r"\bnew\s+RegExp\b")
_BEFORE_A_REGEX = frozenset("=(,:[!&|?{;+")


def _typescript_pattern_literals(relative_path: str, masked: _MaskedSource) -> list[Finding]:
    findings: list[Finding] = []
    for number, line in enumerate(masked.code.splitlines(), start=1):
        if _NEW_REGEXP.search(line):
            findings.append(
                Finding(
                    path=relative_path,
                    line=number,
                    shape=Shape.PATTERN_LITERAL,
                    detail="`new RegExp` over model text",
                    language=Language.TYPESCRIPT,
                )
            )
            continue
        for position, char in enumerate(line):
            if char != "/":
                continue
            before = line[:position].rstrip()
            opens = not before or before[-1] in _BEFORE_A_REGEX or bool(_RETURN.search(before))
            if opens and "/" in line[position + 1 :]:
                findings.append(
                    Finding(
                        path=relative_path,
                        line=number,
                        shape=Shape.PATTERN_LITERAL,
                        detail="a regular expression literal over model text",
                        language=Language.TYPESCRIPT,
                    )
                )
                break
    return findings


def _scan_typescript(relative_path: str, text: str) -> list[Finding]:
    masked = _mask_typescript(text)
    raw_lines = text.splitlines()
    code_lines = masked.code.splitlines()
    findings = _scan_offset_arithmetic(relative_path, raw_lines, code_lines, Language.TYPESCRIPT)
    findings += _typescript_literal_tables(relative_path, masked)
    if _handles_model_text(relative_path, text):
        findings += _typescript_pattern_literals(relative_path, masked)
    return findings


# ---------------------------------------------------------------------------
# Suppressions
# ---------------------------------------------------------------------------


def _suppression_pattern(language: Language) -> re.Pattern[str]:
    return re.compile(
        rf"{re.escape(language.comment)}\s*check-knowledge:\s*allow\b(?P<reason>.*)$"
    )


@dataclass(frozen=True)
class _Suppressions:
    """Which lines carry a usable suppression, and which carry one that says nothing."""

    lines: frozenset[int]
    bare: tuple[int, ...]


def _read_suppressions(text: str, language: Language) -> _Suppressions:
    pattern = _suppression_pattern(language)
    usable: set[int] = set()
    bare: list[int] = []
    for number, line in enumerate(text.splitlines(), start=1):
        match = pattern.search(line)
        if not match:
            continue
        if match.group("reason").strip():
            usable.add(number)
        else:
            bare.append(number)
    return _Suppressions(lines=frozenset(usable), bare=tuple(bare))


def _is_suppressed(finding: Finding, suppressions: _Suppressions) -> bool:
    """A suppression sits on the offending line or the line directly above it."""
    return finding.line in suppressions.lines or finding.line - 1 in suppressions.lines


# ---------------------------------------------------------------------------
# The scan
# ---------------------------------------------------------------------------


def _language_of(path: Path) -> Language | None:
    if path.suffix in _PYTHON_SUFFIXES:
        return Language.PYTHON
    if path.suffix in _TYPESCRIPT_SUFFIXES and not path.name.endswith(".d.ts"):
        return Language.TYPESCRIPT
    return None


def _files(root: Path) -> list[tuple[Path, str, Language]]:
    found: list[tuple[Path, str, Language]] = []
    for scanned in SCANNED_ROOTS:
        base = root / scanned
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*")):
            if not path.is_file():
                continue
            if _SKIP_DIRS.intersection(path.relative_to(root).parts):
                continue
            language = _language_of(path)
            if language is None:
                continue
            found.append((path, path.relative_to(root).as_posix(), language))
    return found


def scan(root: Path) -> ScanResult:
    """Scan the three trees under *root* for the shapes Principle I forbids."""
    findings: list[Finding] = []
    unparsable: list[str] = []
    suppression_count = 0
    for path, relative, language in _files(root):
        text = path.read_text(encoding="utf-8", errors="replace")
        suppressions = _read_suppressions(text, language)
        suppression_count += len(suppressions.lines)

        shaped: list[Finding] = []
        if relative != EXEMPT_FILE:
            if language is Language.PYTHON:
                shaped, parsed = _scan_python(relative, text)
                if not parsed:
                    unparsable.append(relative)
            else:
                shaped = _scan_typescript(relative, text)

        for line in suppressions.bare:
            shaped.append(
                Finding(
                    path=relative,
                    line=line,
                    shape=Shape.BARE_SUPPRESSION,
                    detail="no reason follows `allow`",
                    language=language,
                )
            )

        seen: set[tuple[int, Shape]] = set()
        for finding in shaped:
            key = (finding.line, finding.shape)
            if key in seen:
                continue
            seen.add(key)
            if finding.shape is not Shape.BARE_SUPPRESSION and _is_suppressed(
                finding, suppressions
            ):
                continue
            findings.append(finding)

    findings.sort(key=lambda f: (f.path, f.line, f.shape.name))
    return ScanResult(
        findings=tuple(findings),
        suppressions=suppression_count,
        exempt_present=(root / EXEMPT_FILE).is_file(),
        unparsable=tuple(unparsable),
    )


def main() -> int:
    root = repository_root()
    result = scan(root)

    report = Report(check="check-knowledge")
    for relative in result.unparsable:
        report.fail(relative, "cannot be parsed, so this check cannot vouch for it")
    for finding in result.findings:
        report.fail(f"{finding.path}:{finding.line}", finding.rule())

    status = report.finish()
    if status == 0:
        print(f"  suppressions in force: {result.suppressions}")
    else:
        print(
            f"  {EXEMPT_FILE} is the single declared exception (plan.md Complexity Tracking) "
            "and is exempt from all three shapes.",
        )
        print(
            "  Any other line may be suppressed once, with a reason, by "
            "`# check-knowledge: allow <reason>` or `// check-knowledge: allow <reason>`.",
        )
    if not result.exempt_present:
        print(f"  note: {EXEMPT_FILE} does not exist yet; the exemption is not in use.")
    return status


if __name__ == "__main__":
    raise SystemExit(main())
