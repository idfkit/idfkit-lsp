"""Tests for the hover provider."""

from __future__ import annotations

from idfkit_lsp.analyzer import IdfKitType, InferredType
from idfkit_lsp.hover import (
    HoverInfo,
    HoverTarget,
    build_hover_content,
    detect_hover_target,
)
from idfkit_lsp.schema_cache import SchemaCache


class TestHoverDetection:
    def test_object_type_in_subscript(self) -> None:
        bindings = {"doc": InferredType(IdfKitType.DOCUMENT)}
        info = detect_hover_target('doc["Zone"]', 6, bindings)
        assert info is not None
        assert info.target == HoverTarget.OBJECT_TYPE
        assert info.object_type == "Zone"

    def test_object_type_in_add(self) -> None:
        bindings = {"doc": InferredType(IdfKitType.DOCUMENT)}
        info = detect_hover_target('doc.add("Zone", "Office")', 11, bindings)
        assert info is not None
        assert info.target == HoverTarget.OBJECT_TYPE
        assert info.object_type == "Zone"

    def test_field_attribute(self) -> None:
        bindings = {"zone": InferredType(IdfKitType.OBJECT, "Zone")}
        info = detect_hover_target("zone.x_origin", 7, bindings)
        assert info is not None
        assert info.target == HoverTarget.FIELD_ATTR
        assert info.object_type == "Zone"
        assert info.field_python_name == "x_origin"

    def test_variable_hover(self) -> None:
        bindings = {"doc": InferredType(IdfKitType.DOCUMENT)}
        info = detect_hover_target("doc", 1, bindings)
        assert info is not None
        assert info.target == HoverTarget.VARIABLE
        assert info.variable_name == "doc"

    def test_no_match(self) -> None:
        bindings: dict[str, InferredType] = {}
        info = detect_hover_target("x = 42", 2, bindings)
        assert info is None


class TestHoverContent:
    def test_object_type_content(self, schema: SchemaCache) -> None:
        bindings: dict[str, InferredType] = {}
        info = HoverInfo(HoverTarget.OBJECT_TYPE, object_type="Zone")
        content = build_hover_content(info, bindings, schema)
        assert content is not None
        assert "Zone" in content
        assert "Thermal Zones and Surfaces" in content

    def test_field_content(self, schema: SchemaCache) -> None:
        bindings: dict[str, InferredType] = {}
        info = HoverInfo(
            HoverTarget.FIELD_ATTR,
            object_type="Zone",
            field_python_name="x_origin",
        )
        content = build_hover_content(info, bindings, schema)
        assert content is not None
        assert "x_origin" in content
        assert "number" in content
        assert "m" in content  # units

    def test_variable_content(self) -> None:
        bindings = {"doc": InferredType(IdfKitType.DOCUMENT)}
        info = HoverInfo(HoverTarget.VARIABLE, variable_name="doc")
        # schema not needed for variable hover
        content = build_hover_content(info, bindings, SchemaCache.__new__(SchemaCache))  # type: ignore[arg-type]
        assert content is not None
        assert "IDFDocument" in content

    def test_unknown_object_type(self, schema: SchemaCache) -> None:
        bindings: dict[str, InferredType] = {}
        info = HoverInfo(HoverTarget.OBJECT_TYPE, object_type="NotARealType")
        content = build_hover_content(info, bindings, schema)
        assert content is None
