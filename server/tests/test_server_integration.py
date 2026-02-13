"""End-to-end integration tests — spawns the server as a subprocess and talks LSP."""

from __future__ import annotations

import json
import subprocess
import sys
import time

import pytest


def _send_lsp(proc: subprocess.Popen, method: str, params: dict, id: int | None = None) -> None:
    """Send an LSP JSON-RPC message to the server's stdin."""
    msg: dict = {"jsonrpc": "2.0", "method": method, "params": params}
    if id is not None:
        msg["id"] = id
    body = json.dumps(msg)
    header = f"Content-Length: {len(body)}\r\n\r\n"
    proc.stdin.write(header.encode())
    proc.stdin.write(body.encode())
    proc.stdin.flush()


def _read_lsp(proc: subprocess.Popen, timeout: float = 10.0) -> dict | None:
    """Read an LSP JSON-RPC message from the server's stdout."""
    import fcntl
    import os
    import select

    fd = proc.stdout.fileno()
    # Ensure non-blocking
    fl = fcntl.fcntl(fd, fcntl.F_GETFL)
    fcntl.fcntl(fd, fcntl.F_SETFL, fl | os.O_NONBLOCK)

    deadline = time.monotonic() + timeout
    header = b""
    while time.monotonic() < deadline:
        remaining = max(deadline - time.monotonic(), 0)
        ready, _, _ = select.select([proc.stdout], [], [], min(remaining, 0.1))
        if not ready:
            continue
        try:
            ch = os.read(fd, 1)
        except BlockingIOError:
            continue
        if ch == b"":
            return None
        header += ch
        if header.endswith(b"\r\n\r\n"):
            break
    else:
        return None

    # Parse Content-Length
    content_length = 0
    for line in header.decode().split("\r\n"):
        if line.lower().startswith("content-length:"):
            content_length = int(line.split(":")[1].strip())
            break

    if content_length == 0:
        return None

    # Read body
    body = b""
    while len(body) < content_length:
        remaining = max(deadline - time.monotonic(), 0)
        if remaining <= 0:
            return None
        ready, _, _ = select.select([proc.stdout], [], [], min(remaining, 0.1))
        if ready:
            try:
                chunk = os.read(fd, content_length - len(body))
            except BlockingIOError:
                continue
            if chunk == b"":
                return None
            body += chunk

    return json.loads(body)


def _read_response(proc: subprocess.Popen, expected_id: int, timeout: float = 15.0) -> dict | None:
    """Read messages until we find a response with the expected id."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        msg = _read_lsp(proc, timeout=deadline - time.monotonic())
        if msg is None:
            return None
        if msg.get("id") == expected_id:
            return msg
        # Otherwise it's a notification — skip it
    return None


@pytest.fixture(scope="module")
def lsp_server():
    """Spawn the language server subprocess."""
    proc = subprocess.Popen(
        [sys.executable, "-m", "idfkit_lsp"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    # Initialize handshake
    _send_lsp(proc, "initialize", {
        "processId": None,
        "capabilities": {},
        "rootUri": "file:///test",
    }, id=1)

    response = _read_response(proc, 1, timeout=15)
    assert response is not None, "Server did not respond to initialize"
    assert "result" in response, f"Initialize failed: {response}"

    _send_lsp(proc, "initialized", {})
    # Give server time to load schema
    time.sleep(1)

    yield proc

    # Shutdown
    _send_lsp(proc, "shutdown", {}, id=999)
    _read_response(proc, 999, timeout=5)
    _send_lsp(proc, "exit", {})
    proc.wait(timeout=5)


def _open_doc(proc, uri: str, text: str, version: int = 1) -> None:
    _send_lsp(proc, "textDocument/didOpen", {
        "textDocument": {
            "uri": uri,
            "languageId": "python",
            "version": version,
            "text": text,
        }
    })
    # Let the server process the notification
    time.sleep(0.2)


class TestCompletion:
    def test_object_type_completion(self, lsp_server) -> None:
        src = 'from idfkit import load_idf\ndoc = load_idf("x.idf")\ndoc["Zon'
        _open_doc(lsp_server, "file:///test_comp.py", src)

        _send_lsp(lsp_server, "textDocument/completion", {
            "textDocument": {"uri": "file:///test_comp.py"},
            "position": {"line": 2, "character": 8},
        }, id=10)

        resp = _read_response(lsp_server, 10)
        assert resp is not None
        result = resp["result"]
        if isinstance(result, dict):
            items = result.get("items", [])
        else:
            items = result or []
        labels = [i["label"] for i in items]
        assert "Zone" in labels

    def test_field_attribute_completion(self, lsp_server) -> None:
        src = (
            'from idfkit import load_idf\n'
            'doc = load_idf("x.idf")\n'
            'zone = doc["Zone"]["Office"]\n'
            'zone.x_'
        )
        _open_doc(lsp_server, "file:///test_field.py", src)

        _send_lsp(lsp_server, "textDocument/completion", {
            "textDocument": {"uri": "file:///test_field.py"},
            "position": {"line": 3, "character": 7},
        }, id=11)

        resp = _read_response(lsp_server, 11)
        assert resp is not None
        result = resp["result"]
        if isinstance(result, dict):
            items = result.get("items", [])
        else:
            items = result or []
        labels = [i["label"] for i in items]
        assert "x_origin" in labels

    def test_add_object_type_completion(self, lsp_server) -> None:
        src = 'from idfkit import load_idf\ndoc = load_idf("x.idf")\ndoc.add("Build'
        _open_doc(lsp_server, "file:///test_add.py", src)

        _send_lsp(lsp_server, "textDocument/completion", {
            "textDocument": {"uri": "file:///test_add.py"},
            "position": {"line": 2, "character": 14},
        }, id=12)

        resp = _read_response(lsp_server, 12)
        assert resp is not None
        result = resp["result"]
        if isinstance(result, dict):
            items = result.get("items", [])
        else:
            items = result or []
        labels = [i["label"] for i in items]
        assert "Building" in labels


class TestHover:
    def test_hover_on_object_type(self, lsp_server) -> None:
        src = 'from idfkit import load_idf\ndoc = load_idf("x.idf")\ndoc["Zone"]'
        _open_doc(lsp_server, "file:///test_hover.py", src)

        _send_lsp(lsp_server, "textDocument/hover", {
            "textDocument": {"uri": "file:///test_hover.py"},
            "position": {"line": 2, "character": 6},
        }, id=20)

        resp = _read_response(lsp_server, 20)
        assert resp is not None
        result = resp["result"]
        assert result is not None
        content = result["contents"]["value"]
        assert "Zone" in content
        assert "Thermal Zones" in content

    def test_hover_on_field(self, lsp_server) -> None:
        src = (
            'from idfkit import load_idf\n'
            'doc = load_idf("x.idf")\n'
            'zone = doc["Zone"]["Office"]\n'
            'zone.x_origin'
        )
        _open_doc(lsp_server, "file:///test_hover_field.py", src)

        _send_lsp(lsp_server, "textDocument/hover", {
            "textDocument": {"uri": "file:///test_hover_field.py"},
            "position": {"line": 3, "character": 7},
        }, id=21)

        resp = _read_response(lsp_server, 21)
        assert resp is not None
        result = resp["result"]
        assert result is not None
        content = result["contents"]["value"]
        assert "x_origin" in content
        assert "number" in content


class TestSignatureHelp:
    def test_signature_on_add(self, lsp_server) -> None:
        src = 'from idfkit import load_idf\ndoc = load_idf("x.idf")\ndoc.add("Zone", '
        _open_doc(lsp_server, "file:///test_sig.py", src)

        _send_lsp(lsp_server, "textDocument/signatureHelp", {
            "textDocument": {"uri": "file:///test_sig.py"},
            "position": {"line": 2, "character": 16},
        }, id=30)

        resp = _read_response(lsp_server, 30)
        assert resp is not None
        result = resp["result"]
        assert result is not None
        sigs = result["signatures"]
        assert len(sigs) > 0
        assert '"Zone"' in sigs[0]["label"]
