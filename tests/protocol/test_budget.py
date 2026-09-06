"""What an answer at a cursor costs, measured at the protocol boundary.

SC-012 is about a modeller typing: after one keystroke, an answer should arrive inside one frame at
sixty hertz. The number that matters is therefore what this repository adds on top of the library's
own work, and the place to see it is the protocol boundary, because that is where an editor sees it
too.

**This reports; it does not police.** A developer machine runs tests beside a browser and a build,
so a tight assertion here would fail for reasons that have nothing to do with the code under it.
The ceiling asserted is deliberately far above anything a working server produces: it catches a
handler that has started doing something enormous, and nothing subtler. The figure itself is
printed, and ``make bench-protocol`` runs this file alone with output shown so that the figure is
the point of the run rather than a line scrolled past.

**The edit is one character, sent as one character.** Re-sending a whole document on every
keystroke is the cost this repository could add on its own, and the protocol offers increments
instead, so the measurement uses the increment. Insert and delete alternate, which keeps the
document from growing over the run and measures both directions of an edit.
"""

from __future__ import annotations

import statistics
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import pytest

if TYPE_CHECKING:
    from collections.abc import Sequence

    from idfkit_lsp.capabilities import ServerDeclaration

    from .harness import ProtocolClient

#: Discarded. The first answers pay for a schema load and for whatever the runtime warms up.
WARM_UP = 3

#: Kept. Enough that one scheduling hiccup moves the worst case and not the middle one.
SAMPLES = 20

#: One frame at sixty hertz, which is what SC-012 asks the whole answer to fit inside.
ONE_FRAME_MILLISECONDS = 1000.0 / 60.0

#: Far above a working server and far below a handler that has started doing something enormous.
#: A tighter number would be a flake on a busy machine rather than a finding.
GENEROUS_CEILING_MILLISECONDS = 2000.0

_COMPLETION = "textDocument/completion"


@dataclass(frozen=True)
class Measurement:
    """What one run of the loop saw, in milliseconds."""

    server: str
    request: str
    samples: tuple[float, ...]
    #: How many of those answers carried anything. A timing over an empty answer measures an early
    #: return rather than the work SC-012 is about, so the count is reported beside the figure.
    carrying: int

    @property
    def median(self) -> float:
        return statistics.median(self.samples)

    @property
    def best(self) -> float:
        return min(self.samples)

    @property
    def worst(self) -> float:
        return max(self.samples)

    def report(self) -> str:
        return "\n".join(
            (
                "",
                "=== an answer at a cursor after a single-character edit ===",
                f"  server   {self.server}",
                f"  request  {self.request}",
                f"  samples  {len(self.samples)}",
                f"  median   {self.median:.1f} ms",
                f"  best     {self.best:.1f} ms",
                f"  worst    {self.worst:.1f} ms",
                f"  carrying {self.carrying} of {len(self.samples)} answers held items",
                f"  one frame at 60 Hz is {ONE_FRAME_MILLISECONDS:.1f} ms; this run asserts only "
                f"a ceiling of {GENEROUS_CEILING_MILLISECONDS:.0f} ms",
                "",
            )
        )


@dataclass(frozen=True)
class Cursor:
    """One single-character edit and the position an answer is then asked for."""

    change: dict[str, Any]
    line: int
    character: int

    @classmethod
    def inserting(cls, line: int, character: int, text: str) -> Cursor:
        at = {"line": line, "character": character}
        return cls(
            change={"range": {"start": at, "end": at}, "text": text},
            line=line,
            character=character + len(text),
        )

    @classmethod
    def deleting(cls, line: int, character: int) -> Cursor:
        start = {"line": line, "character": character}
        end = {"line": line, "character": character + 1}
        return cls(
            change={"range": {"start": start, "end": end}, "text": ""},
            line=line,
            character=character,
        )


def _items(result: Any) -> int:
    """How many completions an answer carried, in whichever of the protocol's two shapes it came."""
    if isinstance(result, dict):
        return len(result.get("items") or ())
    return len(result or ())


def measure(
    client: ProtocolClient,
    server: str,
    uri: str,
    language_id: str,
    text: str,
    edits: Sequence[Cursor],
) -> Measurement:
    """Type into an open document one character at a time, timing the answer after each keystroke.

    The timing covers the request alone, but the server processes the edit before it because both
    travel one stream in order. That is the number a typing modeller feels, so it is the number
    reported rather than the handler's own time.
    """
    client.did_open(uri, language_id, text)
    elapsed: list[float] = []
    carrying = 0
    try:
        for index in range(WARM_UP + SAMPLES):
            cursor = edits[index % len(edits)]
            client.did_change(uri, index + 2, changes=[cursor.change])
            started = time.perf_counter()
            response = client.request(
                _COMPLETION,
                {
                    "textDocument": {"uri": uri},
                    "position": {"line": cursor.line, "character": cursor.character},
                },
            )
            taken = (time.perf_counter() - started) * 1000.0
            result = response.unwrap()
            if index >= WARM_UP:
                elapsed.append(taken)
                carrying += 1 if _items(result) else 0
    finally:
        client.did_close(uri)
    return Measurement(
        server=server, request=_COMPLETION, samples=tuple(elapsed), carrying=carrying
    )


class TestAnswerAtACursor:
    def test_the_source_server(self, source_server: ProtocolClient) -> None:
        # The prefix is one character short of a name the schema holds, so each keystroke lands the
        # request in the branch that actually consults the schema rather than in an early return.
        source = 'from idfkit import load_idf\ndoc = load_idf("x.idf")\ndoc["Zon'
        edits = (Cursor.inserting(2, 8, "e"), Cursor.deleting(2, 8))

        measurement = measure(
            source_server,
            server="source",
            uri="file:///budget_source.py",
            language_id="python",
            text=source,
            edits=edits,
        )

        print(measurement.report())
        assert measurement.carrying, "every answer was empty, so nothing was measured"
        assert measurement.median <= GENEROUS_CEILING_MILLISECONDS, (
            f"an answer at a cursor took {measurement.median:.1f} ms on the source server"
        )

    def test_the_model_server(self, model_server: ProtocolClient, declaration: Any) -> None:
        declared: ServerDeclaration = declaration.model
        if _COMPLETION not in declared.present_requests:
            pytest.skip(
                f"the model server does not advertise {_COMPLETION} yet, so there is no answer "
                "at a cursor to measure"
            )
        kind = declared.documents[0]
        edits = (Cursor.inserting(0, 0, "A"), Cursor.deleting(0, 0))

        measurement = measure(
            model_server,
            server="model",
            uri=f"file:///budget_model{kind.extensions[0]}",
            language_id=kind.language_id,
            text="\n",
            edits=edits,
        )

        print(measurement.report())
        assert measurement.median <= GENEROUS_CEILING_MILLISECONDS, (
            f"an answer at a cursor took {measurement.median:.1f} ms on the model server"
        )
