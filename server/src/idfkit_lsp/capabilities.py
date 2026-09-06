"""Typed reader for the repository's one capability declaration.

Both servers, the protocol suite, and the checks learn what is advertised from the root
``capabilities.json`` rather than from a list written beside each handler. A declaration that breaks
one of its own state rules stops the reader here, at load: an editor told that an answer exists when
nobody can give it is worse off than an editor told nothing, so a broken declaration must not reach
a running server.

This module reads a record about the protocol. It holds no schema knowledge and no grammar, and it
deliberately depends on nothing beyond the standard library, because the running server imports it.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from enum import Enum
from functools import lru_cache
from pathlib import Path
from typing import Any

_DECLARATION_FILENAME = "capabilities.json"

# The two servers this repository ships, named by what they serve rather than by their runtime.
_KNOWN_SERVER_IDS = frozenset({"source", "model"})


class CapabilityState(str, Enum):
    """What a server has to say about one protocol request. Three states and no fourth."""

    PRESENT = "present"
    ABSENT_PERMANENT = "absent_permanent"
    ABSENT_TEMPORARY = "absent_temporary"


class DeclarationError(Exception):
    """A capability declaration broke one of its own rules.

    Raised rather than returned so that no caller can carry on with a half-read declaration.
    """


@dataclass(frozen=True)
class Capability:
    """One server's position on one protocol request."""

    request: str
    state: CapabilityState
    reason: str | None = None
    instead: str | None = None
    tracked: str | None = None
    editor_specific: bool = False

    @property
    def is_present(self) -> bool:
        return self.state is CapabilityState.PRESENT


@dataclass(frozen=True)
class DocumentKind:
    """A kind of document a server serves, as the editor identifies it."""

    language_id: str
    extensions: tuple[str, ...]


@dataclass(frozen=True)
class ServerDeclaration:
    """One server: what it runs on, what it serves, and what it answers."""

    id: str
    runtime: str
    documents: tuple[DocumentKind, ...]
    capabilities: tuple[Capability, ...]

    @property
    def present_requests(self) -> frozenset[str]:
        """Every request this server advertises. What the server registers handlers for."""
        return frozenset(c.request for c in self.capabilities if c.is_present)

    @property
    def absent_requests(self) -> frozenset[str]:
        """Every request this server states it does not answer, permanently or for now."""
        return frozenset(c.request for c in self.capabilities if not c.is_present)

    def capability(self, request: str) -> Capability | None:
        """This server's position on ``request``, or ``None`` when it has stated none."""
        for candidate in self.capabilities:
            if candidate.request == request:
                return candidate
        return None


@dataclass(frozen=True)
class CapabilityDeclaration:
    """The whole of ``capabilities.json``."""

    version: int
    servers: tuple[ServerDeclaration, ...]

    def server(self, server_id: str) -> ServerDeclaration:
        for candidate in self.servers:
            if candidate.id == server_id:
                return candidate
        raise DeclarationError(f"server {server_id!r}: rule 'a server id is declared' broken")

    @property
    def source(self) -> ServerDeclaration:
        """The server that serves source files in the first language."""
        return self.server("source")

    @property
    def model(self) -> ServerDeclaration:
        """The server that serves model text."""
        return self.server("model")


def load(path: Path | None = None) -> CapabilityDeclaration:
    """Read and validate a capability declaration, defaulting to the repository root's.

    Cached on the resolved path and its modification time, so a server that consults the
    declaration on every request pays for reading and validating it once, while a long-lived
    process that outlives an edit to the file reads the edit rather than a stale answer.
    """
    resolved = (path if path is not None else _default_path()).resolve()
    try:
        stamp = resolved.stat().st_mtime_ns
    except OSError:
        # An unreadable path is reported by _read, in its own words, rather than here.
        stamp = 0
    return _load_resolved(resolved, stamp)


@lru_cache
def _load_resolved(path: Path, stamp: int) -> CapabilityDeclaration:
    return _parse(path, _read(path))


def _default_path() -> Path:
    """The root declaration, found by walking up from this file rather than from the cwd.

    Resolved from the file so that the loader behaves the same whether the server was started from
    the repository root, from ``server/``, or from wherever an editor happened to launch it.
    """
    here = Path(__file__).resolve()
    for candidate in here.parents:
        found = candidate / _DECLARATION_FILENAME
        if found.is_file():
            return found
    raise DeclarationError(f"no {_DECLARATION_FILENAME} above {here}")


def _read(path: Path) -> Any:
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        raise DeclarationError(f"{path}: the capability declaration is missing") from None
    except OSError as exc:
        raise DeclarationError(f"{path}: cannot be read: {exc}") from None
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise DeclarationError(
            f"{path}: not valid JSON: line {exc.lineno}, column {exc.colno}: {exc.msg}"
        ) from None


def _parse(path: Path, raw: Any) -> CapabilityDeclaration:
    where = str(path)
    root = _mapping(raw, where, "the declaration")
    version = root.get("version")
    if not isinstance(version, int) or isinstance(version, bool):
        raise DeclarationError(f"{where}: rule 'version is an integer' broken")
    servers = tuple(
        _parse_server(where, item) for item in _sequence(root.get("servers"), where, "servers")
    )
    _check_documents_disjoint(where, servers)
    _check_server_set(where, servers)
    return CapabilityDeclaration(version=version, servers=servers)


def _parse_server(where: str, raw: Any) -> ServerDeclaration:
    data = _mapping(raw, where, "a server entry")
    server_id = _text(data.get("id"), where, "a server entry", "id")
    subject = f"server {server_id!r}"
    runtime = _text(data.get("runtime"), where, subject, "runtime")
    documents = tuple(
        _parse_document(where, server_id, item)
        for item in _sequence(data.get("documents"), where, f"{subject}: documents")
    )
    if not documents:
        raise DeclarationError(
            f"{where}: {subject}: rule 'a server serves a document kind' broken"
        )
    capabilities = tuple(
        _parse_capability(where, server_id, item)
        for item in _sequence(data.get("capabilities"), where, f"{subject}: capabilities")
    )
    if not capabilities:
        raise DeclarationError(
            f"{where}: {subject}: rule 'a server states a position on some request' broken"
        )
    seen: set[str] = set()
    for capability in capabilities:
        if capability.request in seen:
            raise DeclarationError(
                f"{where}: {subject}, request {capability.request!r}: "
                "rule 'a request appears once per server' broken"
            )
        seen.add(capability.request)
    return ServerDeclaration(
        id=server_id, runtime=runtime, documents=documents, capabilities=capabilities
    )


def _parse_document(where: str, server_id: str, raw: Any) -> DocumentKind:
    subject = f"server {server_id!r}"
    data = _mapping(raw, where, f"{subject}: a document kind")
    language_id = _text(data.get("language_id"), where, subject, "language_id")
    extensions = tuple(
        _text(item, where, f"{subject}, language id {language_id!r}", "extension")
        for item in _sequence(data.get("extensions"), where, f"{subject}: extensions")
    )
    if not extensions:
        raise DeclarationError(
            f"{where}: {subject}, language id {language_id!r}: "
            "rule 'a document kind names an extension' broken"
        )
    return DocumentKind(language_id=language_id, extensions=extensions)


def _parse_capability(where: str, server_id: str, raw: Any) -> Capability:
    subject = f"server {server_id!r}"
    data = _mapping(raw, where, f"{subject}: a capability")
    request = _text(data.get("request"), where, subject, "request")
    subject = f"{subject}, request {request!r}"
    raw_state = _text(data.get("state"), where, subject, "state")
    try:
        state = CapabilityState(raw_state)
    except ValueError:
        known = ", ".join(sorted(member.value for member in CapabilityState))
        raise DeclarationError(
            f"{where}: {subject}: rule 'state is one of {known}' broken: {raw_state!r}"
        ) from None
    reason = _optional_text(data.get("reason"), where, subject, "reason")
    instead = _optional_text(data.get("instead"), where, subject, "instead")
    tracked = _optional_text(data.get("tracked"), where, subject, "tracked")
    editor_specific = data.get("editor_specific", False)
    if not isinstance(editor_specific, bool):
        raise DeclarationError(f"{where}: {subject}: rule 'editor_specific is a boolean' broken")

    # A permanent absence that says neither why nor what to use instead is the silence this whole
    # declaration exists to end, so it fails at load rather than reaching a reader.
    if state is CapabilityState.ABSENT_PERMANENT:
        if reason is None:
            raise DeclarationError(
                f"{where}: {subject}: rule 'absent_permanent states a reason' broken"
            )
        if instead is None:
            raise DeclarationError(
                f"{where}: {subject}: rule 'absent_permanent names what to use instead' broken"
            )
    elif state is CapabilityState.ABSENT_TEMPORARY:
        if tracked is None:
            raise DeclarationError(
                f"{where}: {subject}: rule 'absent_temporary names the tracked item' broken"
            )
    else:
        carried = [
            name
            for name, value in (("reason", reason), ("instead", instead), ("tracked", tracked))
            if value is not None
        ]
        if carried:
            raise DeclarationError(
                f"{where}: {subject}: rule 'present carries no reason, instead, or tracked' "
                f"broken: carries {', '.join(carried)}"
            )
    return Capability(
        request=request,
        state=state,
        reason=reason,
        instead=instead,
        tracked=tracked,
        editor_specific=editor_specific,
    )


def _check_documents_disjoint(where: str, servers: tuple[ServerDeclaration, ...]) -> None:
    """No document kind may be claimed twice: the client routes on exactly one owner."""
    language_owner: dict[str, str] = {}
    extension_owner: dict[str, str] = {}
    for server in servers:
        for document in server.documents:
            owner = language_owner.get(document.language_id)
            if owner is not None:
                raise DeclarationError(
                    f"{where}: servers {owner!r} and {server.id!r}: "
                    f"rule 'one server per language id' broken: {document.language_id!r}"
                )
            language_owner[document.language_id] = server.id
            for extension in document.extensions:
                holder = extension_owner.get(extension)
                if holder is not None:
                    raise DeclarationError(
                        f"{where}: servers {holder!r} and {server.id!r}: "
                        f"rule 'one server per extension' broken: {extension!r}"
                    )
                extension_owner[extension] = server.id


def _check_server_set(where: str, servers: tuple[ServerDeclaration, ...]) -> None:
    if len(servers) < 2:
        raise DeclarationError(
            f"{where}: rule 'two servers are declared, one per document kind' broken: "
            f"{len(servers)} declared"
        )
    for server in servers:
        if server.id not in _KNOWN_SERVER_IDS:
            known = ", ".join(sorted(_KNOWN_SERVER_IDS))
            raise DeclarationError(
                f"{where}: server {server.id!r}: rule 'a server id is one of {known}' broken"
            )
    declared = {server.id for server in servers}
    if declared != _KNOWN_SERVER_IDS:
        missing = ", ".join(sorted(_KNOWN_SERVER_IDS - declared))
        raise DeclarationError(
            f"{where}: rule 'each server id is declared once' broken: {missing} is not declared"
        )
    # "Once" is both halves: every id declared, and none of them twice. A set of ids alone cannot
    # tell a third entry repeating one apart from two entries covering both.
    if len(declared) != len(servers):
        raise DeclarationError(
            f"{where}: rule 'each server id is declared once' broken: "
            f"{len(servers)} entries declare {len(declared)} ids"
        )


def _mapping(value: Any, where: str, subject: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise DeclarationError(f"{where}: {subject}: rule 'is a JSON object' broken")
    return value


def _sequence(value: Any, where: str, subject: str) -> list[Any]:
    if not isinstance(value, list):
        raise DeclarationError(f"{where}: {subject}: rule 'is a JSON array' broken")
    return value


def _text(value: Any, where: str, subject: str, key: str) -> str:
    if not isinstance(value, str) or not value:
        raise DeclarationError(f"{where}: {subject}: rule '{key} is a non-empty string' broken")
    return value


def _optional_text(value: Any, where: str, subject: str, key: str) -> str | None:
    if value is None:
        return None
    return _text(value, where, subject, key)
