"""The model server's behaviour, asked over the protocol rather than through its own functions.

Four groups, and all of them run.

``classify`` and ``answers`` drive the five model-text answers, every one of them read from
``@idfkit/language``. They were written in full against the surface
``contracts/language-service.md`` fixes while that component was unpublished, and they ran without
being touched on the day it shipped, which is what writing them against a contract was for.

Two of them are marked ``xfail`` and each marker says what the service does instead, measured. Both
are gaps on the service's side that this repository must not close: closing either means validating
or reading model text here, which is the knowledge Principle I keeps out. The markers are strict, so
a fix upstream fails the run rather than passing unnoticed, and the marker is deleted rather than
discovered later.

``missing_component`` and ``ownership`` run on their own terms. The first is scenario 7 of the
quickstart, which must pass whether or not the component is installed, because it is about the path
where it is not. The second is the ownership half of user story 3 and FR-030, which is about which
server serves which document and about neither taking the other down.

**Why this file measures positions.** Principle I keeps position arithmetic over model text out of
the servers, where an answer is produced. A suite that checks an answer has to measure it: a range
that selects the wrong characters is exactly the defect worth catching, and it cannot be caught by
reading the range back. So the helpers below convert between the protocol's units and Python's,
they do it over fixtures this file wrote rather than over a user's model, and they never produce an
answer about model text. The one thing they will not do is describe the format: nothing here knows
what a field is, where one begins, or which of them a position falls in. Each fixture carries a
value this file put there, and the assertion is that the server's range selects that value, found
by searching the fixture for it.
"""

from __future__ import annotations

import bisect
import contextlib
import json
from collections import defaultdict
from dataclasses import dataclass
from enum import IntEnum
from itertools import pairwise
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

from .harness import ProtocolClient, ProtocolTimeout, start_server

if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping, Sequence

    from idfkit_lsp.capabilities import DocumentKind, ServerDeclaration

    from .harness import ServerDescription

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]

# Protocol method names and this repository's own request. Facts about the protocol, not knowledge
# about a model, and spelled here for the same reason ``test_declaration.py`` spells them.
_VERSIONS_REQUEST = "idfkit-lsp/versions"
_SEMANTIC_TOKENS = "textDocument/semanticTokens/full"
_DIAGNOSTIC = "textDocument/diagnostic"
_COMPLETION = "textDocument/completion"
_HOVER = "textDocument/hover"
_DEFINITION = "textDocument/definition"
_PUBLISHED_DIAGNOSTICS = "textDocument/publishDiagnostics"
_SHOW_MESSAGE = "window/showMessage"
_LOG_MESSAGE = "window/logMessage"

_DOCUMENT_REQUEST_PREFIX = "textDocument/"

# The three document requests that carry a position. The other two carry the document alone, and
# sending a position they do not take would be a defect in the probe rather than in the server.
_AT_A_POSITION = frozenset({_COMPLETION, _HOVER, _DEFINITION})

# How long to wait for what a server says unprompted at startup. Generous, because it is the one
# message a user acts on and a run that missed it would be reporting the wrong failure.
_STARTUP_SECONDS = 10.0

# How long to wait before concluding nothing more is coming. Notifications that have arrived are
# routed while this runs, so it drains rather than merely sleeps.
_QUIET_SECONDS = 2.0

# A notification no server sends. Waiting for it is how everything already in flight is routed
# without consuming any of it.
_NEVER_SENT = "idfkit-lsp/protocol-suite/no-such-notification"

# The model server's manifest, which is where this file learns what a user would have to install
# rather than writing the answer down and hoping it stays true.
_MODEL_MANIFEST = REPOSITORY_ROOT / "model-server" / "package.json"

# What the source server answers about, unchanged from ``test_source_server.py``: the point of
# using it here is that it is known to work, so a failure means the model server disturbed it.
_SOURCE_SAMPLE = 'from idfkit import load_idf\ndoc = load_idf("x.idf")\ndoc["Zon'
_SOURCE_SAMPLE_POSITION = (2, 8)
_SOURCE_SAMPLE_OFFERS = "Zone"


class MessageType(IntEnum):
    """The protocol's severities for what a server says to a user or to a log."""

    ERROR = 1
    WARNING = 2
    INFO = 3
    LOG = 4


# ---------------------------------------------------------------------------
# The protocol's units, and this file's arithmetic over its own fixtures
# ---------------------------------------------------------------------------


def _utf16_length(text: str) -> int:
    """How many units the protocol counts in ``text``.

    Two for a character outside the basic plane, one for everything else, which is the whole of
    what separates a range that selects the right characters from one that is off by a unit.
    """
    return len(text.encode("utf-16-le")) // 2


def _index_within(line: str, character: int) -> int:
    """The Python index in ``line`` of a protocol character offset.

    An offset landing between the halves of an astral character resolves past it, which is the
    same clamp the server's own index applies and the only sensible answer to a position that
    selects half a character.
    """
    if character <= 0:
        return 0
    units = 0
    for index, char in enumerate(line):
        if units >= character:
            return index
        units += 2 if ord(char) > 0xFFFF else 1
    return len(line)


@dataclass(frozen=True)
class Position:
    """One protocol position: a line, and a character offset in the negotiated unit."""

    line: int
    character: int

    @classmethod
    def from_protocol(cls, data: Mapping[str, Any]) -> Position:
        return cls(line=int(data["line"]), character=int(data["character"]))

    def as_protocol(self) -> dict[str, int]:
        return {"line": self.line, "character": self.character}


@dataclass(frozen=True)
class Range:
    """One protocol range, half open at the end as the protocol has it."""

    start: Position
    end: Position

    @classmethod
    def from_protocol(cls, data: Mapping[str, Any]) -> Range:
        return cls(
            start=Position.from_protocol(data["start"]),
            end=Position.from_protocol(data["end"]),
        )


@dataclass(frozen=True)
class Sample:
    """One piece of model text under test, and the little arithmetic checking it requires.

    A sample knows where its own values are because this file put them there. It knows nothing
    about the format: ``locate`` searches for a string a test named, and refuses a string that
    appears more than once so that a fixture edited later cannot quietly move an assertion.
    """

    uri: str
    text: str

    # -- lines, split the way the server's own index splits them ----------

    @property
    def line_starts(self) -> tuple[int, ...]:
        starts = [0]
        index = 0
        while index < len(self.text):
            char = self.text[index]
            if char == "\r":
                index += 2 if self.text[index + 1 : index + 2] == "\n" else 1
                starts.append(index)
            elif char == "\n":
                index += 1
                starts.append(index)
            else:
                index += 1
        return tuple(starts)

    @property
    def line_spans(self) -> tuple[tuple[int, int], ...]:
        """Each line's content, terminator excluded. A text ending in one has an empty last line."""
        starts = self.line_starts
        spans: list[tuple[int, int]] = []
        for number, start in enumerate(starts):
            end = len(self.text) if number + 1 == len(starts) else starts[number + 1]
            content = self.text[start:end]
            spans.append((start, start + len(content.rstrip("\r\n"))))
        return tuple(spans)

    @property
    def lines(self) -> tuple[str, ...]:
        return tuple(self.text[start:end] for start, end in self.line_spans)

    # -- positions --------------------------------------------------------

    def position_of(self, index: int) -> Position:
        starts = self.line_starts
        line = bisect.bisect_right(starts, index) - 1
        return Position(line=line, character=_utf16_length(self.text[starts[line] : index]))

    def index_of(self, position: Position) -> int:
        start, end = self.line_spans[position.line]
        return start + _index_within(self.text[start:end], position.character)

    def select(self, span: Range) -> str:
        """The characters a range selects, which is the whole question a range has to answer."""
        return self.text[self.index_of(span.start) : self.index_of(span.end)]

    # -- what this file put in the text -----------------------------------

    def locate(self, value: str, *, after: int = 0) -> int:
        occurrences = self.text.count(value)
        assert occurrences == 1, (
            f"{value!r} appears {occurrences} times in this sample, so an assertion about it "
            "would be about no particular place: give the fixture a value that appears once"
        )
        return self.text.index(value) + after

    def at(self, value: str, *, after: int = 0) -> Position:
        """The position at, or just past, a value this file wrote into the sample."""
        return self.position_of(self.locate(value, after=after))

    def span_of(self, value: str) -> Range:
        """The range that selects exactly a value this file wrote into the sample."""
        index = self.locate(value)
        return Range(start=self.position_of(index), end=self.position_of(index + len(value)))


# ---------------------------------------------------------------------------
# What the answers look like once they are off the wire
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Token:
    """One semantic token, decoded out of the protocol's deltas into absolute units."""

    line: int
    start: int
    length: int
    kind: int
    modifiers: int

    @property
    def end(self) -> int:
        return self.start + self.length


def decode_tokens(data: Sequence[int]) -> tuple[Token, ...]:
    """The protocol's five numbers per token, as absolute positions in the negotiated unit."""
    assert len(data) % 5 == 0, (
        f"a semantic token payload is five numbers per token, got {len(data)}"
    )
    tokens: list[Token] = []
    line = 0
    character = 0
    for cursor in range(0, len(data), 5):
        delta_line, delta_start, length, kind, modifiers = data[cursor : cursor + 5]
        line += delta_line
        character = delta_start if delta_line else character + delta_start
        tokens.append(
            Token(line=line, start=character, length=length, kind=kind, modifiers=modifiers)
        )
    return tuple(tokens)


@dataclass(frozen=True)
class Diagnostic:
    """One finding as the protocol carries it, in the members the contract pins."""

    range: Range
    message: str
    severity: int | None
    code: str | None
    source: str | None
    precision: str | None

    @classmethod
    def from_protocol(cls, data: Mapping[str, Any]) -> Diagnostic:
        extra = data.get("data")
        precision = extra.get("precision") if isinstance(extra, dict) else None
        return cls(
            range=Range.from_protocol(data["range"]),
            message=data["message"],
            severity=data.get("severity"),
            code=data.get("code"),
            source=data.get("source"),
            precision=precision,
        )


@dataclass(frozen=True)
class Offer:
    """One completion item, in the members a translation can get wrong."""

    label: str
    replaces: Range | None

    @classmethod
    def from_protocol(cls, data: Mapping[str, Any]) -> Offer:
        edit = data.get("textEdit")
        replaces = Range.from_protocol(edit["range"]) if isinstance(edit, dict) else None
        return cls(label=data["label"], replaces=replaces)


@dataclass(frozen=True)
class CompletionAnswer:
    """A completion answer, with the one flag that says which absence an empty list stands for."""

    is_incomplete: bool
    offers: tuple[Offer, ...]

    @classmethod
    def from_protocol(cls, result: Any) -> CompletionAnswer | None:
        """``None`` where the server returned nothing at all, which is not an empty list."""
        if result is None:
            return None
        items = result.get("items", []) if isinstance(result, dict) else result
        incomplete = bool(result.get("isIncomplete", False)) if isinstance(result, dict) else False
        return cls(
            is_incomplete=incomplete, offers=tuple(Offer.from_protocol(item) for item in items)
        )

    @property
    def labels(self) -> tuple[str, ...]:
        return tuple(offer.label for offer in self.offers)

    @property
    def is_complete_and_empty(self) -> bool:
        """The one shape that tells an editor the schema permits nothing at this position."""
        return not self.offers and not self.is_incomplete


@dataclass(frozen=True)
class ServerMessage:
    """One thing a server said unprompted, on whichever of the two channels it said it."""

    channel: str
    type: int
    text: str


# ---------------------------------------------------------------------------
# Driving a server
# ---------------------------------------------------------------------------


def _drain(client: ProtocolClient, seconds: float = _QUIET_SECONDS) -> None:
    """Route everything the server has sent, consuming none of it."""
    with contextlib.suppress(ProtocolTimeout):
        client.await_notification(_NEVER_SENT, timeout=seconds)


def _messages(client: ProtocolClient) -> tuple[ServerMessage, ...]:
    """Everything a server has said on the two channels a user or a log reads."""
    said: list[ServerMessage] = []
    for notification in client.received_notifications:
        if notification.method not in (_SHOW_MESSAGE, _LOG_MESSAGE):
            continue
        params = notification.params
        if not isinstance(params, dict):
            continue
        said.append(
            ServerMessage(
                channel=notification.method,
                type=int(params.get("type", MessageType.LOG)),
                text=str(params.get("message", "")),
            )
        )
    return tuple(said)


@contextlib.contextmanager
def _started(description: ServerDescription) -> Iterator[ProtocolClient]:
    """A server started by hand, so that what it says at startup is still in the client."""
    with ProtocolClient(description) as client:
        response = client.initialize()
        assert response.ok, f"{description.name}: initialize failed: {response.error}"
        client.initialized()
        yield client


@contextlib.contextmanager
def _opened(client: ProtocolClient, kind: DocumentKind, name: str, text: str) -> Iterator[Sample]:
    """Open a sample for the length of one test, and close it however the test ends.

    The client is shared by the session, so a document left open would be one the next test has to
    know about.
    """
    sample = Sample(uri=f"file:///protocol-suite/{name}{kind.extensions[0]}", text=text)
    client.did_open(sample.uri, kind.language_id, sample.text)
    try:
        yield sample
    finally:
        client.did_close(sample.uri)


def _document_params(request: str, uri: str) -> dict[str, Any]:
    """The parameters a document request takes, which is the document and sometimes a position."""
    params: dict[str, Any] = {"textDocument": {"uri": uri}}
    if request in _AT_A_POSITION:
        params["position"] = Position(line=0, character=0).as_protocol()
    return params


def _classification(client: ProtocolClient, sample: Sample) -> tuple[Token, ...]:
    result = client.request(_SEMANTIC_TOKENS, {"textDocument": {"uri": sample.uri}}).unwrap()
    assert result is not None, "the server returned no classification at all"
    return decode_tokens(result["data"])


def _findings(client: ProtocolClient, sample: Sample) -> tuple[Diagnostic, ...]:
    report = client.request(_DIAGNOSTIC, {"textDocument": {"uri": sample.uri}}).unwrap()
    assert report is not None, "the server returned no diagnostic report at all"
    return tuple(Diagnostic.from_protocol(item) for item in report["items"])


def _completion(
    client: ProtocolClient, sample: Sample, position: Position
) -> CompletionAnswer | None:
    result = client.request(
        _COMPLETION,
        {"textDocument": {"uri": sample.uri}, "position": position.as_protocol()},
    ).unwrap()
    return CompletionAnswer.from_protocol(result)


def _hover(client: ProtocolClient, sample: Sample, position: Position) -> Any:
    return client.request(
        _HOVER, {"textDocument": {"uri": sample.uri}, "position": position.as_protocol()}
    ).unwrap()


def _declarations(client: ProtocolClient, sample: Sample, position: Position) -> tuple[Range, ...]:
    result = client.request(
        _DEFINITION, {"textDocument": {"uri": sample.uri}, "position": position.as_protocol()}
    ).unwrap()
    assert result is not None, "the server reported no declaration at all"
    locations = result if isinstance(result, list) else [result]
    for location in locations:
        assert location["uri"] == sample.uri, (
            f"a declaration in this document was reported in {location['uri']}"
        )
    return tuple(Range.from_protocol(location["range"]) for location in locations)


def _source_offers(client: ProtocolClient, kind: DocumentKind) -> tuple[str, ...]:
    """What the source server offers for a sample it is known to answer about."""
    with _opened(client, kind, "model-server/source-unaffected", _SOURCE_SAMPLE) as sample:
        line, character = _SOURCE_SAMPLE_POSITION
        result = client.request(
            _COMPLETION,
            {
                "textDocument": {"uri": sample.uri},
                "position": Position(line=line, character=character).as_protocol(),
            },
        ).unwrap()
        answer = CompletionAnswer.from_protocol(result)
        assert answer is not None, "the source server returned nothing where it answers"
        return answer.labels


# ---------------------------------------------------------------------------
# Classification, checked as a covering of the text
# ---------------------------------------------------------------------------


def coverage_faults(tokens: Sequence[Token], sample: Sample) -> list[str]:
    """Every place the classification fails to be total, named one per fault.

    A token is bounded by a line ending, because the protocol cannot express one that is not, so
    the terminators are the only characters no token selects and every other character must be
    selected exactly once.
    """
    faults: list[str] = []
    for earlier, later in pairwise(tokens):
        if (later.line, later.start) <= (earlier.line, earlier.start):
            faults.append(
                f"token at {later.line}:{later.start} does not follow the one at "
                f"{earlier.line}:{earlier.start}, and the protocol's deltas require document order"
            )

    by_line: dict[int, list[Token]] = defaultdict(list)
    for token in tokens:
        by_line[token.line].append(token)

    for number, line in enumerate(sample.lines):
        width = _utf16_length(line)
        here = sorted(by_line.pop(number, []), key=lambda token: token.start)
        cursor = 0
        for token in here:
            if token.start < cursor:
                faults.append(
                    f"line {number}: the token at {token.start} overlaps the one ending at {cursor}"
                )
            elif token.start > cursor:
                faults.append(
                    f"line {number}: characters {cursor} to {token.start} are classified by nothing"
                )
            cursor = max(cursor, token.end)
        if cursor != width:
            faults.append(
                f"line {number}: classification stops at {cursor} and the line is {width} long"
            )

    for number in sorted(by_line):
        faults.append(
            f"line {number} is not in the document and carries {len(by_line[number])} tokens"
        )
    return faults


def reconstruct(tokens: Sequence[Token], sample: Sample) -> str:
    """What the regions select, with the document's own terminators put back between the lines."""
    by_line: dict[int, list[Token]] = defaultdict(list)
    for token in tokens:
        by_line[token.line].append(token)

    starts = sample.line_starts
    parts: list[str] = []
    for number, (start, end) in enumerate(sample.line_spans):
        line = sample.text[start:end]
        for token in sorted(by_line.get(number, []), key=lambda token: token.start):
            first = _index_within(line, token.start)
            last = _index_within(line, token.end)
            parts.append(line[first:last])
        following = starts[number + 1] if number + 1 < len(starts) else len(sample.text)
        parts.append(sample.text[end:following])
    return "".join(parts)


# ---------------------------------------------------------------------------
# The fixtures, which are model text this file wrote and nothing else
# ---------------------------------------------------------------------------

_PARSEABLE = (
    "Version,\n"
    "  9.4;                     !- Version Identifier\n"
    "\n"
    "Zone,\n"
    "  Office,                  !- Name\n"
    "  0.0,                     !- Direction of Relative North\n"
    "  0.0,                     !- X Origin\n"
    "  0.0,                     !- Y Origin\n"
    "  0.0;                     !- Z Origin\n"
)

# No terminator anywhere: the file somebody is halfway through typing, which is the normal case.
_UNTERMINATED = (
    "Version,\n"
    "  9.4;                     !- Version Identifier\n"
    "\n"
    "Zone,\n"
    "  Office,                  !- Name\n"
    "  0.0\n"
)

# Nothing here says which version this is, so no schema can be resolved for it. The grammar needs
# none, so it classifies anyway.
_NO_VERSION = "Zone,\n  Office,                  !- Name\n  0.0;                     !- X Origin\n"

_BAD_VALUE = "not-a-number"
_BAD_FIELD = (
    "Version,\n"
    "  9.4;                     !- Version Identifier\n"
    "\n"
    "Zone,\n"
    "  Office,                  !- Name\n"
    "  0.0,                     !- Direction of Relative North\n"
    f"  {_BAD_VALUE},            !- X Origin\n"
    "  0.0,                     !- Y Origin\n"
    "  0.0;                     !- Z Origin\n"
)

# The same fault inside a group that repeats, where a range computed by counting fields from the
# start of the statement lands somewhere else entirely.
_BAD_VALUE_IN_GROUP = "not-a-height"
_BAD_FIELD_IN_EXTENSIBLE_GROUP = (
    "Version,\n"
    "  9.4;                     !- Version Identifier\n"
    "\n"
    "Zone,\n"
    "  Office;                  !- Name\n"
    "\n"
    "BuildingSurface:Detailed,\n"
    "  South Wall,              !- Name\n"
    "  Wall,                    !- Surface Type\n"
    "  Exterior Wall,           !- Construction Name\n"
    "  Office,                  !- Zone Name\n"
    "  Outdoors,                !- Outside Boundary Condition\n"
    "  ,                        !- Outside Boundary Condition Object\n"
    "  SunExposed,              !- Sun Exposure\n"
    "  WindExposed,             !- Wind Exposure\n"
    "  autocalculate,           !- View Factor to Ground\n"
    "  4,                       !- Number of Vertices\n"
    "  0.0, 0.0, 3.0,           !- X,Y,Z Vertex 1\n"
    "  0.0, 0.0, 0.0,           !- X,Y,Z Vertex 2\n"
    "  5.0, 0.0, 0.0,           !- X,Y,Z Vertex 3\n"
    f"  5.0, {_BAD_VALUE_IN_GROUP}, 3.0;   !- X,Y,Z Vertex 4\n"
)

# The same fault again, with a comment between the separator and the value. A range that selected
# the comment, or that started at the separator, would be wrong in a way ASCII text hides.
_BAD_VALUE_AFTER_COMMENT = "not-an-origin"
_BAD_FIELD_ACROSS_A_COMMENT = (
    "Version,\n"
    "  9.4;                     !- Version Identifier\n"
    "\n"
    "Zone,\n"
    "  Office,                  !- Name\n"
    "  0.0,                     !- Direction of Relative North\n"
    "  !- the value below is on the far side of this comment\n"
    f"  {_BAD_VALUE_AFTER_COMMENT},           !- X Origin\n"
    "  0.0,                     !- Y Origin\n"
    "  0.0;                     !- Z Origin\n"
)

# A name partly typed at a field that refers to something declared above it. What may go there is
# in the document, so the assertion can name it without this file holding any schema.
_DECLARED_NAME = "Office"
_PARTIAL_REFERENCE = "Off,"
_REFERENCE_FIELD = (
    "Version,\n"
    "  9.4;                     !- Version Identifier\n"
    "\n"
    "Zone,\n"
    f"  {_DECLARED_NAME};                  !- Name\n"
    "\n"
    "BuildingSurface:Detailed,\n"
    "  South Wall,              !- Name\n"
    "  Wall,                    !- Surface Type\n"
    "  Exterior Wall,           !- Construction Name\n"
    f"  {_PARTIAL_REFERENCE}                     !- Zone Name\n"
)

# One name, two objects declaring it. Choosing between them is not this repository's to make.
_TWICE_DECLARED = "Office"
_DECLARATIONS_OF_THE_NAME = 2
_DUPLICATE_DECLARATIONS = (
    "Version,\n"
    "  9.4;                     !- Version Identifier\n"
    "\n"
    "Zone,\n"
    f"  {_TWICE_DECLARED},                  !- Name\n"
    "  0.0;                     !- Direction of Relative North\n"
    "\n"
    "Zone,\n"
    f"  {_TWICE_DECLARED},                  !- Name\n"
    "  90.0;                    !- Direction of Relative North\n"
    "\n"
    "BuildingSurface:Detailed,\n"
    "  South Wall,              !- Name\n"
    "  Wall,                    !- Surface Type\n"
    "  Exterior Wall,           !- Construction Name\n"
    f"  {_TWICE_DECLARED},                  !- Zone Name\n"
)

# A name carrying a character outside the basic plane, which the protocol counts as two units and
# Python as one. Every range in this sample is wrong by one unit if the conversion is skipped.
_ASTRAL_NAME = "Bureau \U0001f3e2 Ouest"
_ASTRAL_TEXT = (
    "Version,\n"
    "  9.4;                     !- Version Identifier\n"
    "\n"
    "Zone,\n"
    f"  {_ASTRAL_NAME},        !- Name\n"
    "  0.0;                     !- Direction of Relative North\n"
    "\n"
    "BuildingSurface:Detailed,\n"
    "  South Wall,              !- Name\n"
    "  Wall,                    !- Surface Type\n"
    "  Exterior Wall,           !- Construction Name\n"
    f"  {_ASTRAL_NAME};        !- Zone Name\n"
)


@pytest.fixture(scope="session")
def model_kind(declaration: Any) -> DocumentKind:
    """The kind of document the model server serves, read from the declaration that assigns it."""
    return declaration.model.documents[0]


@pytest.fixture(scope="session")
def source_kind(declaration: Any) -> DocumentKind:
    return declaration.source.documents[0]


# ---------------------------------------------------------------------------
# T057. Classification is total
# ---------------------------------------------------------------------------


class TestClassify:
    """User story 3, acceptance 2, 3 and 5.

    Runs the day ``@idfkit/language`` is installed; until then the ``model_server`` fixture skips
    these and names the component that is missing.
    """

    def _classify_totally(
        self, client: ProtocolClient, kind: DocumentKind, name: str, text: str
    ) -> None:
        with _opened(client, kind, f"model-server/{name}", text) as sample:
            tokens = _classification(client, sample)
            faults = coverage_faults(tokens, sample)
            assert not faults, f"the classification of {name} is not total:\n" + "\n".join(faults)
            assert reconstruct(tokens, sample) == sample.text, (
                f"what the regions select does not reproduce {name}: a region was added, dropped, "
                "merged, or reclassified on the way through"
            )
            assert all(token.modifiers == 0 for token in tokens), (
                "a token carries a modifier, and the service reports none: it was invented here"
            )

    def test_classify_covers_text_that_parses(
        self, model_server: ProtocolClient, model_kind: DocumentKind
    ) -> None:
        self._classify_totally(model_server, model_kind, "classify-parseable", _PARSEABLE)

    def test_classify_covers_text_missing_a_terminator(
        self, model_server: ProtocolClient, model_kind: DocumentKind
    ) -> None:
        self._classify_totally(model_server, model_kind, "classify-unterminated", _UNTERMINATED)

    def test_classify_covers_text_with_no_determinable_version(
        self, model_server: ProtocolClient, model_kind: DocumentKind
    ) -> None:
        self._classify_totally(model_server, model_kind, "classify-no-version", _NO_VERSION)


# ---------------------------------------------------------------------------
# T058. The other four answers
# ---------------------------------------------------------------------------


class TestAnswers:
    """User story 4, acceptance 1 through 7, at the protocol boundary with no editor.

    Nothing here asserts what a schema says, because holding a copy of that is the one thing this
    repository may not do. What it asserts instead is that an answer selects the characters this
    file put in the fixture, that an absence stays the absence the service reported, and that a
    name declared in the fixture is offered where the fixture refers to it.
    """

    def _selects(
        self, client: ProtocolClient, kind: DocumentKind, name: str, text: str, value: str
    ) -> tuple[Diagnostic, ...]:
        """Every finding, having first required one that selects ``value`` character for
        character."""
        with _opened(client, kind, f"model-server/{name}", text) as sample:
            findings = _findings(client, sample)
            assert findings, f"{name} carries a bad value and the server reported no finding"
            wanted = sample.span_of(value)
            exact = [finding for finding in findings if finding.range == wanted]
            selected = "; ".join(
                f"{finding.range} = {sample.select(finding.range)!r}" for finding in findings
            )
            assert exact, (
                f"no finding selects {value!r} exactly. Wanted {wanted}, and the findings "
                f"selected: {selected}"
            )
            assert all(finding.precision == "field" for finding in exact), (
                "a finding selecting the offending value reports itself as a fallback to the "
                "whole statement, so the precision the service set was not carried through"
            )
            return findings

    def test_answers_a_bad_field_is_selected_character_for_character(
        self, model_server: ProtocolClient, model_kind: DocumentKind
    ) -> None:
        self._selects(model_server, model_kind, "bad-field", _BAD_FIELD, _BAD_VALUE)

    @pytest.mark.xfail(
        strict=True,
        reason=(
            "The language service reports no finding for a bad value inside an extensible group. "
            "Measured against @idfkit/language 0.2.0: findingsIn on this exact text returns one "
            "finding, for the dangling Construction Name reference, and none selecting the "
            "vertex. Nothing this repository may do would close it, because producing the finding "
            "means validating a repeating group against the schema, which is the service's work "
            "and is knowledge Principle I keeps out of here. Delete this marker when the service "
            "reports it; strict, so a fix upstream fails this test rather than passing silently."
        ),
    )
    def test_answers_a_bad_field_inside_an_extensible_group_is_selected_character_for_character(
        self, model_server: ProtocolClient, model_kind: DocumentKind
    ) -> None:
        self._selects(
            model_server,
            model_kind,
            "bad-field-in-group",
            _BAD_FIELD_IN_EXTENSIBLE_GROUP,
            _BAD_VALUE_IN_GROUP,
        )

    def test_answers_a_bad_field_across_a_comment_is_selected_character_for_character(
        self, model_server: ProtocolClient, model_kind: DocumentKind
    ) -> None:
        self._selects(
            model_server,
            model_kind,
            "bad-field-across-a-comment",
            _BAD_FIELD_ACROSS_A_COMMENT,
            _BAD_VALUE_AFTER_COMMENT,
        )

    def test_answers_findings_arrive_on_the_services_own_terms(
        self, model_server: ProtocolClient, model_kind: DocumentKind
    ) -> None:
        """Acceptance 2: nothing here filters, rewords, re-severities, or adds to a finding."""
        findings = self._selects(
            model_server, model_kind, "findings-terms", _BAD_FIELD, _BAD_VALUE
        )

        assert all(finding.message.strip() for finding in findings), (
            "a finding arrived with no message, so something other than the service's own words "
            "reached the client"
        )
        assert all(finding.source is None for finding in findings), (
            "a finding names a source, and who produced it is the language service rather than "
            "this server, which is not a claim this repository is in a position to make"
        )
        assert all(finding.precision in ("field", "statement") for finding in findings), (
            "a finding reached the client without the service's own record of how exactly it is "
            "positioned"
        )

    def test_answers_completion_at_a_reference_field_offers_the_declared_names(
        self, model_server: ProtocolClient, model_kind: DocumentKind
    ) -> None:
        """What may go at a reference field is in the document, so the fixture knows the answer."""
        with _opened(
            model_server, model_kind, "model-server/reference-field", _REFERENCE_FIELD
        ) as sample:
            at_the_partial_name = sample.at(_PARTIAL_REFERENCE, after=len(_PARTIAL_REFERENCE) - 1)

            answer = _completion(model_server, sample, at_the_partial_name)

            assert answer is not None, "the server returned nothing where the schema constrains it"
            assert _DECLARED_NAME in answer.labels, (
                f"{_DECLARED_NAME!r} is declared in this document and was not offered at a field "
                f"that refers to one: {answer.labels}"
            )
            assert not answer.is_incomplete, "a complete answer was marked incomplete"
            assert len(set(answer.labels)) == len(answer.labels), "an offer was made twice"
            for offer in answer.offers:
                assert offer.replaces is not None, (
                    f"the offer {offer.label!r} carries no span to replace, and working one out "
                    "here would need the format's rules"
                )
                assert sample.select(offer.replaces) in sample.text

    def test_answers_completion_where_the_schema_constrains_nothing_is_empty_and_complete(
        self, model_server: ProtocolClient, model_kind: DocumentKind
    ) -> None:
        """Acceptance 3: an empty list, marked complete, and never a local fallback."""
        with _opened(model_server, model_kind, "model-server/unconstrained", _PARSEABLE) as sample:
            inside_a_free_value = sample.at("0.0,                     !- Direction", after=1)

            answer = _completion(model_server, sample, inside_a_free_value)

            assert answer is not None, (
                "the server returned nothing where the schema was consulted and constrained "
                "nothing, which is a different answer from the one it gave"
            )
            assert answer.is_complete_and_empty, (
                "where the schema constrains nothing the answer is an empty list marked complete, "
                f"and this one carried {len(answer.offers)} offers with isIncomplete="
                f"{answer.is_incomplete}"
            )

    def test_answers_no_schema_is_stated_rather_than_answered_as_an_empty_list(
        self, model_server: ProtocolClient, model_kind: DocumentKind
    ) -> None:
        """Acceptance 7: an editor reads a complete empty list as "nothing is permitted here"."""
        with _opened(model_server, model_kind, "model-server/no-schema", _NO_VERSION) as sample:
            at_a_value = sample.at("0.0;", after=1)

            answer = _completion(model_server, sample, at_a_value)

            assert answer is None or not answer.is_complete_and_empty, (
                "no schema could be resolved for this text, and the client was told the schema "
                "permits nothing here instead of being told that plainly"
            )

    def test_answers_hover_off_a_field_returns_nothing(
        self, model_server: ProtocolClient, model_kind: DocumentKind
    ) -> None:
        """Acceptance 4: nothing, rather than the nearest field."""
        with _opened(model_server, model_kind, "model-server/hover-off", _PARSEABLE) as sample:
            off_a_field = {
                "a comment": sample.at("!- Direction of Relative North", after=4),
                "a separator": sample.at("Office,", after=len("Office")),
                "whitespace": sample.at("  0.0,                     !- X Origin", after=1),
            }

            hovers = {
                where: _hover(model_server, sample, position)
                for where, position in off_a_field.items()
            }
            answered = {where: hover for where, hover in hovers.items() if hover is not None}

            assert not answered, (
                "hover answered off a field, which can only be the nearest one: "
                + json.dumps(answered)[:400]
            )

    @pytest.mark.xfail(
        strict=True,
        reason=(
            "The language service yields one declaration for a name declared twice. Measured "
            'against @idfkit/core 0.2.0: parsing reports \'A Zone named "Office" already '
            "exists' and keeps the first, so declarationAt has one to return. Reporting both "
            "means reading declarations out of the text rather than out of the parsed model, "
            "which is the grammar this repository may not hold. Delete this marker when the "
            "service reports both; strict, so a fix upstream fails this test rather than "
            "passing silently."
        ),
    )
    def test_answers_a_name_declared_twice_yields_every_declaration(
        self, model_server: ProtocolClient, model_kind: DocumentKind
    ) -> None:
        """Acceptance 5: every declaration, rather than one chosen here."""
        with _opened(
            model_server, model_kind, "model-server/declared-twice", _DUPLICATE_DECLARATIONS
        ) as sample:
            at_the_reference = sample.position_of(
                sample.text.rindex(_TWICE_DECLARED) + len(_TWICE_DECLARED) - 1
            )

            declarations = _declarations(model_server, sample, at_the_reference)

            assert len(declarations) == _DECLARATIONS_OF_THE_NAME, (
                f"{_TWICE_DECLARED!r} is declared {_DECLARATIONS_OF_THE_NAME} times in this "
                f"document and {len(declarations)} declarations came back"
            )
            assert all(sample.select(span) == _TWICE_DECLARED for span in declarations), (
                "a declaration selects something other than the declared name: "
                + "; ".join(repr(sample.select(span)) for span in declarations)
            )
            assert len(set(declarations)) == len(declarations), (
                "one declaration was reported twice"
            )

    def test_answers_a_range_outside_the_basic_plane_selects_the_right_characters(
        self, model_server: ProtocolClient, model_kind: DocumentKind
    ) -> None:
        """Acceptance 6: the one assertion that would pass by accident on ASCII."""
        assert _utf16_length(_ASTRAL_NAME) != len(_ASTRAL_NAME), (
            "this fixture no longer contains a character outside the basic plane, so it no longer "
            "tells a converted position from an unconverted one"
        )
        with _opened(model_server, model_kind, "model-server/astral", _ASTRAL_TEXT) as sample:
            at_the_reference = sample.position_of(
                sample.text.rindex(_ASTRAL_NAME) + len(_ASTRAL_NAME) - 1
            )

            declarations = _declarations(model_server, sample, at_the_reference)

            assert declarations, "no declaration came back for a name outside the basic plane"
            assert all(sample.select(span) == _ASTRAL_NAME for span in declarations), (
                "a range over text outside the basic plane selects the wrong characters: "
                + "; ".join(repr(sample.select(span)) for span in declarations)
            )


# ---------------------------------------------------------------------------
# T059. The component is absent, and says so
# ---------------------------------------------------------------------------


def _optional_peers() -> tuple[str, ...]:
    """What the model server declares it resolves the language service through.

    Read from the manifest rather than written here, so a message naming a different install than
    the one this server would take is a failure rather than a coincidence.
    """
    manifest = json.loads(_MODEL_MANIFEST.read_text(encoding="utf-8"))
    peers = manifest.get("peerDependencies", {})
    assert peers, f"{_MODEL_MANIFEST} declares no peer for the language service"
    return tuple(sorted(peers))


class TestMissingComponent:
    """User story 3, acceptance 6, and quickstart scenario 7.

    This group passes whether or not the language service is installed, because it is about the
    path where it is not. With the component present there is nothing to report and the server
    must not report anything; with it absent the server must say what to install, in the guard's
    own words, and leave the source server alone.
    """

    def test_missing_component_startup_reports_what_to_install(
        self, model_server_description: ServerDescription
    ) -> None:
        with _started(model_server_description) as model:
            _drain(model, _STARTUP_SECONDS)
            said = _messages(model)
            shown = [message for message in said if message.channel == _SHOW_MESSAGE]

            if not shown:
                # The component resolved. Nothing is missing, so nothing is reported, and the
                # server is up and answering rather than quietly degraded.
                assert not [
                    message
                    for message in said
                    if message.type in (MessageType.ERROR, MessageType.WARNING)
                ], "nothing is missing and the server warned about something anyway"
                assert model.request(_VERSIONS_REQUEST).ok
                return

            assert len(shown) == 1, f"the server showed {len(shown)} messages at startup"
            absence = shown[0]
            assert absence.type == MessageType.WARNING, (
                "an absent component is a warning: it is neither an error, which would say the "
                "server is broken, nor an informational note nobody reads"
            )
            assert "install" in absence.text.lower(), (
                f"the message does not say what to do about it: {absence.text!r}"
            )
            assert any(peer in absence.text for peer in _optional_peers()), (
                "the message names no package this server actually resolves the language service "
                f"through ({', '.join(_optional_peers())}): {absence.text!r}"
            )
            logged = [
                message
                for message in said
                if message.channel == _LOG_MESSAGE and message.text == absence.text
            ]
            assert logged, (
                "the message shown to the user does not appear in the log verbatim, so it was "
                "reworded on the way to one of them rather than being the guard's own words "
                "carried to both"
            )
            assert absence.text not in [
                message.text for message in said if message.type == MessageType.INFO
            ], (
                "the user was shown this wiring's own summary of what it did not advertise, "
                "rather than the message written where the resolution failed"
            )

    def test_missing_component_leaves_the_source_server_answering(
        self,
        model_server_description: ServerDescription,
        source_server: ProtocolClient,
        source_kind: DocumentKind,
    ) -> None:
        """The two servers are separate processes, and this asserts they behave like it."""
        with _started(model_server_description) as model:
            _drain(model, _STARTUP_SECONDS)

            offers = _source_offers(source_server, source_kind)

            assert _SOURCE_SAMPLE_OFFERS in offers, (
                "the source server stopped answering while the model server was reporting the "
                f"absence of the language service: {offers}"
            )
            assert model.process.poll() is None, (
                "the model server exited over an absent component instead of staying up and "
                "saying what to install"
            )


# ---------------------------------------------------------------------------
# T060. Which server serves what, and neither takes the other down
# ---------------------------------------------------------------------------


class TestOwnership:
    """User story 3 acceptance 1, and FR-030.

    Which server an editor starts for a document is decided by the declaration, so the first test
    is that the declaration decides it unambiguously. The rest is what each server does when it is
    handed the other's document, and what each does when the other stops.
    """

    def test_ownership_each_document_kind_belongs_to_exactly_one_server(
        self, declaration: Any
    ) -> None:
        served: dict[str, list[str]] = defaultdict(list)
        for server in declaration.servers:
            for kind in server.documents:
                served[kind.language_id].append(server.id)
                for extension in kind.extensions:
                    served[extension.lower()].append(server.id)

        shared = {name: owners for name, owners in served.items() if len(owners) > 1}

        assert not shared, (
            "a document kind is claimed by more than one server, so which one an editor starts "
            f"for it is undecided: {shared}"
        )
        assert declaration.model.documents and declaration.source.documents, (
            "a server that serves no kind of document cannot be started for one"
        )

    def test_ownership_the_model_server_refuses_a_document_it_does_not_serve(
        self,
        model_server_description: ServerDescription,
        declaration: Any,
        source_kind: DocumentKind,
    ) -> None:
        """Unsupported, never a guess.

        Today every one of these requests is refused because the language service is absent and so
        no handler is registered for it. The assertion is the same in both worlds, which is why it
        is written against the declaration's own list rather than against one request.
        """
        model: ServerDeclaration = declaration.model
        not_ours = f"file:///protocol-suite/ownership/not-mine{source_kind.extensions[0]}"
        requests = sorted(
            capability.request
            for capability in model.capabilities
            if capability.request.startswith(_DOCUMENT_REQUEST_PREFIX)
            and capability.request != _PUBLISHED_DIAGNOSTICS
        )
        assert requests, "the declaration gives the model server no document request to ask for"

        with _started(model_server_description) as client:
            _drain(client, _STARTUP_SECONDS)
            client.did_open(not_ours, source_kind.language_id, _SOURCE_SAMPLE)
            _drain(client)

            answered = [
                request
                for request in requests
                if not client.request(request, _document_params(request, not_ours)).unsupported
            ]

            assert not answered, (
                "the model server answered about a document it does not serve, rather than "
                f"saying so: {', '.join(answered)}"
            )
            assert [message for message in _messages(client) if not_ours in message.text], (
                "the model server said nothing about being handed a document it does not serve, "
                "so an operator reading its output cannot tell it declined to hold it"
            )
            assert client.request(_VERSIONS_REQUEST).ok, (
                "the model server stopped answering the request it does serve after being handed "
                "one it does not"
            )

    def test_ownership_the_source_server_answers_nothing_about_model_text(
        self, source_server: ProtocolClient, model_kind: DocumentKind
    ) -> None:
        """The other direction of acceptance 1, in the only terms this server has for it.

        The source server holds no grammar and no schema table for model text, so what it must not
        do is produce something anyway. Silence here is the answer, and a completion assembled
        from Python bindings would be exactly the plausible wrong answer Principle IV forbids.
        """
        with _opened(source_server, model_kind, "ownership/not-python", _PARSEABLE) as sample:
            at_a_type_name = sample.at("Zone,", after=2)

            hover = _hover(source_server, sample, at_a_type_name)
            completion = _completion(source_server, sample, at_a_type_name)

            assert hover is None, f"the source server explained model text: {json.dumps(hover)}"
            assert completion is None or not completion.offers, (
                "the source server offered completions in model text: "
                f"{'' if completion is None else completion.labels}"
            )

    def test_ownership_the_source_server_serves_on_when_the_model_server_stops(
        self,
        source_server: ProtocolClient,
        source_kind: DocumentKind,
        model_server_description: ServerDescription,
    ) -> None:
        model = ProtocolClient(model_server_description).start()
        try:
            assert model.initialize().ok
            model.initialized()
            assert model.request(_VERSIONS_REQUEST).ok, "the model server never answered at all"
        finally:
            model.stop()

        offers = _source_offers(source_server, source_kind)

        assert _SOURCE_SAMPLE_OFFERS in offers, (
            f"the source server stopped answering when the model server did: {offers}"
        )

    def test_ownership_the_model_server_serves_on_when_the_source_server_stops(
        self,
        source_server_description: ServerDescription,
        model_server_description: ServerDescription,
        declaration: Any,
    ) -> None:
        with _started(model_server_description) as model:
            source = start_server(source_server_description)
            try:
                assert source.request(_VERSIONS_REQUEST).ok, "the source server never answered"
            finally:
                source.stop()

            report = model.request(_VERSIONS_REQUEST).unwrap()

            assert report["server_id"] == declaration.model.id, (
                f"the model server stopped answering when the source server did: {report}"
            )
