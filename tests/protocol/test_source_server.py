"""The source server's behaviour, asked over the protocol rather than through its own functions.

Every assertion here came from ``server/tests/test_server_integration.py``, which spawned the
server itself and read its output through ``fcntl`` and ``select``. Those two make the file
unrunnable on a contributor's Windows machine, and the reader they were part of belonged to one
suite rather than to both servers. The behaviour is unchanged and nothing it asserted has been
weakened; only the client driving it has moved to ``harness.py``, where the model server's suite
reaches it too.

Two things the old file needed are gone with the harness: sleeping after opening a document, and
sleeping after the handshake. Notifications and requests travel one stream in order, so a request
sent after an open is served after it, and the schema load that the second sleep was waiting for
happens before the first answer whether or not anyone waits.

The last group covers ``idfkit-lsp/versions``, which the old file predates.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from idfkit_lsp.capabilities import ServerDeclaration

    from .harness import ProtocolClient

_LANGUAGE_ID = "python"

_VERSIONS_REQUEST = "idfkit-lsp/versions"


def _open(client: ProtocolClient, uri: str, text: str) -> None:
    client.did_open(uri, _LANGUAGE_ID, text)


def _labels(result: Any) -> list[str]:
    """The labels of a completion answer, whichever of the protocol's two shapes it arrived in."""
    items = result.get("items", []) if isinstance(result, dict) else result or []
    return [item["label"] for item in items]


def _complete(client: ProtocolClient, uri: str, line: int, character: int) -> list[str]:
    response = client.request(
        "textDocument/completion",
        {"textDocument": {"uri": uri}, "position": {"line": line, "character": character}},
    )
    return _labels(response.unwrap())


def _hover(client: ProtocolClient, uri: str, line: int, character: int) -> str:
    response = client.request(
        "textDocument/hover",
        {"textDocument": {"uri": uri}, "position": {"line": line, "character": character}},
    )
    result = response.unwrap()
    assert result is not None
    return result["contents"]["value"]


class TestCompletion:
    def test_object_type_completion(self, source_server: ProtocolClient) -> None:
        uri = "file:///test_comp.py"
        _open(
            source_server,
            uri,
            'from idfkit import load_idf\ndoc = load_idf("x.idf")\ndoc["Zon',
        )

        assert "Zone" in _complete(source_server, uri, 2, 8)

    def test_field_attribute_completion(self, source_server: ProtocolClient) -> None:
        uri = "file:///test_field.py"
        _open(
            source_server,
            uri,
            "from idfkit import load_idf\n"
            'doc = load_idf("x.idf")\n'
            'zone = doc["Zone"]["Office"]\n'
            "zone.x_",
        )

        assert "x_origin" in _complete(source_server, uri, 3, 7)

    def test_add_object_type_completion(self, source_server: ProtocolClient) -> None:
        uri = "file:///test_add.py"
        _open(
            source_server,
            uri,
            'from idfkit import load_idf\ndoc = load_idf("x.idf")\ndoc.add("Build',
        )

        assert "Building" in _complete(source_server, uri, 2, 14)


class TestHover:
    def test_hover_on_object_type(self, source_server: ProtocolClient) -> None:
        uri = "file:///test_hover.py"
        _open(
            source_server,
            uri,
            'from idfkit import load_idf\ndoc = load_idf("x.idf")\ndoc["Zone"]',
        )

        content = _hover(source_server, uri, 2, 6)
        assert "Zone" in content
        assert "Thermal Zones" in content

    def test_hover_on_field(self, source_server: ProtocolClient) -> None:
        uri = "file:///test_hover_field.py"
        _open(
            source_server,
            uri,
            "from idfkit import load_idf\n"
            'doc = load_idf("x.idf")\n'
            'zone = doc["Zone"]["Office"]\n'
            "zone.x_origin",
        )

        content = _hover(source_server, uri, 3, 7)
        assert "x_origin" in content
        assert "number" in content


class TestSignatureHelp:
    def test_signature_on_add(self, source_server: ProtocolClient) -> None:
        uri = "file:///test_sig.py"
        _open(
            source_server,
            uri,
            'from idfkit import load_idf\ndoc = load_idf("x.idf")\ndoc.add("Zone", ',
        )

        response = source_server.request(
            "textDocument/signatureHelp",
            {"textDocument": {"uri": uri}, "position": {"line": 2, "character": 16}},
        )
        result = response.unwrap()
        assert result is not None
        signatures = result["signatures"]
        assert len(signatures) > 0
        assert '"Zone"' in signatures[0]["label"]


class TestVersions:
    """What a delivery path actually delivered, asked at the boundary a delivery path can reach.

    A path that named one level and installed another is a failure nobody sees until an answer
    goes missing, so the answer is asserted to name this server and to carry a resolved level for
    at least one library rather than merely to exist.
    """

    def test_the_server_reports_itself_and_the_levels_it_resolved(
        self, source_server: ProtocolClient, declaration: Any
    ) -> None:
        declared: ServerDeclaration = declaration.source

        report = source_server.request(_VERSIONS_REQUEST, None).unwrap()

        assert report["server_id"] == declared.id
        assert report["version"]
        libraries = report["libraries"]
        assert libraries, "the server reported no libraries at all"
        assert all(library["name"] for library in libraries)
        resolved = [library for library in libraries if library["level"]]
        assert resolved, f"no library reported a resolved level: {libraries}"

    def test_the_request_is_the_one_the_declaration_names(self, declaration: Any) -> None:
        declared: ServerDeclaration = declaration.source

        assert _VERSIONS_REQUEST in declared.present_requests
