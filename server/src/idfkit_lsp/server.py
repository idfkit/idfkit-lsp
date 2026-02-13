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

# These are initialised in the ``initialized`` handler once the client is ready.
_schema: SchemaCache | None = None
_docs: DocumentStateManager | None = None


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------


@server.feature(types.INITIALIZED)
def on_initialized(params: types.InitializedParams) -> None:
    global _schema, _docs
    _schema = SchemaCache()
    _docs = DocumentStateManager()
    log.info("idfkit-lsp server initialised (schema %s)", _schema.object_types[:3])


@server.feature(types.TEXT_DOCUMENT_DID_OPEN)
def on_did_open(params: types.DidOpenTextDocumentParams) -> None:
    if _docs is None:
        return
    td = params.text_document
    _docs.update(td.uri, td.text, td.version or 0)


@server.feature(types.TEXT_DOCUMENT_DID_CHANGE)
def on_did_change(params: types.DidChangeTextDocumentParams) -> None:
    if _docs is None:
        return
    doc = server.workspace.get_text_document(params.text_document.uri)
    _docs.update(
        params.text_document.uri,
        doc.source,
        params.text_document.version or 0,
    )


@server.feature(types.TEXT_DOCUMENT_DID_CLOSE)
def on_did_close(params: types.DidCloseTextDocumentParams) -> None:
    if _docs is None:
        return
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
        return types.CompletionList(is_incomplete=False, items=[])

    line_text = lines[line]
    # LSP lines are 0-based, AST lineno is 1-based
    bindings = _docs.get_bindings_at_line(uri, line + 1)

    info = detect_completion_context(line_text, character, bindings)
    items = build_completion_items(info, _schema)

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
        return None

    content = build_hover_content(target, bindings, _schema)
    if not content:
        return None

    return types.Hover(
        contents=types.MarkupContent(
            kind=types.MarkupKind.Markdown,
            value=content,
        ),
    )


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
        return None

    _var_name, obj_type, active_param = result
    return build_signature_help(obj_type, active_param, _schema)
