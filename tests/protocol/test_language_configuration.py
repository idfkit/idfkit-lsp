"""The one value this repository hands to an editor that no server can supply.

VS Code toggles a comment using a marker it reads from a language configuration, and the protocol
has no request that could carry it. Constitution Principle V routes that case through the capability
declaration as an editor-specific limitation. Principle I is why the file stays this small, and
Principle VI is why the marker is held against a server rather than against an editor.

Four things are asserted:

1. the manifest routes the model language to a configuration file that exists and is named for
   packaging,
2. that file holds the comment marker and no other member, so a word pattern or a bracket table
   cannot arrive unnoticed,
3. the declaration records the file as retained, editor-specific knowledge, and
4. what the file says is a comment is what the language service classifies as one.

The marker is read from the file and never written here, so this suite holds no copy of its own.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from .conftest import REPOSITORY_ROOT
from .test_declaration import ProbeDocument, opened
from .test_model_server import Token, decode_tokens

if TYPE_CHECKING:
    from pathlib import Path

    from .harness import ProtocolClient

_MANIFEST = REPOSITORY_ROOT / "package.json"
_DECLARATION = REPOSITORY_ROOT / "capabilities.json"
_PACKAGING_IGNORE = REPOSITORY_ROOT / ".vscodeignore"

_SEMANTIC_TOKENS = "textDocument/semanticTokens/full"

# A statement a marker can be put in front of. Its separators are what make it several regions when
# it is live, and one region is the observable difference a marker has to make.
_STATEMENT = "Version, 26.1;"


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _configuration_path(declaration: Any) -> str:
    """The configuration the manifest names for the model language, relative to the root."""
    language_id = declaration.model.documents[0].language_id
    languages = _read_json(_MANIFEST)["contributes"]["languages"]
    entry = next(item for item in languages if item["id"] == language_id)
    assert "configuration" in entry, (
        f"the manifest contributes {language_id!r} with no configuration, so VS Code has no "
        "comment marker for it and toggling a comment does nothing"
    )
    return entry["configuration"].removeprefix("./")


def _marker(declaration: Any) -> str:
    configuration = _read_json(REPOSITORY_ROOT / _configuration_path(declaration))
    return configuration["comments"]["lineComment"]


def _line_regions(client: ProtocolClient, declaration: Any, name: str, text: str) -> list[Token]:
    """The regions the model server classifies on the first line of ``text``."""
    kind = declaration.model.documents[0]
    document = ProbeDocument(
        uri=f"file:///protocol-suite/language-configuration/{name}{kind.extensions[0]}",
        language_id=kind.language_id,
        text=text,
    )
    with opened(client, document):
        result = client.request(_SEMANTIC_TOKENS, {"textDocument": {"uri": document.uri}}).unwrap()
    assert result is not None, "the server returned no classification at all"
    return [token for token in decode_tokens(result["data"]) if token.line == 0]


class TestTheConfigurationStaysGlue:
    """Principles I and V: one recorded value, and nothing that reads model text."""

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
        configuration = _read_json(REPOSITORY_ROOT / path)
        assert set(configuration) == {"comments"}, (
            f"{path} holds {sorted(configuration)}. Only the comment marker is recorded as "
            "editor-specific glue, and a word pattern is a grammar pattern, which Principle I "
            "forbids"
        )
        assert set(configuration["comments"]) == {"lineComment"}, (
            f"{path} declares {sorted(configuration['comments'])} under comments, and only the "
            "line comment marker is recorded"
        )
        marker = configuration["comments"]["lineComment"]
        assert isinstance(marker, str) and marker, f"{path} declares no usable marker: {marker!r}"

    def test_the_declaration_records_it_as_editor_specific(self, declaration: Any) -> None:
        path = _configuration_path(declaration)
        recorded = [
            entry
            for entry in _read_json(_DECLARATION)["retained_knowledge"]
            if entry["where"] == path
        ]
        assert len(recorded) == 1, (
            f"{_DECLARATION.name} carries {len(recorded)} retained_knowledge entries for {path}, "
            "and Principle V requires exactly one record of this glue"
        )
        assert recorded[0].get("editor_specific") is True, (
            f"the record of {path} does not say it is editor-specific, so a reader cannot tell "
            "that other editors do not receive it"
        )


class TestTheServiceAgreesWithTheMarker:
    """Principle VI: the copy is held against the library that owns the question."""

    def test_a_marked_line_is_one_region_from_the_marker_to_the_line_end(
        self, model_server: ProtocolClient, declaration: Any
    ) -> None:
        line = f"{_marker(declaration)} {_STATEMENT}"
        regions = _line_regions(model_server, declaration, "marked", f"{line}\n")
        assert [(region.start, region.length) for region in regions] == [(0, len(line))], (
            "the language service does not classify a line opened by the configured marker as "
            f"one comment, so the marker and the service disagree: {regions}"
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
