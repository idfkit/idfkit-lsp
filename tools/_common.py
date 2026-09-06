"""Shared plumbing for the repository's checks.

Every check in this directory reads a declared record, compares it against the repository as it
actually stands, and fails loudly naming both the offending file and the rule broken. This module
holds the three pieces all of them need and nothing else: where the repository root is, how a
declared record is read, and how a failure is reported.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


def repository_root() -> Path:
    """The directory holding the declared records, found by walking up from this file.

    Resolved from the file rather than from the working directory, so a check behaves the same
    whether it is run from the root, from ``server/``, or by a pre-commit hook.
    """
    here = Path(__file__).resolve()
    for candidate in here.parents:
        if (candidate / "capabilities.json").is_file() or (candidate / ".git").exists():
            return candidate
    raise RuntimeError(f"no repository root above {here}")


def read_json(path: Path) -> Any:
    """Read a declared record, failing loudly on anything malformed.

    A declared record that cannot be parsed is not a warning. Every check reads one, and a check
    that quietly treats an unreadable record as an empty one is a check that passes when it should
    be the loudest thing in the run.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        raise SystemExit(f"{path}: declared record is missing") from None
    except OSError as exc:
        raise SystemExit(f"{path}: cannot be read: {exc}") from None
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise SystemExit(
            f"{path}: not valid JSON: line {exc.lineno}, column {exc.colno}: {exc.msg}"
        ) from None


@dataclass
class Report:
    """Collected failures for one check, each naming a file and the rule it broke."""

    check: str
    failures: list[str] = field(default_factory=list)

    def fail(self, path: Path | str, rule: str) -> None:
        """Record one failure. ``path`` is the offending file, ``rule`` is what it broke."""
        shown: Path | str = path
        if isinstance(path, Path):
            try:
                shown = path.relative_to(repository_root())
            except ValueError:
                shown = path
        self.failures.append(f"{shown}: {rule}")

    @property
    def ok(self) -> bool:
        return not self.failures

    def finish(self) -> int:
        """Print the outcome and return the process exit status."""
        if self.ok:
            print(f"{self.check}: ok")
            return 0
        print(f"{self.check}: {len(self.failures)} failure(s)", file=sys.stderr)
        for failure in self.failures:
            print(f"  {failure}", file=sys.stderr)
        return 1


def validate_against_schema(
    instance: Any, schema_path: Path, report: Report, source: Path
) -> None:
    """Validate a declared record against its JSON schema, recording every violation."""
    import jsonschema

    schema = read_json(schema_path)
    validator = jsonschema.Draft202012Validator(schema)
    for error in sorted(validator.iter_errors(instance), key=lambda e: list(e.absolute_path)):
        location = "/".join(str(part) for part in error.absolute_path) or "(root)"
        report.fail(source, f"schema violation at {location}: {error.message}")
