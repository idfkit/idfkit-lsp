"""Tests for ``language-configuration.json``, which holds the line comment marker of model text.

VS Code reads the marker for comment toggling from a language configuration, and the protocol has
no request that could carry it. Constitution Principle V requires such glue to be recorded in the
capability declaration as an editor-specific limitation. Principle I limits the file to this one
value, and Principle VI requires the marker to be checked against a server, not an editor.

Four things are asserted:

1. the manifest routes the model language to a configuration file that exists and is named for
   packaging,
2. that file holds the comment marker and no other member, which excludes a word pattern and a
   bracket table,
3. the declaration records the file as retained, editor-specific knowledge, and
4. the language service classifies a line opened by the marker as one comment region.

The marker is read from the file and is not written here, so this suite holds no copy of it.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from .conftest import REPOSITORY_ROOT
from .test_model_server import Token, _classification, _opened

if TYPE_CHECKING:
    from pathlib import Path

    from .harness import ProtocolClient

_MANIFEST = REPOSITORY_ROOT / "package.json"
_DECLARATION = REPOSITORY_ROOT / "capabilities.json"
_PACKAGING_IGNORE = REPOSITORY_ROOT / ".vscodeignore"

# A statement that classifies as several regions when no marker precedes it, because of its
# separators. A marker has to reduce it to one region of a different kind.
_STATEMENT = "Version, 26.1;"


@dataclass(frozen=True)
class ManifestLanguage:
    """One ``contributes.languages`` entry of the extension manifest, in the members read here."""

    id: str
    configuration: str | None


@dataclass(frozen=True)
class LanguageConfiguration:
    """The configuration file, with its member names kept so that an extra member is visible."""

    members: frozenset[str]
    comment_members: frozenset[str]
    line_comment: object

    @classmethod
    def read(cls, path: Path) -> LanguageConfiguration:
        data = json.loads(path.read_text(encoding="utf-8"))
        comments = data.get("comments", {})
        return cls(frozenset(data), frozenset(comments), comments.get("lineComment"))


@dataclass(frozen=True)
class RetainedRecord:
    """One ``retained_knowledge`` entry of the declaration, in the members read here."""

    where: str
    editor_specific: bool


def _configuration_path(declaration: Any) -> str:
    """The configuration the manifest names for the model language, relative to the root."""
    language_id = declaration.model.documents[0].language_id
    manifest = json.loads(_MANIFEST.read_text(encoding="utf-8"))
    languages = [
        ManifestLanguage(item["id"], item.get("configuration"))
        for item in manifest["contributes"]["languages"]
    ]
    entry = next((language for language in languages if language.id == language_id), None)
    assert entry is not None, f"the manifest does not contribute the language {language_id!r}"
    assert entry.configuration is not None, (
        f"the manifest contributes {language_id!r} with no configuration, so VS Code has no "
        "comment marker for it and toggling a comment does nothing"
    )
    return entry.configuration.removeprefix("./")


def _retained_records() -> tuple[RetainedRecord, ...]:
    declared = json.loads(_DECLARATION.read_text(encoding="utf-8"))
    return tuple(
        RetainedRecord(item["where"], item.get("editor_specific", False))
        for item in declared["retained_knowledge"]
    )


def _marker(declaration: Any) -> str:
    path = REPOSITORY_ROOT / _configuration_path(declaration)
    marker = LanguageConfiguration.read(path).line_comment
    assert isinstance(marker, str), f"{path.name} declares no usable marker: {marker!r}"
    return marker


def _line_regions(client: ProtocolClient, declaration: Any, name: str, text: str) -> list[Token]:
    """The regions the model server classifies on the first line of ``text``."""
    kind = declaration.model.documents[0]
    with _opened(client, kind, f"language-configuration/{name}", text) as sample:
        return [token for token in _classification(client, sample) if token.line == 0]


class TestTheConfigurationStaysGlue:
    """Principles I and V: the file records one value and no pattern over model text."""

    def test_the_manifest_names_a_file_that_exists(self, declaration: Any) -> None:
        path = REPOSITORY_ROOT / _configuration_path(declaration)
        assert path.is_file(), f"the manifest names {path.name}, which does not exist"

    def test_the_file_is_named_for_packaging(self, declaration: Any) -> None:
        path = _configuration_path(declaration)
        lines = _PACKAGING_IGNORE.read_text(encoding="utf-8").splitlines()
        assert f"!{path}" in lines, (
            f"{_PACKAGING_IGNORE.name} does not keep {path} by name, so tightening the packaging "
            "could drop it and comment toggling would stop with no error"
        )

    def test_the_file_holds_the_comment_marker_and_nothing_else(self, declaration: Any) -> None:
        path = _configuration_path(declaration)
        configuration = LanguageConfiguration.read(REPOSITORY_ROOT / path)
        assert configuration.members == {"comments"}, (
            f"{path} holds {sorted(configuration.members)}. Only the comment marker is recorded as "
            "editor-specific glue, and a word pattern is a grammar pattern, which Principle I "
            "forbids"
        )
        assert configuration.comment_members == {"lineComment"}, (
            f"{path} declares {sorted(configuration.comment_members)} under comments, and only the "
            "line comment marker is recorded"
        )
        marker = configuration.line_comment
        assert isinstance(marker, str) and marker, f"{path} declares no usable marker: {marker!r}"

    def test_the_declaration_records_it_as_editor_specific(self, declaration: Any) -> None:
        path = _configuration_path(declaration)
        recorded = [record for record in _retained_records() if record.where == path]
        assert len(recorded) == 1, (
            f"{_DECLARATION.name} carries {len(recorded)} retained_knowledge entries for {path}, "
            "and Principle V requires exactly one record of this glue"
        )
        assert recorded[0].editor_specific, (
            f"the record of {path} does not say it is editor-specific, so a reader cannot tell "
            "that other editors do not receive it"
        )


class TestTheServiceAgreesWithTheMarker:
    """Principle VI: the marker is compared with the classification of the language service."""

    def test_a_marked_line_is_one_region_from_the_marker_to_the_line_end(
        self, model_server: ProtocolClient, declaration: Any
    ) -> None:
        line = f"{_marker(declaration)} {_STATEMENT}"
        regions = _line_regions(model_server, declaration, "marked", f"{line}\n")
        assert [(region.start, region.length) for region in regions] == [(0, len(line))], (
            "the language service does not classify a line opened by the configured marker as "
            f"one comment, so the marker and the service disagree: {regions}"
        )
        # The span alone would also accept a service that reports an unrecognised line as one
        # region. The kind has to differ from every kind the unmarked statement receives.
        statement = _line_regions(model_server, declaration, "statement", f"{_STATEMENT}\n")
        assert regions[0].kind not in {region.kind for region in statement}, (
            "the marked line has a kind the unmarked statement also has, so the marker did not "
            f"change how the service classifies the text: {regions} against {statement}"
        )

    def test_the_same_line_without_the_marker_is_not_one_region(
        self, model_server: ProtocolClient, declaration: Any
    ) -> None:
        """The control: without it, a service that merged every line would pass the test above."""
        regions = _line_regions(model_server, declaration, "unmarked", f"{_STATEMENT}\n")
        assert len(regions) > 1, (
            f"the statement used as the sample is one region without a marker: {regions}, so the "
            "test above cannot tell a comment from anything else"
        )
