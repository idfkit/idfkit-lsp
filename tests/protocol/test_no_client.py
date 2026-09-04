"""Everything a user depends on, reached without this repository's client.

US7 is the claim that a second editor costs a launch configuration and nothing else. The claim is
only worth what it can be shown to be: FR-031 says every advertised capability must be reachable by
driving the servers alone, and SC-010 counts what a user in a different editor loses, excluding
what the declaration records as editor-specific.

The harness is the demonstration. It is a plain protocol client that belongs to the suite rather
than to the extension, so an answer it gets is an answer any editor gets.

Three things are asserted, and the third is the one that would otherwise drift:

1. every capability the declaration marks present is answered with no client running,
2. the only protocol requests the client's own source names are the ones the declaration marks
   ``editor_specific``, so nothing else a user sees passes through it, and
3. neither server is started by way of the client.

The set of editor-specific entries is read from the declaration, never written here: a limitation
that stopped being editor-specific, or a new one that appeared, changes one file and this suite
follows it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest

from .conftest import REPOSITORY_ROOT
from .test_declaration import ProbeDocument, ask, opened

if TYPE_CHECKING:
    from idfkit_lsp.capabilities import ServerDeclaration

    from .harness import ProtocolClient, ServerDescription

CLIENT_SOURCE = REPOSITORY_ROOT / "client" / "src"

_CLIENT_SUFFIXES = frozenset({".ts", ".tsx", ".js", ".mjs", ".cjs"})


def _unanswered(client: ProtocolClient, declared: ServerDeclaration) -> list[str]:
    """Every present capability this server did not answer while nothing else was running."""
    found: list[str] = []
    document = ProbeDocument.for_server(declared, f"no-client-{declared.id}")
    with opened(client, document):
        for capability in declared.capabilities:
            if not capability.is_present:
                continue
            answer = ask(client, capability.request, document)
            if not answer.answered:
                found.append(
                    f"the {declared.id} server: {capability.request} is advertised and is not "
                    f"reachable without the client ({answer.detail})"
                )
    return found


def _client_text() -> str:
    """Everything the client is written in, as one body of text to look for request names in."""
    if not CLIENT_SOURCE.is_dir():
        pytest.skip(f"{CLIENT_SOURCE} does not exist, so there is no client to read")
    parts = [
        path.read_text(encoding="utf-8")
        for path in sorted(CLIENT_SOURCE.rglob("*"))
        if path.is_file() and path.suffix in _CLIENT_SUFFIXES
    ]
    if not parts:
        pytest.skip(f"{CLIENT_SOURCE} holds no source to read")
    return "\n".join(parts)


def _declared_requests(declaration: Any) -> frozenset[str]:
    return frozenset(
        capability.request for server in declaration.servers for capability in server.capabilities
    )


def _editor_specific(declaration: Any) -> frozenset[str]:
    return frozenset(
        capability.request
        for server in declaration.servers
        for capability in server.capabilities
        if capability.editor_specific
    )


class TestEveryAdvertisedCapabilityIsReachedWithoutTheClient:
    """FR-031, driven by a client that belongs to the suite rather than to one editor."""

    def test_the_source_server(self, source_server: ProtocolClient, declaration: Any) -> None:
        found = _unanswered(source_server, declaration.source)
        assert not found, "the source server needs the client:\n" + "\n".join(found)

    def test_the_model_server(self, model_server: ProtocolClient, declaration: Any) -> None:
        found = _unanswered(model_server, declaration.model)
        assert not found, "the model server needs the client:\n" + "\n".join(found)


class TestOnlyTheDeclaredLimitationsPassThroughTheClient:
    """SC-010: what a user in another editor loses is exactly what the declaration says it is."""

    def test_the_client_names_no_request_the_declaration_does_not_call_editor_specific(
        self, declaration: Any
    ) -> None:
        text = _client_text()
        editor_specific = _editor_specific(declaration)

        named = frozenset(
            request for request in _declared_requests(declaration) if request in text
        )

        unrecorded = sorted(named - editor_specific)
        assert not unrecorded, (
            "the client names protocol requests the declaration does not record as "
            f"editor-specific, so a user in another editor loses them silently: {unrecorded}"
        )
        unreached = sorted(editor_specific - named)
        assert not unreached, (
            "the declaration records these requests as editor-specific and the client does not "
            f"name any of them, so the limitation describes nothing: {unreached}"
        )

    def test_an_editor_specific_limitation_is_recorded_on_something_the_server_serves(
        self, declaration: Any
    ) -> None:
        stated = [
            f"the {server.id} server: {capability.request} is marked editor-specific and is "
            f"declared {capability.state.value}"
            for server in declaration.servers
            for capability in server.capabilities
            if capability.editor_specific and not capability.is_present
        ]
        assert not stated, (
            "an editor-specific limitation qualifies a capability a server offers, so it cannot "
            "sit on one no server offers:\n" + "\n".join(stated)
        )


class TestNeitherServerIsStartedThroughTheClient:
    """The mechanical form of "no client code is loaded": the client is nowhere on the command."""

    def test_the_source_server(self, source_server_description: ServerDescription) -> None:
        found = _client_mentions(source_server_description)
        assert not found, f"starting the source server reaches into the client: {found}"

    def test_the_model_server(self, model_server_description: ServerDescription) -> None:
        found = _client_mentions(model_server_description)
        assert not found, f"starting the model server reaches into the client: {found}"


def _client_mentions(description: ServerDescription) -> list[str]:
    """Wherever starting this server would reach into the client's tree, if anywhere."""
    client = str(CLIENT_SOURCE.parent)
    places = [*description.argv, str(description.cwd or ""), *description.environment().values()]
    return [place for place in places if client in place]
