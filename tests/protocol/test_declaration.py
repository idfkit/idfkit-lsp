"""The declaration and the servers, held against each other in both directions.

``capabilities.json`` is the single record of what each server answers, so the one failure it
cannot be allowed to have is disagreement with the servers it describes. This file asserts that
agreement mechanically, which is what FR-035 asks for and what SC-001 counts:

* a request the declaration marks present that the owning server refuses fails, and
* a request the declaration marks absent that the owning server answers fails,

each named as one sentence saying which server, which request, and which of the two directions.

**How a request is asked.** A capability is probed rather than looked up, because looking it up
would mean this file holding a second copy of the thing it is meant to be checking. The shape of
the probe follows from the request's own name: a ``textDocument/`` request is asked at a position,
a command request is asked by naming a command the server cannot possibly have registered, and
anything else is asked with no parameters at all.

**What counts as answering.** A server answers a request when it does not refuse the method
outright. A handled request that declines on its parameters is still a handled request: the
declaration records which requests reach a handler, not which invocations succeed. The distinction
matters for the command request, where naming an undefined command is the only way to ask "do you
handle this method" without also asking a command to run.

**One request is never asked.** Published diagnostics travel from server to client, so a client
never requests them. Its presence is observed the only way it can be: by opening a document and
seeing whether anything arrives.

The probing helpers here are also used by ``test_no_client.py``, which asks the same question for a
different reason.
"""

from __future__ import annotations

import contextlib
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, Any

import pytest

from .harness import ProtocolTimeout

if TYPE_CHECKING:
    from collections.abc import Iterator

    from idfkit_lsp.capabilities import ServerDeclaration

    from .harness import ProtocolClient

# Protocol method names, which are facts about the protocol rather than knowledge about a model.
_COMMAND_REQUEST = "workspace/executeCommand"
_PUBLISHED_DIAGNOSTICS = "textDocument/publishDiagnostics"
_DOCUMENT_REQUEST_PREFIX = "textDocument/"

# A command no server can have registered. Asking for it separates a server that handles the
# command request and rejects the name from one that does not handle the request at all.
_UNDEFINED_COMMAND = "idfkit-lsp/protocol-suite/no-such-command"

# How long one probe waits. Below the harness's own default, because a probe that hangs is a probe
# whose parameters do not fit rather than a server thinking, and the run should say so sooner.
_PROBE_TIMEOUT = 10.0

# How long to wait before concluding a server sent nothing unprompted. Long enough that a server
# doing work on an opened document is not mistaken for a server with nothing to say.
_QUIET_SECONDS = 2.0

# Which advertised provider names which request. Protocol knowledge, and deliberately partial: a
# provider this suite has never seen fails the run rather than passing unnoticed, so the mapping
# cannot go stale in the quiet direction.
_PROVIDER_REQUESTS: dict[str, str] = {
    "completionProvider": "textDocument/completion",
    "hoverProvider": "textDocument/hover",
    "signatureHelpProvider": "textDocument/signatureHelp",
    "definitionProvider": "textDocument/definition",
    "diagnosticProvider": "textDocument/diagnostic",
    "semanticTokensProvider": "textDocument/semanticTokens/full",
    "executeCommandProvider": _COMMAND_REQUEST,
}

_PROVIDER_SUFFIX = "Provider"

# The declaration's own names for its two absent states, spelled here rather than imported so that
# this file collects whether or not the reader module has been written yet.
_ABSENT_PERMANENT = "absent_permanent"
_ABSENT_TEMPORARY = "absent_temporary"


class RequestShape(Enum):
    """How one request has to be asked, read from the request's own name."""

    AT_A_POSITION = "a request about a position in a document"
    A_COMMAND = "a request to run a command the server registered"
    UNPROMPTED = "a message a server sends unasked, which a client never requests"
    PLAIN = "a request carrying no document"


def shape_of(request: str) -> RequestShape:
    """Which probe fits ``request``. Two named exceptions, then the request's own prefix."""
    if request == _COMMAND_REQUEST:
        return RequestShape.A_COMMAND
    if request == _PUBLISHED_DIAGNOSTICS:
        return RequestShape.UNPROMPTED
    if request.startswith(_DOCUMENT_REQUEST_PREFIX):
        return RequestShape.AT_A_POSITION
    return RequestShape.PLAIN


@dataclass(frozen=True)
class ProbeDocument:
    """A document of the kind a server serves, built from what that server declares it serves.

    The text is one empty line and nothing else. A probe asks whether a request reaches a handler,
    and content that meant something to one server would have to mean something to the other, which
    would put a sample of model text and a sample of source in a file whose subject is neither.
    """

    uri: str
    language_id: str
    text: str = "\n"

    @classmethod
    def for_server(cls, declared: ServerDeclaration, name: str) -> ProbeDocument:
        kind = declared.documents[0]
        return cls(
            uri=f"file:///protocol-suite/{name}{kind.extensions[0]}",
            language_id=kind.language_id,
        )


@contextlib.contextmanager
def opened(client: ProtocolClient, document: ProbeDocument) -> Iterator[ProbeDocument]:
    """Open a document for the length of a probe, and close it however the probe ends.

    The clients are shared by the session, so a document left open would be a document the next
    test has to know about.
    """
    client.did_open(document.uri, document.language_id, document.text)
    try:
        yield document
    finally:
        client.did_close(document.uri)


@dataclass(frozen=True)
class Answer:
    """What one probe learned: whether the server answered, and in its own words why not."""

    request: str
    answered: bool
    detail: str
    #: Whether the server said anything at all. A server that says nothing has not stated an
    #: absence, so silence is never read as one: it fails whatever the declaration claims.
    reached: bool = True


def ask(client: ProtocolClient, request: str, document: ProbeDocument) -> Answer:
    """Probe one request against one server, without assuming what the answer should be."""
    shape = shape_of(request)
    if shape is RequestShape.UNPROMPTED:
        try:
            client.await_notification(request, timeout=_QUIET_SECONDS)
        except ProtocolTimeout:
            return Answer(request, False, f"nothing arrived in {_QUIET_SECONDS:g}s")
        return Answer(request, True, "the server sent it unprompted")

    if shape is RequestShape.A_COMMAND:
        params: Any = {"command": _UNDEFINED_COMMAND, "arguments": []}
    elif shape is RequestShape.AT_A_POSITION:
        params = {
            "textDocument": {"uri": document.uri},
            "position": {"line": 0, "character": 0},
        }
    else:
        params = None

    try:
        response = client.request(request, params, timeout=_PROBE_TIMEOUT)
    except ProtocolTimeout as silence:
        # A request whose parameters do not fit its protocol type is dropped before any handler
        # sees it, and nothing comes back. That is a defect in the probe rather than an answer
        # about the server, so it is reported as one instead of being counted either way.
        return Answer(
            request,
            False,
            f"the server never replied, which usually means the parameters this suite sends for "
            f"{request} do not fit it: {silence}",
            reached=False,
        )
    if response.unsupported:
        return Answer(request, False, f"refused the method: {response.error_message}")
    if response.ok:
        return Answer(request, True, "answered")
    return Answer(request, True, f"handled it and declined: {response.error_message}")


def disagreements(client: ProtocolClient, declared: ServerDeclaration) -> list[str]:
    """Every place this server and its declaration disagree, in either direction."""
    found: list[str] = []
    document = ProbeDocument.for_server(declared, f"declaration-{declared.id}")
    with opened(client, document):
        for capability in declared.capabilities:
            answer = ask(client, capability.request, document)
            if not answer.reached:
                found.append(
                    f"the {declared.id} server: {capability.request} could not be asked at all "
                    f"({answer.detail})"
                )
            elif capability.is_present and not answer.answered:
                found.append(
                    f"the {declared.id} server: {capability.request} is declared present and "
                    f"the server does not answer it ({answer.detail})"
                )
            elif not capability.is_present and answer.answered:
                found.append(
                    f"the {declared.id} server: {capability.request} is declared "
                    f"{capability.state.value} and the server answers it ({answer.detail})"
                )
    return found


@dataclass(frozen=True)
class Advertised:
    """What a server told the editor at startup, read back out of its initialize result."""

    requests: frozenset[str]
    unrecognised: tuple[str, ...]

    @classmethod
    def read(cls, client: ProtocolClient) -> Advertised:
        requests: set[str] = set()
        unrecognised: list[str] = []
        for key, value in client.server_capabilities.items():
            # Everything else in the result is lifecycle or document synchronisation, which every
            # server registers because an editor sends it whether or not anything is advertised.
            if not key.endswith(_PROVIDER_SUFFIX) or not value:
                continue
            request = _PROVIDER_REQUESTS.get(key)
            if request is None:
                unrecognised.append(key)
            else:
                requests.add(request)
        return cls(requests=frozenset(requests), unrecognised=tuple(sorted(unrecognised)))


def advertisement_faults(client: ProtocolClient, declared: ServerDeclaration) -> list[str]:
    """Every place what a server advertised and what the declaration says differ."""
    advertised = Advertised.read(client)
    found = [
        f"the {declared.id} server advertises {key!r}, which this suite does not recognise: add "
        f"it to the provider mapping in {__name__} so the comparison stays complete"
        for key in advertised.unrecognised
    ]
    # Only requests that have a provider to advertise can be compared this way. A custom request
    # never appears in an initialize result, and its presence is settled by asking for it.
    comparable = frozenset(_PROVIDER_REQUESTS.values())
    declared_here = declared.present_requests & comparable
    for request in sorted(advertised.requests - declared_here):
        found.append(
            f"the {declared.id} server advertises {request}, which the declaration does not "
            "mark present for it"
        )
    for request in sorted(declared_here - advertised.requests):
        found.append(
            f"the {declared.id} server does not advertise {request}, which the declaration "
            "marks present for it"
        )
    return found


@pytest.fixture(scope="session")
def source_declaration(declaration: Any) -> ServerDeclaration:
    return declaration.source


@pytest.fixture(scope="session")
def model_declaration(declaration: Any) -> ServerDeclaration:
    return declaration.model


class TestTheServersAnswerWhatIsDeclared:
    """SC-001, counted in both directions rather than read."""

    def test_the_source_server(
        self, source_server: ProtocolClient, source_declaration: ServerDeclaration
    ) -> None:
        found = disagreements(source_server, source_declaration)
        assert not found, "the declaration and the source server disagree:\n" + "\n".join(found)

    def test_the_model_server(
        self, model_server: ProtocolClient, model_declaration: ServerDeclaration
    ) -> None:
        found = disagreements(model_server, model_declaration)
        assert not found, "the declaration and the model server disagree:\n" + "\n".join(found)


class TestNothingIsAdvertisedOffTheDeclaration:
    """What a server tells an editor at startup is the declaration's list and no other."""

    def test_the_source_server(
        self, source_server: ProtocolClient, source_declaration: ServerDeclaration
    ) -> None:
        found = advertisement_faults(source_server, source_declaration)
        assert not found, "the source server advertises something else:\n" + "\n".join(found)

    def test_the_model_server(
        self, model_server: ProtocolClient, model_declaration: ServerDeclaration
    ) -> None:
        found = advertisement_faults(model_server, model_declaration)
        assert not found, "the model server advertises something else:\n" + "\n".join(found)


class TestAbsencesAreExplained:
    """Principle IV: an absence is stated with a way forward, never left as silence."""

    def test_a_permanent_absence_says_why_and_what_to_use_instead(self, declaration: Any) -> None:
        found = [
            f"the {server.id} server: {capability.request} is declared absent permanently "
            f"without a {field}"
            for server in declaration.servers
            for capability in server.capabilities
            if capability.state.value == _ABSENT_PERMANENT
            for field, value in (("reason", capability.reason), ("instead", capability.instead))
            if not value
        ]
        assert not found, "a permanent absence explains nothing:\n" + "\n".join(found)

    def test_a_temporary_absence_names_the_tracked_item(self, declaration: Any) -> None:
        found = [
            f"the {server.id} server: {capability.request} is declared absent for now without "
            "naming what is tracked to remove the absence"
            for server in declaration.servers
            for capability in server.capabilities
            if capability.state.value == _ABSENT_TEMPORARY and not capability.tracked
        ]
        assert not found, "a temporary absence tracks nothing:\n" + "\n".join(found)
