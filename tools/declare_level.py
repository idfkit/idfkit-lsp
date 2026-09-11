"""Move one library's declared level in ``levels.json`` to what a manifest or lockfile now states.

Run by the two bump workflows after the pin has moved, so that the declaration moves in the same
change as the thing it declares.

WHY THE LEVEL IS READ BACK FROM THE FILE AND NOT TAKEN FROM THE RELEASE. Every idfkit bump from
1.0.0rc1 to 1.0.0rc4 failed here (idfkit/idfkit-lsp#17). The workflow wrote the release tag's
spelling, ``1.0.0-rc.4``, into ``levels.json``, while ``uv`` wrote the PEP 440 spelling,
``1.0.0rc4``, into ``server/pyproject.toml`` and ``server/uv.lock``. ``check_levels`` compares the
three as strings, correctly, because a declaration is a claim about what a file says. So the one
source for the declared level is the file the check will hold it against: whatever spelling the tool
that wrote the pin chose is the spelling declared, and the two can never disagree about a release
they agree on. A failed bump opens no pull request and tells nobody, which is how four release
candidates passed this repository by.
"""

from __future__ import annotations

import json
import sys
from typing import TYPE_CHECKING

from ._common import repository_root
from .check_levels import _statement

if TYPE_CHECKING:
    from pathlib import Path


def declare(root: Path, library: str, rel_path: str) -> str:
    """Set *library*'s level in ``levels.json`` to what *rel_path* states, and return that level."""
    statement = _statement(root, rel_path, library)
    if statement.level is None:
        raise ValueError(f"{rel_path}: {statement.problem}")
    path = root / "levels.json"
    declaration = json.loads(path.read_text(encoding="utf-8"))
    matched = [entry for entry in declaration["libraries"] if entry["name"] == library]
    if not matched:
        raise ValueError(f"levels.json declares no library named {library!r}")
    for entry in matched:
        entry["level"] = statement.level
        entry["current"] = statement.level
        entry["standing"] = "current"
        entry.pop("reason", None)
        entry.pop("tracked", None)
    path.write_text(json.dumps(declaration, indent=2) + "\n", encoding="utf-8")
    return statement.level


def main() -> int:
    if len(sys.argv) != 3:
        print(
            "usage: python -m tools.declare_level <library> <file that states its level>",
            file=sys.stderr,
        )
        return 2
    library, rel_path = sys.argv[1], sys.argv[2]
    try:
        level = declare(repository_root(), library, rel_path)
    except ValueError as error:
        print(f"declare_level: {error}", file=sys.stderr)
        return 1
    print(f"levels.json: {library} declared at {level}, as {rel_path} states it")
    return 0


if __name__ == "__main__":
    sys.exit(main())
