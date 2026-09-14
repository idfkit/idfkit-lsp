"""Check ``levels.json`` against the files that actually state each level.

Principle III asks two questions of every library this repository resolves, and this check answers
both. Forward: every path a declaration names must state the level the declaration claims, and two
paths that name the same library must not disagree with each other (FR-012). Backward: every
dependency a manifest declares must appear in ``levels.json``, so a library cannot arrive
undeclared.

Both directions are load-time failures rather than warnings. A consumer running ahead of the level
it declares looks exactly like one running behind it, and the only moment that difference is cheap
to see is the moment the pin moves.

TOML is read with regular expressions rather than ``tomllib``, which is absent on Python 3.10 and
therefore on the floor this repository supports. A conditional import would give the check two
parsing paths, only one of which any given run exercises. One text path, reading two shapes this
repository owns and no others, is the form that is always tested.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from ._common import Report, read_json, repository_root, validate_against_schema

SCHEMA_PATH = Path(__file__).resolve().parent / "schemas" / "levels.schema.json"

_PROJECT_TABLE = re.compile(r"^\[project\]\s*$(?P<body>.*?)(?=^\[|\Z)", re.MULTILINE | re.DOTALL)
_DEPENDENCY_ARRAY = re.compile(r"^dependencies\s*=\s*\[(?P<items>.*?)\]", re.MULTILINE | re.DOTALL)
_QUOTED = re.compile(r"""["']([^"']+)["']""")
_SPECIFIER = re.compile(r"^(?P<name>[A-Za-z0-9._-]+)(?:\[[^\]]*\])?\s*(?P<rest>.*)$")
_LOCK_FIELD = re.compile(r"""^(?P<key>name|version)\s*=\s*["'](?P<value>[^"']+)["']""")
# An exact level is a bare version. Anything carrying a range operator, a wildcard, a union, or a
# tag fails this and is reported as a range rather than silently accepted as a pin.
_EXACT_LEVEL = re.compile(r"[0-9][0-9A-Za-z.+-]*")

_NPM_MANIFEST_SECTIONS = (
    "dependencies",
    "devDependencies",
    "peerDependencies",
    "optionalDependencies",
)


class Standing(str, Enum):
    """How a declared level stands against the current published one."""

    CURRENT = "current"
    BEHIND_DELIBERATE = "behind_deliberate"
    BEHIND_TEMPORARY = "behind_temporary"


@dataclass(frozen=True)
class ResolvedLibrary:
    """One entry of ``levels.json``."""

    name: str
    declared_in: tuple[str, ...]
    level: str
    standing: str
    reason: str | None
    tracked: str | None

    @property
    def lookup_name(self) -> str:
        """The name the manifests actually install under.

        An entry may carry a parenthetical after the name, as the second language's facade
        (``@idfkit/idfkit``) does, so the text before the first space is what a manifest is
        searched for. The parenthetical was added when the facade and the first language's library
        both installed as ``idfkit``; npm refused that name, and it now only describes the entry.
        """
        return self.name.split(" ", 1)[0]


@dataclass(frozen=True)
class Statement:
    """What one declared file actually says about one library.

    Exactly one of ``level`` and ``problem`` is set. ``problem`` covers every way a file can fail
    to state an exact level: the file is missing, the library is not in it, or the value it carries
    is a range.
    """

    path: str
    level: str | None = None
    problem: str | None = None


@dataclass(frozen=True)
class NpmManifest:
    """A manifest read in the backward direction, and the sections that bind this repository.

    ``devDependencies`` are excluded: a formatter or a bundler is a build detail, not a library
    whose level reaches a user of either server.
    """

    path: str
    sections: tuple[str, ...]


_BACKWARD_NPM = (
    NpmManifest("model-server/package.json", ("dependencies", "peerDependencies")),
    NpmManifest("client/package.json", ("dependencies",)),
)


def _normalize(name: str) -> str:
    """PEP 503 name normalisation, so ``uv.lock`` and ``pyproject.toml`` compare as equals."""
    return re.sub(r"[-_.]+", "-", name).lower()


def _pyproject_specifiers(text: str) -> list[str]:
    table = _PROJECT_TABLE.search(text)
    if table is None:
        return []
    array = _DEPENDENCY_ARRAY.search(table.group("body"))
    if array is None:
        return []
    return _QUOTED.findall(array.group("items"))


def _read_pyproject(path: Path, rel_path: str, library: str) -> Statement:
    text = path.read_text(encoding="utf-8")
    wanted = _normalize(library)
    for specifier in _pyproject_specifiers(text):
        parsed = _SPECIFIER.match(specifier.strip())
        if parsed is None or _normalize(parsed.group("name")) != wanted:
            continue
        rest = parsed.group("rest").strip()
        if rest.startswith("==") and _EXACT_LEVEL.fullmatch(rest[2:].strip()):
            return Statement(rel_path, level=rest[2:].strip())
        return Statement(
            rel_path,
            problem=(
                f"declares {library} as {specifier!r}, which is a range rather than an exact "
                f"level; Principle III requires an exact pin"
            ),
        )
    return Statement(rel_path, problem=f"states no level for {library}")


def _read_uv_lock(path: Path, rel_path: str, library: str) -> Statement:
    wanted = _normalize(library)
    name: str | None = None
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip() == "[[package]]":
            name = None
            continue
        field = _LOCK_FIELD.match(line)
        if field is None:
            continue
        if field.group("key") == "name":
            name = field.group("value")
        elif name is not None and _normalize(name) == wanted:
            return Statement(rel_path, level=field.group("value"))
    return Statement(rel_path, problem=f"states no level for {library}")


def _read_package_json(path: Path, rel_path: str, library: str) -> Statement:
    manifest = read_json(path)
    for section in _NPM_MANIFEST_SECTIONS:
        entries = manifest.get(section)
        if not isinstance(entries, dict) or library not in entries:
            continue
        declared = str(entries[library])
        if _EXACT_LEVEL.fullmatch(declared):
            return Statement(rel_path, level=declared)
        return Statement(
            rel_path,
            problem=(
                f"declares {library} as {declared!r} in {section}, which is a range rather than "
                f"an exact level; Principle III requires an exact pin"
            ),
        )
    return Statement(rel_path, problem=f"states no level for {library}")


def _statement(root: Path, rel_path: str, library: str) -> Statement:
    path = root / rel_path
    if not path.is_file():
        return Statement(rel_path, problem="declared as stating a level, but does not exist")
    kind = path.name
    if kind == "pyproject.toml":
        return _read_pyproject(path, rel_path, library)
    if kind == "uv.lock":
        return _read_uv_lock(path, rel_path, library)
    if kind == "package.json":
        return _read_package_json(path, rel_path, library)
    return Statement(rel_path, problem=f"is not a file kind this check can read for {library}")


def _libraries(declaration: object) -> list[ResolvedLibrary]:
    """Read the entries this check can act on, leaving malformed ones to schema validation."""
    if not isinstance(declaration, dict):
        return []
    entries = declaration.get("libraries")
    if not isinstance(entries, list):
        return []
    libraries: list[ResolvedLibrary] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        name = entry.get("name")
        declared_in = entry.get("declared_in")
        level = entry.get("level")
        standing = entry.get("standing")
        if (
            not isinstance(name, str)
            or not isinstance(level, str)
            or not isinstance(standing, str)
        ):
            continue
        if not isinstance(declared_in, list):
            continue
        reason = entry.get("reason")
        tracked = entry.get("tracked")
        libraries.append(
            ResolvedLibrary(
                name=name,
                declared_in=tuple(p for p in declared_in if isinstance(p, str)),
                level=level,
                standing=standing,
                reason=reason if isinstance(reason, str) else None,
                tracked=tracked if isinstance(tracked, str) else None,
            )
        )
    return libraries


def _check_standing(library: ResolvedLibrary, report: Report) -> None:
    """Enforce the standing rules in code as well as in the schema.

    The schema encodes the same two rules, but it is validated separately and a schema anyone can
    loosen is not where a rule of the record should live alone.
    """
    if library.standing != Standing.CURRENT.value and not library.reason:
        report.fail(
            "levels.json",
            f"{library.name}: standing is {library.standing!r} and carries no reason; being "
            f"behind must be a decision on the record",
        )
    if library.standing == Standing.BEHIND_TEMPORARY.value and not library.tracked:
        report.fail(
            "levels.json",
            f"{library.name}: standing is 'behind_temporary' and names no tracked item that "
            f"closes it",
        )


def _check_forward(root: Path, library: ResolvedLibrary, report: Report) -> None:
    """Every declared path must state the declared level, and none may contradict another."""
    stated: list[Statement] = []
    for rel_path in library.declared_in:
        statement = _statement(root, rel_path, library.lookup_name)
        if statement.problem is not None:
            report.fail(statement.path, statement.problem)
            continue
        stated.append(statement)

    for statement in stated:
        if statement.level != library.level:
            report.fail(
                statement.path,
                f"states {library.lookup_name} {statement.level}, but levels.json declares "
                f"{library.level}",
            )

    first = stated[0] if stated else None
    if first is not None:
        for other in stated[1:]:
            if other.level != first.level:
                report.fail(
                    first.path,
                    f"states {library.lookup_name} {first.level} while {other.path} states "
                    f"{other.level}; two declared paths disagree",
                )

    if not stated:
        report.fail(
            "levels.json",
            f"{library.name}: resolves nowhere; no path in declared_in states a level for it",
        )


def _declared_pairs(libraries: list[ResolvedLibrary]) -> set[tuple[str, str]]:
    return {
        (library.lookup_name, rel_path)
        for library in libraries
        for rel_path in library.declared_in
    }


def _check_backward(root: Path, libraries: list[ResolvedLibrary], report: Report) -> None:
    """Every dependency a manifest declares must have an entry that names that manifest."""
    declared = _declared_pairs(libraries)

    pyproject = root / "server" / "pyproject.toml"
    if pyproject.is_file():
        for specifier in _pyproject_specifiers(pyproject.read_text(encoding="utf-8")):
            parsed = _SPECIFIER.match(specifier.strip())
            if parsed is None:
                continue
            name = parsed.group("name")
            if not any(
                _normalize(known) == _normalize(name) and path == "server/pyproject.toml"
                for known, path in declared
            ):
                report.fail(
                    "server/pyproject.toml",
                    f"depends on {name}, which has no entry in levels.json naming this file",
                )

    for npm in _BACKWARD_NPM:
        path = root / npm.path
        if not path.is_file():
            continue
        manifest = read_json(path)
        if not isinstance(manifest, dict):
            continue
        for section in npm.sections:
            entries = manifest.get(section)
            if not isinstance(entries, dict):
                continue
            for name in entries:
                if (name, npm.path) not in declared:
                    report.fail(
                        npm.path,
                        f"declares {name} in {section}, which has no entry in levels.json naming "
                        f"this file",
                    )


def check_levels(root: Path) -> Report:
    """Run every level rule against one repository tree and return what it found."""
    report = Report("check_levels")
    source = root / "levels.json"
    declaration = read_json(source)
    validate_against_schema(declaration, SCHEMA_PATH, report, source)

    libraries = _libraries(declaration)
    for library in libraries:
        _check_standing(library, report)
        _check_forward(root, library, report)
    _check_backward(root, libraries, report)
    return report


def main() -> int:
    return check_levels(repository_root()).finish()


if __name__ == "__main__":
    raise SystemExit(main())
