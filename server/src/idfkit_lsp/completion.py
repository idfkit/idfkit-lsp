"""Completion context detection and item generation for idfkit patterns."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from enum import Enum

from lsprotocol import types

from idfkit_lsp.analyzer import InferredType
from idfkit_lsp.schema_cache import SchemaCache

log = logging.getLogger(__name__)


class CompletionContext(Enum):
    OBJECT_TYPE_SUBSCRIPT = "object_type_subscript"  # doc["Z...
    OBJECT_TYPE_ADD_ARG = "object_type_add_arg"  # doc.add("Z...
    FIELD_ATTRIBUTE = "field_attribute"  # zone.x_...
    FIELD_KEYWORD_ARG = "field_keyword_arg"  # doc.add("Zone", "name", x_o...
    NONE = "none"


@dataclass
class CompletionInfo:
    context: CompletionContext
    variable_name: str | None = None
    object_type: str | None = None
    prefix: str = ""


def detect_completion_context(
    line_text: str,
    character: int,
    bindings: dict[str, InferredType],
) -> CompletionInfo:
    """Analyse text before the cursor to determine what kind of completion to offer.

    Uses regex on the current line — more robust than AST for incomplete code.
    """
    text = line_text[:character]

    # Pattern 1: var.add("ObjType", ..., kw  (keyword args to .add())
    # Must be checked before the simpler .add( pattern
    m = re.search(r"(\w+)\.add\(\s*[\"']([\w:]+)[\"'].*,\s*(\w*)$", text)
    if m:
        var_name, obj_type, prefix = m.group(1), m.group(2), m.group(3)
        var_type = bindings.get(var_name)
        if var_type and var_type.is_document:
            return CompletionInfo(
                CompletionContext.FIELD_KEYWORD_ARG,
                var_name,
                object_type=obj_type,
                prefix=prefix,
            )

    # Pattern 2: var.add("prefix  (first arg to .add())
    m = re.search(r"(\w+)\.add\(\s*[\"']([^\"']*)$", text)
    if m:
        var_name, prefix = m.group(1), m.group(2)
        var_type = bindings.get(var_name)
        if var_type and var_type.is_document:
            return CompletionInfo(
                CompletionContext.OBJECT_TYPE_ADD_ARG, var_name, prefix=prefix
            )

    # Pattern 3: var["ObjType"]["prefix  (chained subscript — object name, skip)
    m = re.search(r"(\w+)\[[\"']([\w:]+)[\"']\]\[[\"']([^\"']*)$", text)
    if m:
        # We can't complete object names without runtime data — return NONE
        return CompletionInfo(CompletionContext.NONE)

    # Pattern 4: var["prefix  (subscript on a variable)
    m = re.search(r"(\w+)\[[\"']([^\"']*)$", text)
    if m:
        var_name, prefix = m.group(1), m.group(2)
        var_type = bindings.get(var_name)
        if var_type:
            if var_type.is_document:
                return CompletionInfo(
                    CompletionContext.OBJECT_TYPE_SUBSCRIPT, var_name, prefix=prefix
                )

    # Pattern 5: var.attr_prefix  (attribute access)
    m = re.search(r"(\w+)\.(\w*)$", text)
    if m:
        var_name, prefix = m.group(1), m.group(2)
        var_type = bindings.get(var_name)
        if var_type and var_type.is_object and var_type.object_type:
            return CompletionInfo(
                CompletionContext.FIELD_ATTRIBUTE,
                var_name,
                object_type=var_type.object_type,
                prefix=prefix,
            )

    log.debug("detect_completion_context: no pattern matched for %r", text)
    return CompletionInfo(CompletionContext.NONE)


def build_completion_items(
    info: CompletionInfo,
    schema: SchemaCache,
) -> list[types.CompletionItem]:
    """Generate CompletionItem list based on detected context."""

    if info.context in (
        CompletionContext.OBJECT_TYPE_SUBSCRIPT,
        CompletionContext.OBJECT_TYPE_ADD_ARG,
    ):
        matches = schema.match_object_types(info.prefix)
        return [
            types.CompletionItem(
                label=ot,
                kind=types.CompletionItemKind.Class,
                detail=schema.get_group(ot) or "EnergyPlus object",
                insert_text=ot,
                sort_text=f"0_{ot}",
            )
            for ot in matches
        ]

    if info.context == CompletionContext.FIELD_ATTRIBUTE and info.object_type:
        return _field_completions(info.object_type, info.prefix, schema)

    if info.context == CompletionContext.FIELD_KEYWORD_ARG and info.object_type:
        return _keyword_arg_completions(info.object_type, info.prefix, schema)

    return []


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _field_completions(
    obj_type: str, prefix: str, schema: SchemaCache
) -> list[types.CompletionItem]:
    """Completion items for field attributes on an IDFObject."""
    python_names = schema.get_field_python_names(obj_type)
    prefix_lower = prefix.lower()
    items: list[types.CompletionItem] = []
    for pname in python_names:
        if pname.lower().startswith(prefix_lower):
            items.append(_make_field_item(pname, obj_type, schema))
    return items


def _keyword_arg_completions(
    obj_type: str, prefix: str, schema: SchemaCache
) -> list[types.CompletionItem]:
    """Completion items for keyword arguments in doc.add() calls."""
    python_names = schema.get_field_python_names(obj_type)
    required_idf = set(schema.get_required_fields(obj_type))
    prefix_lower = prefix.lower()
    items: list[types.CompletionItem] = []
    for pname in python_names:
        if not pname.lower().startswith(prefix_lower):
            continue
        idf_name = schema.get_field_idf_name(obj_type, pname)
        is_required = idf_name in required_idf if idf_name else False
        items.append(
            types.CompletionItem(
                label=pname,
                kind=types.CompletionItemKind.Property,
                detail="(required)" if is_required else "(optional)",
                insert_text=f"{pname}=",
                sort_text=f"{'0' if is_required else '1'}_{pname}",
            )
        )
    return items


def _make_field_item(
    python_name: str, obj_type: str, schema: SchemaCache
) -> types.CompletionItem:
    """Create a CompletionItem for a single field with inline docs."""
    idf_name = schema.get_field_idf_name(obj_type, python_name)
    detail_parts: list[str] = []
    doc_parts: list[str] = []

    if idf_name:
        fs = schema.get_field_schema(obj_type, idf_name)
        if fs:
            if "type" in fs:
                detail_parts.append(fs["type"])
            if "units" in fs:
                detail_parts.append(f"[{fs['units']}]")
            if "default" in fs:
                doc_parts.append(f"**Default:** {fs['default']}")
            if "enum" in fs:
                vals = fs["enum"]
                doc_parts.append(f"**Options:** {', '.join(str(v) for v in vals[:8])}")
            if "minimum" in fs:
                doc_parts.append(f"**Min:** {fs['minimum']}")
            if "maximum" in fs:
                doc_parts.append(f"**Max:** {fs['maximum']}")

    return types.CompletionItem(
        label=python_name,
        kind=types.CompletionItemKind.Property,
        detail=" ".join(detail_parts) if detail_parts else "field",
        documentation=(
            types.MarkupContent(
                kind=types.MarkupKind.Markdown,
                value="\n\n".join(doc_parts),
            )
            if doc_parts
            else None
        ),
        insert_text=python_name,
    )
