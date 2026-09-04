"""The level check, exercised against fixture trees rather than against this repository.

Each fixture is a whole small repository: a ``levels.json`` and the manifests it points at. That is
the only way to test the rule that matters, because the failure the check exists to catch is a
disagreement between two files, and a disagreement needs two files to exist.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from ..check_levels import check_levels

if TYPE_CHECKING:
    from pathlib import Path


def _write(root: Path, rel_path: str, text: str) -> None:
    path = root / rel_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _levels(root: Path, *libraries: dict[str, Any]) -> None:
    declaration = {
        "version": 1,
        "register": "the consumer register, named by role rather than by path",
        "libraries": list(libraries),
    }
    _write(root, "levels.json", json.dumps(declaration))


def _pyproject(root: Path, *specifiers: str) -> None:
    rendered = ",\n    ".join(f'"{spec}"' for spec in specifiers)
    _write(
        root,
        "server/pyproject.toml",
        f'[project]\nname = "idfkit-lsp"\ndependencies = [\n    {rendered},\n]\n'
        f'\n[project.optional-dependencies]\ndev = ["pytest>=7.0"]\n',
    )


def _uv_lock(root: Path, **levels: str) -> None:
    blocks = "\n".join(
        f'[[package]]\nname = "{name}"\nversion = "{level}"\n'
        f'source = {{ registry = "https://pypi.org/simple" }}\n'
        for name, level in levels.items()
    )
    _write(root, "server/uv.lock", f"version = 1\n\n{blocks}")


def _package_json(root: Path, rel_path: str, **sections: dict[str, str]) -> None:
    _write(root, rel_path, json.dumps({"name": "fixture", **sections}))


def _entry(**overrides: Any) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "name": "idfkit",
        "declared_in": ["server/pyproject.toml", "server/uv.lock"],
        "resolution": "exact pin, resolved from PyPI by uv",
        "level": "1.0.0rc1",
        "current": "1.0.0rc1",
        "standing": "current",
    }
    entry.update(overrides)
    return entry


def _agreeing_tree(root: Path) -> None:
    _levels(root, _entry())
    _pyproject(root, "idfkit==1.0.0rc1")
    _uv_lock(root, idfkit="1.0.0rc1")


def _failures(root: Path) -> str:
    report = check_levels(root)
    assert not report.ok, "expected the check to fail"
    return "\n".join(report.failures)


class TestAgreement:
    def test_a_tree_that_agrees_passes(self, tmp_path: Path) -> None:
        _agreeing_tree(tmp_path)
        report = check_levels(tmp_path)
        assert report.ok, report.failures

    def test_a_declared_path_stating_another_level_fails(self, tmp_path: Path) -> None:
        _levels(tmp_path, _entry())
        _pyproject(tmp_path, "idfkit==1.0.0rc1")
        _uv_lock(tmp_path, idfkit="1.0.1")

        failures = _failures(tmp_path)
        assert "server/uv.lock" in failures
        assert "1.0.1" in failures
        assert "1.0.0rc1" in failures

    def test_two_declared_paths_disagreeing_names_both(self, tmp_path: Path) -> None:
        _levels(tmp_path, _entry())
        _pyproject(tmp_path, "idfkit==1.0.0rc1")
        _uv_lock(tmp_path, idfkit="1.0.1")

        disagreement = [
            failure
            for failure in check_levels(tmp_path).failures
            if "two declared paths disagree" in failure
        ]
        assert len(disagreement) == 1
        assert "server/pyproject.toml" in disagreement[0]
        assert "server/uv.lock" in disagreement[0]

    def test_a_missing_declared_path_is_named(self, tmp_path: Path) -> None:
        _levels(tmp_path, _entry())
        _pyproject(tmp_path, "idfkit==1.0.0rc1")

        failures = _failures(tmp_path)
        assert "server/uv.lock: declared as stating a level, but does not exist" in failures


class TestStanding:
    def test_behind_without_a_reason_fails(self, tmp_path: Path) -> None:
        _levels(tmp_path, _entry(current="1.1.0", standing="behind_deliberate"))
        _pyproject(tmp_path, "idfkit==1.0.0rc1")
        _uv_lock(tmp_path, idfkit="1.0.0rc1")

        assert "carries no reason" in _failures(tmp_path)

    def test_behind_temporary_without_a_tracked_item_fails(self, tmp_path: Path) -> None:
        _levels(
            tmp_path,
            _entry(
                current="1.1.0",
                standing="behind_temporary",
                reason="the level it will resolve is not published yet",
            ),
        )
        _pyproject(tmp_path, "idfkit==1.0.0rc1")
        _uv_lock(tmp_path, idfkit="1.0.0rc1")

        assert "names no tracked item" in _failures(tmp_path)


class TestNpmManifests:
    def test_a_range_is_not_an_exact_pin(self, tmp_path: Path) -> None:
        _agreeing_tree(tmp_path)
        _levels(
            tmp_path,
            _entry(),
            _entry(
                name="vscode-languageclient",
                declared_in=["client/package.json"],
                resolution="exact pin, resolved from the npm registry",
                level="9.0.1",
                current="9.0.1",
            ),
        )
        _package_json(
            tmp_path, "client/package.json", dependencies={"vscode-languageclient": "^9.0.1"}
        )

        failures = _failures(tmp_path)
        assert "client/package.json" in failures
        assert "range" in failures
        assert "Principle III" in failures

    def test_a_facade_named_with_a_parenthetical_resolves_by_its_first_word(
        self, tmp_path: Path
    ) -> None:
        _agreeing_tree(tmp_path)
        _levels(
            tmp_path,
            _entry(),
            _entry(
                name="idfkit (the second language's facade)",
                declared_in=["model-server/package.json"],
                resolution="optional peer, not installed by this repository",
                level="0.0.0",
                current="0.0.0",
                standing="behind_temporary",
                reason="the facade is not published to the npm registry",
                tracked="feature 005 of the unification",
            ),
        )
        _package_json(tmp_path, "model-server/package.json", peerDependencies={"idfkit": "0.0.0"})

        report = check_levels(tmp_path)
        assert report.ok, report.failures

    def test_an_undeclared_dependency_fails(self, tmp_path: Path) -> None:
        _agreeing_tree(tmp_path)
        _package_json(
            tmp_path,
            "model-server/package.json",
            dependencies={"vscode-languageserver": "10.1.1"},
        )

        failures = _failures(tmp_path)
        assert "vscode-languageserver" in failures
        assert "no entry in levels.json" in failures
