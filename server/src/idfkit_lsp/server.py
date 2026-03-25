"""pygls Language Server wiring — connects all providers to LSP protocol handlers."""

from __future__ import annotations

import logging

from lsprotocol import types
from pygls.lsp.server import LanguageServer

from idfkit_lsp.completion import build_completion_items, detect_completion_context
from idfkit_lsp.document_state import DocumentStateManager
from idfkit_lsp.hover import build_hover_content, detect_hover_target
from idfkit_lsp.schema_cache import SchemaCache
from idfkit_lsp.signature_help import build_signature_help, detect_add_call

log = logging.getLogger(__name__)

server = LanguageServer("idfkit-lsp", "v0.1.0")


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
# Lifecycle
# ---------------------------------------------------------------------------


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


@server.feature(
    types.TEXT_DOCUMENT_COMPLETION,
    types.CompletionOptions(
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


@server.feature(types.TEXT_DOCUMENT_HOVER)
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


@server.command("idfkit.openDocumentation")
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


@server.feature(
    types.TEXT_DOCUMENT_SIGNATURE_HELP,
    types.SignatureHelpOptions(trigger_characters=["(", ","]),
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
