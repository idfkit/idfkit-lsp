"""pygls Language Server wiring — connects all providers to LSP protocol handlers.

What this server advertises is read from the repository's capability declaration rather than
written beside each handler: a handler defined here is registered only where ``capabilities.json``
marks its request present for the source server, and a request the declaration marks present with
no handler behind it stops the server at startup. An editor is therefore never told this server
answers something nobody here answers, and never told it stays silent about something it in fact
handles.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from importlib import metadata
from typing import TYPE_CHECKING, Any, TypeVar

from lsprotocol import types
from pygls.lsp.server import LanguageServer

from idfkit_lsp import capabilities
from idfkit_lsp.completion import build_completion_items, detect_completion_context
from idfkit_lsp.document_state import DocumentStateManager
from idfkit_lsp.hover import build_hover_content, detect_hover_target
from idfkit_lsp.schema_cache import SchemaCache
from idfkit_lsp.signature_help import build_signature_help, detect_add_call

if TYPE_CHECKING:
    from collections.abc import Callable

log = logging.getLogger(__name__)

#: The installed distribution this server is delivered as. Its metadata answers both what level
#: this server runs at and which libraries it resolves, so neither is written down here.
DISTRIBUTION = "idfkit-lsp"

#: Custom request by which a delivery path can be asked what it actually delivered.
VERSIONS_REQUEST = "idfkit-lsp/versions"

_DOCUMENTATION_COMMAND = "idfkit.openDocumentation"


# ---------------------------------------------------------------------------
# Levels, read from the installed distribution rather than written here
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class LibraryLevel:
    """One library this server resolved, and the level it resolved to.

    ``level`` is ``None`` where the library has no installed distribution to ask, because a level
    this server cannot read is one it must not invent.
    """

    name: str
    level: str | None


@dataclass(frozen=True)
class VersionReport:
    """This server's answer to ``idfkit-lsp/versions``: what it is, and what it read from."""

    server_id: str
    version: str | None
    libraries: tuple[LibraryLevel, ...]


def _level(distribution: str) -> str | None:
    try:
        return metadata.version(distribution)
    except metadata.PackageNotFoundError:
        return None


def _requirement_name(requirement: str) -> str:
    """The distribution name at the head of a requirement string, without its version or extras."""
    head = requirement.split(";", 1)[0]
    for separator in ("[", "(", "=", "<", ">", "!", "~", " "):
        head = head.split(separator, 1)[0]
    return head.strip()


def _belongs_to_an_extra(requirement: str) -> bool:
    """Whether a requirement is only installed for an extra, and so is not imported by a run."""
    _, _, marker = requirement.partition(";")
    return "extra" in marker


def _resolved_libraries() -> tuple[LibraryLevel, ...]:
    """Every library this server imports, with the level each one actually resolved to.

    The names come from this server's own distribution metadata rather than from a list in this
    file, so a dependency added or renamed is reported without anyone editing the report.
    """
    try:
        declared = metadata.requires(DISTRIBUTION) or ()
    except metadata.PackageNotFoundError:
        declared = ()
    names = {
        _requirement_name(requirement)
        for requirement in declared
        if not _belongs_to_an_extra(requirement)
    }
    return tuple(LibraryLevel(name=name, level=_level(name)) for name in sorted(names) if name)


_DECLARED = capabilities.load().source

server = LanguageServer(DISTRIBUTION, _level(DISTRIBUTION) or "unknown")


# ---------------------------------------------------------------------------
# Logging bridge: forward Python logging → LSP window/logMessage
# ---------------------------------------------------------------------------

_LOG_LEVEL_TO_MESSAGE_TYPE = {
    logging.DEBUG: types.MessageType.Log,
    logging.INFO: types.MessageType.Info,
    logging.WARNING: types.MessageType.Warning,
    logging.ERROR: types.MessageType.Error,
    logging.CRITICAL: types.MessageType.Error,
}


class _LspLogHandler(logging.Handler):
    """Forwards Python log records to the LSP client via ``window/logMessage``."""

    def __init__(self, ls: LanguageServer) -> None:
        super().__init__()
        self._ls = ls

    def emit(self, record: logging.LogRecord) -> None:
        try:
            msg = self.format(record)
            msg_type = _LOG_LEVEL_TO_MESSAGE_TYPE.get(record.levelno, types.MessageType.Log)
            self._ls.window_log_message(types.LogMessageParams(type=msg_type, message=msg))
        except Exception:
            self.handleError(record)


# These are initialised in the ``initialized`` handler once the client is ready.
_schema: SchemaCache | None = None
_docs: DocumentStateManager | None = None


# ---------------------------------------------------------------------------
# Registration: the declaration decides, this file only supplies the handlers
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _Registration:
    """A handler this file supplies for one request, and how pygls is told about it."""

    request: str
    function: Callable[..., Any]
    options: Any | None = None
    command: str | None = None


@dataclass(frozen=True)
class Advertisement:
    """What the declaration made of the handlers this file supplies."""

    registered: tuple[str, ...]
    skipped: tuple[str, ...]

    def describe(self) -> str:
        registered = ", ".join(self.registered) or "nothing"
        skipped = ", ".join(self.skipped) or "nothing"
        return f"advertised from the declaration: {registered}; not advertised: {skipped}"


_REGISTRATIONS: dict[str, _Registration] = {}

_HandlerT = TypeVar("_HandlerT", bound="Callable[..., Any]")


def _handles(
    request: str,
    *,
    options: Any | None = None,
    command: str | None = None,
) -> Callable[[_HandlerT], _HandlerT]:
    """Supply a handler for one request without advertising it.

    Advertising is done once, from the declaration, by :func:`_advertise`. Nothing this module
    defines reaches the editor except through that function.
    """

    def record(function: _HandlerT) -> _HandlerT:
        if request in _REGISTRATIONS:
            raise RuntimeError(f"{request!r} has two handlers in {__name__}")
        _REGISTRATIONS[request] = _Registration(
            request=request, function=function, options=options, command=command
        )
        return function

    return record


def _advertise(declared: capabilities.ServerDeclaration) -> Advertisement:
    """Register exactly the requests the declaration marks present for this server."""
    advertised = declared.present_requests
    for request in sorted(advertised):
        registration = _REGISTRATIONS.get(request)
        if registration is None:
            raise RuntimeError(
                f"the capability declaration marks {request!r} present for the "
                f"{declared.id!r} server, but no handler is registered for it: an editor would "
                "be told an answer exists that nothing here gives"
            )
        if registration.command is not None:
            # A command is advertised through pygls' executeCommandProvider rather than as a
            # feature, so the declaration gates the command registration itself.
            server.command(registration.command)(registration.function)
        elif registration.options is not None:
            server.feature(registration.request, registration.options)(registration.function)
        else:
            server.feature(registration.request)(registration.function)
    skipped = declared.absent_requests | (set(_REGISTRATIONS) - advertised)
    return Advertisement(registered=tuple(sorted(advertised)), skipped=tuple(sorted(skipped)))


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------

# Lifecycle and document synchronisation are not advertised capabilities: an editor sends them to
# every server it starts, and a server that ignored them would hold no documents to answer about.
# They are therefore registered unconditionally, outside the declaration's gate.


@server.feature(types.INITIALIZED)
def on_initialized(params: types.InitializedParams) -> None:
    global _schema, _docs

    # Attach the LSP log handler so Python logs appear in the client output panel.
    # Only forward INFO and above over LSP; DEBUG stays on stderr only.
    lsp_handler = _LspLogHandler(server)
    lsp_handler.setFormatter(logging.Formatter("%(name)s: %(message)s"))
    lsp_handler.setLevel(logging.INFO)
    root = logging.getLogger("idfkit_lsp")
    root.addHandler(lsp_handler)
    root.setLevel(logging.DEBUG)

    _schema = SchemaCache()
    _docs = DocumentStateManager()
    # Said once the bridge is attached, so an operator reading the client's output panel can see
    # the declaration taking effect rather than having to guess from what does and does not work.
    log.info("%s", _ADVERTISED.describe())
    log.info("idfkit-lsp server initialised (schema %s)", _schema.object_types[:3])


@server.feature(types.TEXT_DOCUMENT_DID_OPEN)
def on_did_open(params: types.DidOpenTextDocumentParams) -> None:
    if _docs is None:
        return
    td = params.text_document
    log.info("didOpen  uri=%s version=%s len=%d", td.uri, td.version, len(td.text))
    _docs.update(td.uri, td.text, td.version or 0)


@server.feature(types.TEXT_DOCUMENT_DID_CHANGE)
def on_did_change(params: types.DidChangeTextDocumentParams) -> None:
    if _docs is None:
        return
    doc = server.workspace.get_text_document(params.text_document.uri)
    log.debug(
        "didChange uri=%s version=%s", params.text_document.uri, params.text_document.version
    )
    _docs.update(
        params.text_document.uri,
        doc.source,
        params.text_document.version or 0,
    )


@server.feature(types.TEXT_DOCUMENT_DID_CLOSE)
def on_did_close(params: types.DidCloseTextDocumentParams) -> None:
    if _docs is None:
        return
    log.info("didClose uri=%s", params.text_document.uri)
    _docs.remove(params.text_document.uri)


# ---------------------------------------------------------------------------
# Completion
# ---------------------------------------------------------------------------


@_handles(
    types.TEXT_DOCUMENT_COMPLETION,
    options=types.CompletionOptions(
        trigger_characters=['"', "'", ".", "["],
        resolve_provider=False,
    ),
)
def on_completion(params: types.CompletionParams) -> types.CompletionList:
    if _schema is None or _docs is None:
        return types.CompletionList(is_incomplete=False, items=[])

    uri = params.text_document.uri
    line = params.position.line
    character = params.position.character

    doc = server.workspace.get_text_document(uri)
    lines = doc.source.splitlines()
    if line >= len(lines):
        log.debug("completion: line %d out of range (total %d)", line, len(lines))
        return types.CompletionList(is_incomplete=False, items=[])

    line_text = lines[line]
    # LSP lines are 0-based, AST lineno is 1-based
    bindings = _docs.get_bindings_at_line(uri, line + 1)

    info = detect_completion_context(line_text, character, bindings)
    items = build_completion_items(info, _schema)

    log.info(
        "completion: ctx=%s obj_type=%s prefix=%r → %d items",
        info.context.value,
        info.object_type,
        info.prefix,
        len(items),
    )
    return types.CompletionList(is_incomplete=False, items=items)


# ---------------------------------------------------------------------------
# Hover
# ---------------------------------------------------------------------------


@_handles(types.TEXT_DOCUMENT_HOVER)
def on_hover(params: types.HoverParams) -> types.Hover | None:
    if _schema is None or _docs is None:
        return None

    uri = params.text_document.uri
    line = params.position.line
    character = params.position.character

    doc = server.workspace.get_text_document(uri)
    lines = doc.source.splitlines()
    if line >= len(lines):
        return None

    line_text = lines[line]
    bindings = _docs.get_bindings_at_line(uri, line + 1)

    target = detect_hover_target(line_text, character, bindings)
    if not target:
        log.debug("hover: no target at %d:%d", line, character)
        return None

    content = build_hover_content(target, bindings, _schema)
    if not content:
        log.debug("hover: no content for target=%s", target.target.value)
        return None

    log.info("hover: target=%s obj_type=%s", target.target.value, target.object_type)
    return types.Hover(
        contents=types.MarkupContent(
            kind=types.MarkupKind.Markdown,
            value=content,
        ),
    )


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------


@_handles(types.WORKSPACE_EXECUTE_COMMAND, command=_DOCUMENTATION_COMMAND)
def on_open_documentation(args: list[object]) -> str | None:
    if _schema is None:
        return None

    obj_type = str(args[0]) if args else ""
    if not obj_type:
        return None

    try:
        from idfkit.docs import io_reference_url

        result = io_reference_url(obj_type, _schema.version, _schema.raw_schema)
        if result:
            server.window_show_document(types.ShowDocumentParams(uri=result.url, external=True))
            return result.url
    except Exception:
        log.warning("Failed to open documentation for %s", obj_type, exc_info=True)
    return None


# ---------------------------------------------------------------------------
# Signature Help
# ---------------------------------------------------------------------------


@_handles(
    types.TEXT_DOCUMENT_SIGNATURE_HELP,
    options=types.SignatureHelpOptions(trigger_characters=["(", ","]),
)
def on_signature_help(params: types.SignatureHelpParams) -> types.SignatureHelp | None:
    if _schema is None or _docs is None:
        return None

    uri = params.text_document.uri
    line = params.position.line
    character = params.position.character

    doc = server.workspace.get_text_document(uri)
    lines = doc.source.splitlines()
    if line >= len(lines):
        return None

    line_text = lines[line]
    bindings = _docs.get_bindings_at_line(uri, line + 1)

    result = detect_add_call(line_text, character, bindings)
    if not result:
        log.debug("signatureHelp: no add() call at %d:%d", line, character)
        return None

    _var_name, obj_type, active_param = result
    log.info("signatureHelp: obj_type=%s active_param=%d", obj_type, active_param)
    return build_signature_help(obj_type, active_param, _schema)


# ---------------------------------------------------------------------------
# Versions
# ---------------------------------------------------------------------------


@_handles(VERSIONS_REQUEST)
def on_versions(params: Any = None) -> VersionReport:
    """Report this server's own level and the level of every library it resolved.

    Every level here is read at the moment of asking, so a delivery path that installed something
    other than what it named is visible in the answer rather than in a user's confusion.
    """
    return VersionReport(
        server_id=_DECLARED.id,
        version=_level(DISTRIBUTION),
        libraries=_resolved_libraries(),
    )


# Registration happens once, here, after every handler above exists: the declaration is read and
# what it marks present is what this server advertises.
_ADVERTISED = _advertise(_DECLARED)
