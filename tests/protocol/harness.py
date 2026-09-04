"""A portable stdio client for the Language Server Protocol.

One suite drives both servers, so the client that drives them belongs to neither. It spawns a
server as a subprocess, writes protocol messages to its standard input, and reads protocol
messages back from its standard output.

Reading is done by a blocking reader on a daemon thread feeding a queue. The harness this
replaces used ``fcntl`` and ``select``, which made every protocol test unrunnable on a
contributor's Windows machine; a blocking read on a thread costs one thread and runs everywhere.

The harness's own surface is typed: a server is described by :class:`ServerDescription` and an
answer arrives as a :class:`Response`. What travels over the wire stays a dictionary, because it
is protocol JSON and giving it a second shape here would be this repository holding a copy of the
protocol's own types.

A timeout is the expensive failure, so it is never silent: :class:`ProtocolTimeout` carries what
the server wrote to its standard error and whether it is still running.
"""

from __future__ import annotations

import contextlib
import json
import os
import queue
import subprocess
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from enum import IntEnum
from typing import IO, TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from pathlib import Path
    from types import TracebackType

DEFAULT_TIMEOUT = 15.0
"""Long enough for a server loading a schema on its first request, short enough to fail a run."""

_STDERR_LINES_KEPT = 80
_SHUTDOWN_TIMEOUT = 2.0
_TERMINATE_TIMEOUT = 5.0


class ErrorCode(IntEnum):
    """JSON-RPC and protocol error codes the suite asserts on by name rather than by number."""

    PARSE_ERROR = -32700
    INVALID_REQUEST = -32600
    METHOD_NOT_FOUND = -32601
    INVALID_PARAMS = -32602
    INTERNAL_ERROR = -32603
    SERVER_NOT_INITIALIZED = -32002
    REQUEST_FAILED = -32803


class ProtocolError(RuntimeError):
    """A server did something the protocol does not allow, or could not be spoken to at all."""


class ProtocolTimeout(ProtocolError):
    """A server did not answer in time. Carries the server's own output in its message."""


@dataclass(frozen=True)
class ServerDescription:
    """How to start one server, and what to call it when it misbehaves."""

    name: str
    command: str
    args: tuple[str, ...] = ()
    cwd: Path | None = None
    # Excluded from comparison so that a description carrying an environment overlay stays
    # hashable; two servers are the same server when their command line and directory match.
    env: Mapping[str, str] | None = field(default=None, compare=False)

    @property
    def argv(self) -> list[str]:
        return [self.command, *self.args]

    def environment(self) -> dict[str, str]:
        """The spawned process's environment: the caller's, with this description's overlay."""
        merged = dict(os.environ)
        if self.env is not None:
            merged.update(self.env)
        return merged


@dataclass(frozen=True)
class Response:
    """One answer to one request, either a result or an error, never both."""

    id: int
    method: str
    result: Any = None
    error: dict[str, Any] | None = None

    @property
    def ok(self) -> bool:
        return self.error is None

    @property
    def error_code(self) -> int | None:
        if self.error is None:
            return None
        code = self.error.get("code")
        return code if isinstance(code, int) else None

    @property
    def error_message(self) -> str:
        if self.error is None:
            return ""
        message = self.error.get("message")
        return message if isinstance(message, str) else ""

    @property
    def unsupported(self) -> bool:
        """Whether the server refused the method outright rather than answering emptily.

        The declaration's absent states are asserted with this: a request a server does not
        advertise must come back as a refusal, not as a plausible empty answer.
        """
        return self.error_code == ErrorCode.METHOD_NOT_FOUND

    def unwrap(self) -> Any:
        """The result, or a failure naming the error, so a test never asserts against ``None``."""
        if self.error is not None:
            raise ProtocolError(f"{self.method} failed: {self.error}")
        return self.result


@dataclass(frozen=True)
class Notification:
    """One message a server sent unprompted, such as a set of published diagnostics."""

    method: str
    params: Any = None


def _read_message(stream: IO[bytes]) -> dict[str, Any] | None:
    """Read one framed protocol message, blocking until it arrives. ``None`` at end of output.

    The body is read in a loop because a pipe may hand it over in pieces, which is the case a
    fixed-size read gets away with on small messages and fails on a large classification.
    """
    content_length = -1
    while True:
        line = stream.readline()
        if not line:
            return None
        if line in (b"\r\n", b"\n"):
            break
        name, separator, value = line.decode("ascii", "replace").partition(":")
        if separator and name.strip().lower() == "content-length":
            try:
                content_length = int(value.strip())
            except ValueError:
                raise ProtocolError(f"unreadable Content-Length: {line!r}") from None
    if content_length < 0:
        raise ProtocolError("a message arrived with no Content-Length header")
    body = bytearray()
    while len(body) < content_length:
        chunk = stream.read(content_length - len(body))
        if not chunk:
            return None
        body.extend(chunk)
    try:
        return json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProtocolError(f"message body is not JSON: {exc}") from None


class ProtocolClient:
    """A protocol client over one server subprocess. Use it as a context manager."""

    def __init__(self, description: ServerDescription) -> None:
        self.description = description
        self.initialize_result: dict[str, Any] | None = None
        self._process: subprocess.Popen[bytes] | None = None
        self._incoming: queue.Queue[dict[str, Any] | None] = queue.Queue()
        self._stderr: deque[str] = deque(maxlen=_STDERR_LINES_KEPT)
        self._responses: dict[int, Response] = {}
        self._pending: dict[int, str] = {}
        self._notifications: list[Notification] = []
        self._output_ended = False
        self._next_id = 0

    # -- lifetime ---------------------------------------------------------

    def start(self) -> ProtocolClient:
        if self._process is not None:
            raise ProtocolError(f"{self.description.name}: already started")
        try:
            process = subprocess.Popen(
                self.description.argv,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=str(self.description.cwd) if self.description.cwd is not None else None,
                env=self.description.environment(),
            )
        except OSError as exc:
            raise ProtocolError(
                f"{self.description.name}: cannot start {' '.join(self.description.argv)}: {exc}"
            ) from None
        self._process = process
        threading.Thread(target=self._read_output, args=(process.stdout,), daemon=True).start()
        threading.Thread(target=self._read_errors, args=(process.stderr,), daemon=True).start()
        return self

    def __enter__(self) -> ProtocolClient:
        return self.start()

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.stop()

    def stop(self) -> int | None:
        """End the session, then guarantee the process is gone however the test finished.

        Asked to leave first, terminated next, killed last. A failing test must not leave a
        server behind holding a pipe open, and it must not hang the run waiting for one.
        """
        process = self._process
        if process is None:
            return None
        if process.poll() is None:
            with contextlib.suppress(ProtocolError, OSError):
                self.request("shutdown", None, timeout=_SHUTDOWN_TIMEOUT)
            with contextlib.suppress(ProtocolError, OSError):
                self.notify("exit", None)
        try:
            process.wait(timeout=_TERMINATE_TIMEOUT)
        except subprocess.TimeoutExpired:
            process.terminate()
            try:
                process.wait(timeout=_TERMINATE_TIMEOUT)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
        for pipe in (process.stdin, process.stdout, process.stderr):
            if pipe is not None:
                with contextlib.suppress(OSError):
                    pipe.close()
        return process.returncode

    @property
    def process(self) -> subprocess.Popen[bytes]:
        if self._process is None:
            raise ProtocolError(f"{self.description.name}: not started")
        return self._process

    @property
    def stderr_text(self) -> str:
        """What the server has written to its standard error so far, most recent lines kept."""
        return "".join(self._stderr)

    # -- protocol ---------------------------------------------------------

    def initialize(
        self,
        capabilities: dict[str, Any] | None = None,
        *,
        root_uri: str | None = None,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> Response:
        """Send ``initialize`` and keep the result, so a test can read what was advertised."""
        response = self.request(
            "initialize",
            {
                "processId": None,
                "clientInfo": {"name": "idfkit-lsp protocol suite"},
                "capabilities": capabilities if capabilities is not None else {},
                "rootUri": root_uri,
            },
            timeout=timeout,
        )
        if response.ok and isinstance(response.result, dict):
            self.initialize_result = response.result
        return response

    def initialized(self) -> None:
        self.notify("initialized", {})

    @property
    def server_capabilities(self) -> dict[str, Any]:
        """What the server said it answers. Empty until ``initialize`` has succeeded."""
        if self.initialize_result is None:
            return {}
        advertised = self.initialize_result.get("capabilities")
        return advertised if isinstance(advertised, dict) else {}

    def request(
        self, method: str, params: Any = None, timeout: float = DEFAULT_TIMEOUT
    ) -> Response:
        request_id = self._new_id()
        self._pending[request_id] = method
        self._write({"jsonrpc": "2.0", "id": request_id, "method": method, "params": params})
        return self._await_response(request_id, method, timeout)

    def notify(self, method: str, params: Any = None) -> None:
        self._write({"jsonrpc": "2.0", "method": method, "params": params})

    def did_open(self, uri: str, language_id: str, text: str, version: int = 1) -> None:
        self.notify(
            "textDocument/didOpen",
            {
                "textDocument": {
                    "uri": uri,
                    "languageId": language_id,
                    "version": version,
                    "text": text,
                }
            },
        )

    def did_change(
        self,
        uri: str,
        version: int,
        text: str | None = None,
        *,
        changes: Sequence[dict[str, Any]] | None = None,
    ) -> None:
        """Change a document, either wholesale (``text``) or incrementally (``changes``).

        Both forms exist because a server that negotiates incremental synchronisation must be
        driven incrementally to be tested as it is actually used.
        """
        if (text is None) == (changes is None):
            raise ProtocolError("did_change takes exactly one of text or changes")
        content_changes = list(changes) if changes is not None else [{"text": text}]
        self.notify(
            "textDocument/didChange",
            {
                "textDocument": {"uri": uri, "version": version},
                "contentChanges": content_changes,
            },
        )

    def did_close(self, uri: str) -> None:
        self.notify("textDocument/didClose", {"textDocument": {"uri": uri}})

    def shutdown(self, timeout: float = DEFAULT_TIMEOUT) -> Response:
        return self.request("shutdown", None, timeout=timeout)

    def exit(self) -> None:
        self.notify("exit", None)

    def await_notification(self, method: str, timeout: float = DEFAULT_TIMEOUT) -> Notification:
        """Wait for one unprompted message, such as published diagnostics.

        Consuming, and it searches what has already arrived first: a notification a server sent
        while an earlier request was in flight is still the notification the test is waiting for.
        """
        deadline = time.monotonic() + timeout
        while True:
            for index, notification in enumerate(self._notifications):
                if notification.method == method:
                    return self._notifications.pop(index)
            if not self._pump(deadline):
                raise ProtocolTimeout(self._unanswered(f"a {method} notification", timeout))

    @property
    def received_notifications(self) -> tuple[Notification, ...]:
        """Everything unprompted that has arrived and not been consumed."""
        return tuple(self._notifications)

    # -- plumbing ---------------------------------------------------------

    def _new_id(self) -> int:
        self._next_id += 1
        return self._next_id

    def _write(self, message: dict[str, Any]) -> None:
        body = json.dumps(message).encode("utf-8")
        stdin = self.process.stdin
        if stdin is None:
            raise ProtocolError(f"{self.description.name}: no standard input")
        try:
            stdin.write(f"Content-Length: {len(body)}\r\n\r\n".encode("ascii"))
            stdin.write(body)
            stdin.flush()
        except (BrokenPipeError, ValueError, OSError):
            method = message.get("method", "a message")
            raise ProtocolError(
                f"{self.description.name}: cannot send {method}{self._diagnosis()}"
            ) from None

    def _await_response(self, request_id: int, method: str, timeout: float) -> Response:
        deadline = time.monotonic() + timeout
        while request_id not in self._responses:
            if not self._pump(deadline):
                raise ProtocolTimeout(
                    self._unanswered(f"a response to {method} (request {request_id})", timeout)
                )
        self._pending.pop(request_id, None)
        return self._responses.pop(request_id)

    def _pump(self, deadline: float) -> bool:
        """Route one incoming message. False when the deadline passed or the output ended."""
        if self._output_ended:
            return False
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return False
        try:
            message = self._incoming.get(timeout=remaining)
        except queue.Empty:
            return False
        if message is None:
            self._output_ended = True
            return False
        self._route(message)
        return True

    def _route(self, message: dict[str, Any]) -> None:
        message_id = message.get("id")
        method = message.get("method")
        if method is not None and message_id is not None:
            # A server asking the client for something. Nothing here needs an answer with
            # substance, but leaving it unanswered would let a server block on its own request.
            self._write({"jsonrpc": "2.0", "id": message_id, "result": None})
            return
        if method is not None:
            self._notifications.append(Notification(method=method, params=message.get("params")))
            return
        if isinstance(message_id, int):
            error = message.get("error")
            self._responses[message_id] = Response(
                id=message_id,
                method=self._pending.get(message_id, "(unknown request)"),
                result=message.get("result"),
                error=error if isinstance(error, dict) else None,
            )

    def _unanswered(self, wanted: str, timeout: float) -> str:
        """Why nothing arrived, said out loud.

        A harness that reports only that it waited leaves a maintainer to rediscover the server's
        own explanation by hand, and the explanation is usually one line on standard error.
        """
        if self._output_ended:
            reason = f"waited for {wanted} and the server closed its output"
        else:
            reason = f"waited {timeout:g}s for {wanted} and nothing arrived"
        return f"{self.description.name}: {reason}{self._diagnosis()}"

    def _diagnosis(self) -> str:
        """What the server was doing when it failed to answer, appended to every failure."""
        process = self._process
        if process is None:
            return ". The server was never started."
        code = process.poll()
        state = "is still running" if code is None else f"has exited with code {code}"
        errors = self.stderr_text.strip()
        if not errors:
            return f". The server {state} and wrote nothing to its standard error."
        return f". The server {state}. Its standard error:\n{errors}"

    def _read_output(self, stream: IO[bytes] | None) -> None:
        if stream is None:
            self._incoming.put(None)
            return
        try:
            while True:
                message = _read_message(stream)
                if message is None:
                    break
                self._incoming.put(message)
        except (ProtocolError, OSError, ValueError):
            pass
        finally:
            self._incoming.put(None)

    def _read_errors(self, stream: IO[bytes] | None) -> None:
        if stream is None:
            return
        try:
            for line in stream:
                self._stderr.append(line.decode("utf-8", "replace"))
        except (OSError, ValueError):
            pass


def start_server(description: ServerDescription) -> ProtocolClient:
    """Spawn a server and complete the handshake, returning a client ready to be asked things."""
    client = ProtocolClient(description).start()
    response = client.initialize()
    if not response.ok:
        client.stop()
        raise ProtocolError(f"{description.name}: initialize failed: {response.error}")
    client.initialized()
    return client
