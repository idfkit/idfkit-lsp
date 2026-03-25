"""Hover documentation provider for idfkit patterns."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from enum import Enum

from idfkit_lsp.analyzer import InferredType
from idfkit_lsp.schema_cache import SchemaCache

log = logging.getLogger(__name__)


class HoverTarget(Enum):
    OBJECT_TYPE = "object_type"  # hovering over "Zone" in doc["Zone"]
    FIELD_ATTR = "field_attr"  # hovering over .x_origin on IDFObject
    VARIABLE = "variable"  # hovering over a variable name


@dataclass
class HoverInfo:
    target: HoverTarget
    object_type: str | None = None
    field_python_name: str | None = None
    variable_name: str | None = None


def detect_hover_target(
    line_text: str,
    character: int,
    bindings: dict[str, InferredType],
) -> HoverInfo | None:
    """Determine what the user is hovering over."""

    # Check: cursor inside a quoted string within brackets → object type
    for m in re.finditer(r'(\w+)\[[\"\']([^"\']+)[\"\']\]', line_text):
        start, end = m.start(2), m.end(2)
        if start <= character <= end:
            var_name = m.group(1)
            obj_type = m.group(2)
            var_type = bindings.get(var_name)
            if var_type and var_type.is_document:
                return HoverInfo(HoverTarget.OBJECT_TYPE, object_type=obj_type)

    # Check: cursor inside .add("...") → object type (on the string OR on "add")
    for m in re.finditer(r'(\w+)\.(add)\(\s*[\"\']([^"\']+)[\"\']', line_text):
        var_name = m.group(1)
        obj_type = m.group(3)
        var_type = bindings.get(var_name)
        if not (var_type and var_type.is_document):
            continue
        # Cursor on the object type string
        str_start, str_end = m.start(3), m.end(3)
        if str_start <= character <= str_end:
            return HoverInfo(HoverTarget.OBJECT_TYPE, object_type=obj_type)
        # Cursor on the "add" method name
        add_start, add_end = m.start(2), m.end(2)
        if add_start <= character <= add_end:
            return HoverInfo(HoverTarget.OBJECT_TYPE, object_type=obj_type)

    # Check: cursor on an attribute after a dot → field
    for m in re.finditer(r"(\w+)\.(\w+)", line_text):
        attr_start, attr_end = m.start(2), m.end(2)
        if attr_start <= character <= attr_end:
            var_name = m.group(1)
            attr_name = m.group(2)
            var_type = bindings.get(var_name)
            if var_type and var_type.is_object and var_type.object_type:
                return HoverInfo(
                    HoverTarget.FIELD_ATTR,
                    object_type=var_type.object_type,
                    field_python_name=attr_name,
                )

    # Check: cursor on a variable name
    for m in re.finditer(r"\b(\w+)\b", line_text):
        if m.start() <= character <= m.end():
            var_name = m.group(1)
            if var_name in bindings:
                return HoverInfo(HoverTarget.VARIABLE, variable_name=var_name)

    log.debug("detect_hover_target: no target at character %d", character)
    return None


def build_hover_content(
    info: HoverInfo,
    bindings: dict[str, InferredType],
    schema: SchemaCache,
) -> str | None:
    """Generate markdown hover documentation."""

    if info.target == HoverTarget.OBJECT_TYPE and info.object_type:
        return _object_type_hover(info.object_type, schema)

    if info.target == HoverTarget.FIELD_ATTR and info.object_type and info.field_python_name:
        return _field_hover(info.object_type, info.field_python_name, schema)

    if info.target == HoverTarget.VARIABLE and info.variable_name:
        return _variable_hover(info.variable_name, bindings, schema)

    return None


# ---------------------------------------------------------------------------
# Content builders
# ---------------------------------------------------------------------------


def _object_type_hover(obj_type: str, schema: SchemaCache) -> str | None:
    if obj_type not in schema:
        return None
    desc = schema.describe(obj_type)
    group = schema.get_group(obj_type)
    required = schema.get_required_fields(obj_type)

    lines = [f"### {obj_type}"]
    if group:
        lines.append(f"**Group:** {group}")
    lines.append("")
    if desc.memo:
        lines.append(desc.memo)
        lines.append("")
    if required:
        lines.append("**Required fields:**")
        for fname in required:
            lines.append(f"- `{fname}`")
        lines.append("")
    lines.append(f"*{len(desc.fields)} total fields*")

    doc_url = _docs_link(obj_type, schema)
    if doc_url:
        lines.append("")
        lines.append(doc_url)

    return "\n".join(lines)


def _field_hover(obj_type: str, python_name: str, schema: SchemaCache) -> str | None:
    field = schema.get_field_description(obj_type, python_name)
    if not field:
        return None

    lines = [f"### {obj_type} · `{python_name}`", ""]
    if field.field_type:
        lines.append(f"**Type:** {field.field_type}")
    if field.units:
        lines.append(f"**Units:** {field.units}")
    if field.default is not None:
        lines.append(f"**Default:** {field.default}")
    if field.minimum is not None:
        lines.append(f"**Minimum:** {field.minimum}")
    if field.maximum is not None:
        lines.append(f"**Maximum:** {field.maximum}")
    if field.exclusive_minimum is not None:
        lines.append(f"**Exclusive minimum:** {field.exclusive_minimum}")
    if field.exclusive_maximum is not None:
        lines.append(f"**Exclusive maximum:** {field.exclusive_maximum}")
    if field.enum_values:
        lines.append(f"**Options:** {', '.join(str(v) for v in field.enum_values)}")
    if field.is_reference:
        lines.append("**Reference field:** yes")
    if field.note:
        lines.append("")
        lines.append(field.note)

    doc_url = _docs_link(obj_type, schema)
    if doc_url:
        lines.append("")
        lines.append(doc_url)

    return "\n".join(lines)


def _variable_hover(
    var_name: str,
    bindings: dict[str, InferredType],
    schema: SchemaCache,
) -> str | None:
    var_type = bindings.get(var_name)
    if not var_type:
        return None
    type_str = var_type.kind.value
    if var_type.object_type:
        type_str += f' (object type: "{var_type.object_type}")'
    lines = [f"**{var_name}**: `{type_str}`"]
    if var_type.object_type and var_type.object_type in schema:
        desc = schema.describe(var_type.object_type)
        if desc.memo:
            lines.append("")
            lines.append(desc.memo)
    return "\n".join(lines)


def _docs_link(obj_type: str, schema: SchemaCache) -> str | None:
    """Build a clickable markdown link to docs.idfkit.com for an object type."""
    try:
        from idfkit.docs import io_reference_url

        result = io_reference_url(obj_type, schema.version, schema.raw_schema)
        if result:
            return f"[Open documentation]({result.url})"
    except Exception:
        log.debug("Failed to build docs URL for %s", obj_type, exc_info=True)
    return None
