"""The bump declares the level the pinned files state, in their spelling (idfkit/idfkit-lsp#17)."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest

from ..check_levels import check_levels
from ..declare_level import declare

if TYPE_CHECKING:
    from pathlib import Path


def _tree(root: Path, *, declared: str, pinned: str) -> None:
    (root / "server").mkdir()
    (root / "server" / "pyproject.toml").write_text(
        f'[project]\nname = "idfkit-lsp"\ndependencies = [\n    "idfkit=={pinned}",\n]\n',
        encoding="utf-8",
    )
    (root / "server" / "uv.lock").write_text(
        f'version = 1\n\n[[package]]\nname = "idfkit"\nversion = "{pinned}"\n'
        'source = { registry = "https://pypi.org/simple" }\n',
        encoding="utf-8",
    )
    declaration = {
        "version": 1,
        "register": "the consumer register",
        "libraries": [
            {
                "name": "idfkit",
                "declared_in": ["server/pyproject.toml", "server/uv.lock"],
                "resolution": "exact pin, resolved from PyPI by uv",
                "level": declared,
                "current": declared,
                "standing": "current",
            }
        ],
    }
    (root / "levels.json").write_text(json.dumps(declaration), encoding="utf-8")


def _failures(root: Path) -> list[str]:
    return [finding for finding in check_levels(root).failures if "idfkit" in finding]


def test_the_tag_spelling_is_what_failed_every_release_candidate(tmp_path: Path) -> None:
    # What the old bump wrote: uv's pin in the manifest and lockfile, the tag's spelling declared.
    _tree(tmp_path, declared="1.0.0-rc.4", pinned="1.0.0rc4")
    assert _failures(tmp_path)


def test_declaring_from_the_lockfile_agrees_with_the_pin(tmp_path: Path) -> None:
    _tree(tmp_path, declared="1.0.0rc1", pinned="1.0.0rc4")
    assert declare(tmp_path, "idfkit", "server/uv.lock") == "1.0.0rc4"
    assert _failures(tmp_path) == []
    entry = json.loads((tmp_path / "levels.json").read_text())["libraries"][0]
    assert (entry["level"], entry["current"], entry["standing"]) == (
        "1.0.0rc4",
        "1.0.0rc4",
        "current",
    )


def test_declaring_a_library_the_file_does_not_state_fails(tmp_path: Path) -> None:
    _tree(tmp_path, declared="1.0.0rc1", pinned="1.0.0rc4")
    with pytest.raises(ValueError, match="pygls"):
        declare(tmp_path, "pygls", "server/uv.lock")
