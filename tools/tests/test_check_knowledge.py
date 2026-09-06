"""The knowledge check is only worth having if it actually rejects the three shapes.

Each fixture below is the smallest file that carries one forbidden shape, written the way a helpful
contributor would write it: correct, small, and convenient. The clean files are the control, because
a check that rejects everything is as useless as one that rejects nothing.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from ..check_knowledge import EXEMPT_FILE, Shape, scan

if TYPE_CHECKING:
    from pathlib import Path

LITERAL_TABLE_PY = '''"""Field names, written down once and wrong on the next release."""

FIELDS = [
    "zone_name",
    "x_origin",
    "y_origin",
    "ceiling_height",
    "floor_area",
]
'''

PATTERN_LITERAL_PY = '''"""Read a field out of the model text."""

import re


def first_field(text: str) -> str | None:
    match = re.search(r"^\\s*([\\w:]+),", text)
    return match.group(1) if match else None
'''

OFFSET_ARITHMETIC_PY = '''"""Work out which field of the model text an offset falls in."""


def field_index(text: str, offset: int) -> int:
    return text.count(",", 0, offset - 1) + 1
'''

CLEAN_PY = '''"""Ask the library, and return nothing when it declines to answer."""

from __future__ import annotations

from typing import Any


def describe(library: Any, name: str) -> Any:
    described = library.describe(name)
    if described is None:
        return None
    return described.fields
'''

LITERAL_TABLE_TS = """export const OBJECT_TYPES = [
  'BuildingSurface:Detailed',
  'Schedule:Constant',
  'ScheduleTypeLimits',
  'Zone:Air:Balance',
  'Output:Variable',
  'Material:NoMass',
];
"""

CLEAN_TS = """import { createConnection } from 'vscode-languageserver/node.js';

export function start(): void {
  const connection = createConnection();
  connection.listen();
}
"""

EXEMPT_TS = """// The single declared exception: a service offset becomes a protocol position here.
export function columnFor(text: string, offset: number): number {
  const start = text.lastIndexOf(",", offset - 1) + 1;
  return offset - start;
}
"""

SUPPRESSED_TS = """export function shift(cursor: number, text: string): number {
  // check-knowledge: allow this counts protocol frame bytes, not model fields
  return cursor + text.indexOf(";");
}
"""

BARE_SUPPRESSION_TS = """export function shift(cursor: number, text: string): number {
  // check-knowledge: allow
  return cursor + text.indexOf(";");
}
"""

TREE: dict[str, str] = {
    "server/src/tables.py": LITERAL_TABLE_PY,
    "server/src/patterns.py": PATTERN_LITERAL_PY,
    "server/src/offsets.py": OFFSET_ARITHMETIC_PY,
    "server/src/clean.py": CLEAN_PY,
    "client/src/tables.ts": LITERAL_TABLE_TS,
    "client/src/clean.ts": CLEAN_TS,
    "model-server/src/positions.ts": EXEMPT_TS,
    "model-server/src/suppressed.ts": SUPPRESSED_TS,
    "model-server/src/bare.ts": BARE_SUPPRESSION_TS,
}


def write_tree(root: Path, files: dict[str, str]) -> Path:
    for relative, text in files.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return root


@pytest.fixture
def tree(tmp_path: Path) -> Path:
    return write_tree(tmp_path, TREE)


def shapes_at(root: Path, relative: str) -> set[Shape]:
    return {f.shape for f in scan(root).findings if f.path == relative}


class TestForbiddenShapes:
    def test_literal_table_is_rejected(self, tree: Path) -> None:
        assert Shape.LITERAL_TABLE in shapes_at(tree, "server/src/tables.py")

    def test_pattern_over_model_text_is_rejected(self, tree: Path) -> None:
        assert Shape.PATTERN_LITERAL in shapes_at(tree, "server/src/patterns.py")

    def test_offset_arithmetic_is_rejected(self, tree: Path) -> None:
        assert Shape.OFFSET_ARITHMETIC in shapes_at(tree, "server/src/offsets.py")

    def test_typescript_literal_table_is_rejected(self, tree: Path) -> None:
        assert Shape.LITERAL_TABLE in shapes_at(tree, "client/src/tables.ts")

    def test_clean_python_is_not_rejected(self, tree: Path) -> None:
        assert shapes_at(tree, "server/src/clean.py") == set()

    def test_clean_typescript_is_not_rejected(self, tree: Path) -> None:
        assert shapes_at(tree, "client/src/clean.ts") == set()

    def test_a_pattern_outside_model_text_is_left_alone(self, tmp_path: Path) -> None:
        """The source server matches first-language source lines, which is its job, not a grammar."""
        source = '''"""Completion context detection for library call sites."""

import re


def call_target(line: str) -> str | None:
    match = re.search(r"(\\w+)\\.add\\(", line)
    return match.group(1) if match else None
'''
        root = write_tree(tmp_path, {"server/src/completion.py": source})
        assert shapes_at(root, "server/src/completion.py") == set()


class TestTheDeclaredException:
    def test_positions_is_exempt_from_all_three(self, tree: Path) -> None:
        assert shapes_at(tree, EXEMPT_FILE) == set()

    def test_the_exception_is_reported_as_present(self, tree: Path) -> None:
        assert scan(tree).exempt_present is True

    def test_the_check_still_runs_when_the_exception_is_absent(self, tmp_path: Path) -> None:
        root = write_tree(tmp_path, {"server/src/tables.py": LITERAL_TABLE_PY})
        result = scan(root)
        assert result.exempt_present is False
        assert Shape.LITERAL_TABLE in {f.shape for f in result.findings}


class TestSuppression:
    def test_a_suppression_with_a_reason_passes(self, tree: Path) -> None:
        assert shapes_at(tree, "model-server/src/suppressed.ts") == set()

    def test_a_suppression_without_a_reason_fails(self, tree: Path) -> None:
        found = shapes_at(tree, "model-server/src/bare.ts")
        assert Shape.BARE_SUPPRESSION in found

    def test_a_suppression_without_a_reason_suppresses_nothing(self, tree: Path) -> None:
        assert Shape.OFFSET_ARITHMETIC in shapes_at(tree, "model-server/src/bare.ts")

    def test_only_reasoned_suppressions_are_counted(self, tree: Path) -> None:
        assert scan(tree).suppressions == 1

    def test_a_python_suppression_carries_its_reason(self, tmp_path: Path) -> None:
        source = '''"""Work out which field an offset falls in."""


def field_index(text: str, offset: int) -> int:
    # check-knowledge: allow the protocol frame is not model text
    return text.count(",", 0, offset - 1) + 1
'''
        root = write_tree(tmp_path, {"server/src/offsets.py": source})
        assert shapes_at(root, "server/src/offsets.py") == set()


class TestFailureOutput:
    def test_a_failure_names_the_file_the_line_the_shape_and_the_way_out(self, tree: Path) -> None:
        finding = next(f for f in scan(tree).findings if f.path == "server/src/tables.py")
        assert finding.line > 0
        rule = finding.rule()
        assert Shape.LITERAL_TABLE.description in rule
        assert "check-knowledge: allow <reason>" in rule

    def test_a_bare_suppression_says_what_is_missing(self, tree: Path) -> None:
        finding = next(f for f in scan(tree).findings if f.shape is Shape.BARE_SUPPRESSION)
        assert "reason" in finding.rule()
