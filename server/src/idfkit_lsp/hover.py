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

    # Check: cursor inside a quoted string in .add("...") → object type
    for m in re.finditer(r'(\w+)\.add\(\s*[\"\']([^"\']+)[\"\']', line_text):
        start, end = m.start(2), m.end(2)
        if start <= character <= end:
            var_name = m.group(1)
            obj_type = m.group(2)
            var_type = bindings.get(var_name)
            if var_type and var_type.is_document:
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
        return _variable_hover(info.variable_name, bindings)

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
    return "\n".join(lines)


def _field_hover(obj_type: str, python_name: str, schema: SchemaCache) -> str | None:
    idf_name = schema.get_field_idf_name(obj_type, python_name)
    if not idf_name:
        return None
    fs = schema.get_field_schema(obj_type, idf_name)
    if not fs:
        return None

    lines = [f"### {obj_type} · {idf_name}", f"**Python name:** `{python_name}`", ""]
    if "type" in fs:
        lines.append(f"**Type:** {fs['type']}")
    if "units" in fs:
        lines.append(f"**Units:** {fs['units']}")
    if "default" in fs:
        lines.append(f"**Default:** {fs['default']}")
    if "minimum" in fs:
        lines.append(f"**Minimum:** {fs['minimum']}")
    if "maximum" in fs:
        lines.append(f"**Maximum:** {fs['maximum']}")
    if "exclusiveMinimum" in fs:
        lines.append(f"**Exclusive minimum:** {fs['exclusiveMinimum']}")
    if "exclusiveMaximum" in fs:
        lines.append(f"**Exclusive maximum:** {fs['exclusiveMaximum']}")
    if "enum" in fs:
        lines.append(f"**Options:** {', '.join(str(v) for v in fs['enum'])}")
    if "note" in fs:
        lines.append("")
        lines.append(fs["note"])
    return "\n".join(lines)


def _variable_hover(var_name: str, bindings: dict[str, InferredType]) -> str | None:
    var_type = bindings.get(var_name)
    if not var_type:
        return None
    type_str = var_type.kind.value
    if var_type.object_type:
        type_str += f' (object type: "{var_type.object_type}")'
    return f"**{var_name}**: `{type_str}`"
