"""Signature help provider for doc.add() calls."""

from __future__ import annotations

import logging
import re

from lsprotocol import types

from idfkit_lsp.analyzer import InferredType
from idfkit_lsp.schema_cache import SchemaCache

log = logging.getLogger(__name__)


def detect_add_call(
    line_text: str,
    character: int,
    bindings: dict[str, InferredType],
) -> tuple[str, str | None, int] | None:
    """Detect if the cursor is inside a ``doc.add(...)`` call.

    Returns ``(variable_name, object_type_or_none, active_parameter_index)``
    or *None* if not inside an add call.
    """
    text = line_text[:character]

    m = re.search(r"(\w+)\.add\((.*)$", text)
    if not m:
        return None

    var_name = m.group(1)
    var_type = bindings.get(var_name)
    if not var_type or not var_type.is_document:
        log.debug("detect_add_call: %r is not a document variable", var_name)
        return None

    args_text = m.group(2)

    # Extract object type from first quoted argument
    obj_type_match = re.match(r"""\s*[\"']([^\"']+)[\"']""", args_text)
    obj_type = obj_type_match.group(1) if obj_type_match else None

    active_param = _count_parameters(args_text)
    return (var_name, obj_type, active_param)


def build_signature_help(
    obj_type: str | None,
    active_param: int,
    schema: SchemaCache,
) -> types.SignatureHelp:
    """Build SignatureHelp for ``doc.add()`` calls."""

    if not obj_type or obj_type not in schema:
        # Generic signature — object type unknown
        sig = types.SignatureInformation(
            label="add(obj_type: str, name: str = '', **kwargs)",
            documentation=types.MarkupContent(
                kind=types.MarkupKind.Markdown,
                value=(
                    "Add a new EnergyPlus object to the document.\n\n"
                    "**obj_type**: The EnergyPlus object type (e.g. `'Zone'`)\n\n"
                    "**name**: The object name\n\n"
                    "**kwargs**: Field values as keyword arguments"
                ),
            ),
            parameters=[
                types.ParameterInformation(
                    label="obj_type",
                    documentation="EnergyPlus object type name",
                ),
                types.ParameterInformation(
                    label="name",
                    documentation="Object name",
                ),
                types.ParameterInformation(
                    label="**kwargs",
                    documentation="Field values",
                ),
            ],
        )
        return types.SignatureHelp(
            signatures=[sig],
            active_signature=0,
            active_parameter=min(active_param, 2),
        )

    # Object-type-specific signature
    desc = schema.describe(obj_type)
    required_idf = set(schema.get_required_fields(obj_type))

    param_labels: list[str] = [f'"{obj_type}"']
    params: list[types.ParameterInformation] = [
        types.ParameterInformation(
            label=f'"{obj_type}"',
            documentation=f"Object type: {obj_type}",
        )
    ]

    if desc.has_name:
        param_labels.append("name: str")
        params.append(
            types.ParameterInformation(
                label="name: str",
                documentation="Object name identifier",
            )
        )

    # Show required fields as explicit parameters
    for field in desc.fields:
        if field.required:
            type_str = field.field_type or "str"
            label = f"{field.name}={type_str}"
            doc_parts: list[str] = []
            if field.units:
                doc_parts.append(f"Units: {field.units}")
            if field.default is not None:
                doc_parts.append(f"Default: {field.default}")
            if field.note:
                doc_parts.append(field.note)
            param_labels.append(label)
            params.append(
                types.ParameterInformation(
                    label=label,
                    documentation="\n".join(doc_parts) if doc_parts else None,
                )
            )

    optional_count = len(desc.fields) - len(required_idf)
    param_labels.append("**kwargs")
    params.append(
        types.ParameterInformation(
            label="**kwargs",
            documentation=f"{optional_count} optional fields available",
        )
    )

    sig_label = f"add({', '.join(param_labels)})"
    memo = desc.memo or ""
    sig = types.SignatureInformation(
        label=sig_label,
        documentation=types.MarkupContent(
            kind=types.MarkupKind.Markdown,
            value=f"Add a **{obj_type}** object.\n\n{memo}".strip(),
        ),
        parameters=params,
    )

    return types.SignatureHelp(
        signatures=[sig],
        active_signature=0,
        active_parameter=min(active_param, len(params) - 1),
    )


def _count_parameters(args_text: str) -> int:
    """Count which parameter the cursor is on by counting commas outside strings/parens."""
    depth = 0
    in_string: str | None = None
    count = 0
    for ch in args_text:
        if in_string:
            if ch == in_string:
                in_string = None
            continue
        if ch in ('"', "'"):
            in_string = ch
        elif ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        elif ch == "," and depth == 0:
            count += 1
    return count
