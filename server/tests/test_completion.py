"""Tests for the completion provider."""

from __future__ import annotations

from idfkit_lsp.analyzer import IdfKitType, InferredType
from idfkit_lsp.completion import (
    CompletionContext,
    CompletionInfo,
    build_completion_items,
    detect_completion_context,
)
from idfkit_lsp.schema_cache import SchemaCache


class TestContextDetection:
    """Tests for detect_completion_context."""

    def test_doc_subscript_double_quote(self) -> None:
        bindings = {"doc": InferredType(IdfKitType.DOCUMENT)}
        info = detect_completion_context('doc["Zon', 9, bindings)
        assert info.context == CompletionContext.OBJECT_TYPE_SUBSCRIPT
        assert info.prefix == "Zon"

    def test_doc_subscript_single_quote(self) -> None:
        bindings = {"doc": InferredType(IdfKitType.DOCUMENT)}
        info = detect_completion_context("doc['Zon", 9, bindings)
        assert info.context == CompletionContext.OBJECT_TYPE_SUBSCRIPT
        assert info.prefix == "Zon"

    def test_doc_subscript_empty_prefix(self) -> None:
        bindings = {"doc": InferredType(IdfKitType.DOCUMENT)}
        info = detect_completion_context('doc["', 5, bindings)
        assert info.context == CompletionContext.OBJECT_TYPE_SUBSCRIPT
        assert info.prefix == ""

    def test_add_first_arg(self) -> None:
        bindings = {"doc": InferredType(IdfKitType.DOCUMENT)}
        info = detect_completion_context('doc.add("Zon', 13, bindings)
        assert info.context == CompletionContext.OBJECT_TYPE_ADD_ARG
        assert info.prefix == "Zon"

    def test_field_attribute(self) -> None:
        bindings = {"zone": InferredType(IdfKitType.OBJECT, "Zone")}
        info = detect_completion_context("zone.x_or", 9, bindings)
        assert info.context == CompletionContext.FIELD_ATTRIBUTE
        assert info.object_type == "Zone"
        assert info.prefix == "x_or"

    def test_field_attribute_empty(self) -> None:
        bindings = {"zone": InferredType(IdfKitType.OBJECT, "Zone")}
        info = detect_completion_context("zone.", 5, bindings)
        assert info.context == CompletionContext.FIELD_ATTRIBUTE
        assert info.prefix == ""

    def test_keyword_arg(self) -> None:
        bindings = {"doc": InferredType(IdfKitType.DOCUMENT)}
        info = detect_completion_context(
            'doc.add("Zone", "Office", x_or', 30, bindings
        )
        assert info.context == CompletionContext.FIELD_KEYWORD_ARG
        assert info.object_type == "Zone"
        assert info.prefix == "x_or"

    def test_unknown_variable(self) -> None:
        bindings: dict[str, InferredType] = {}
        info = detect_completion_context('unknown["Zon', 13, bindings)
        assert info.context == CompletionContext.NONE

    def test_non_document_subscript(self) -> None:
        bindings = {"zones": InferredType(IdfKitType.COLLECTION, "Zone")}
        info = detect_completion_context('zones["Off', 11, bindings)
        # Collection subscript is an object name lookup — no completion
        assert info.context == CompletionContext.NONE

    def test_chained_subscript_returns_none(self) -> None:
        bindings = {"doc": InferredType(IdfKitType.DOCUMENT)}
        info = detect_completion_context('doc["Zone"]["Off', 17, bindings)
        assert info.context == CompletionContext.NONE


class TestItemGeneration:
    """Tests for build_completion_items using a real schema."""

    def test_object_type_matches(self, schema: SchemaCache) -> None:
        info = CompletionInfo(
            CompletionContext.OBJECT_TYPE_SUBSCRIPT, prefix="Zone"
        )
        items = build_completion_items(info, schema)
        labels = [i.label for i in items]
        assert "Zone" in labels
        # Should also match "ZoneHVAC:..." types
        assert any(l.startswith("ZoneHVAC") for l in labels)

    def test_object_type_empty_prefix(self, schema: SchemaCache) -> None:
        info = CompletionInfo(
            CompletionContext.OBJECT_TYPE_SUBSCRIPT, prefix=""
        )
        items = build_completion_items(info, schema)
        # All object types returned
        assert len(items) == len(schema.object_types)

    def test_field_attribute_items(self, schema: SchemaCache) -> None:
        info = CompletionInfo(
            CompletionContext.FIELD_ATTRIBUTE, object_type="Zone", prefix="x"
        )
        items = build_completion_items(info, schema)
        labels = [i.label for i in items]
        assert "x_origin" in labels

    def test_field_attribute_all(self, schema: SchemaCache) -> None:
        info = CompletionInfo(
            CompletionContext.FIELD_ATTRIBUTE, object_type="Zone", prefix=""
        )
        items = build_completion_items(info, schema)
        # Zone has 12 fields per our earlier check
        assert len(items) > 5

    def test_keyword_arg_items(self, schema: SchemaCache) -> None:
        info = CompletionInfo(
            CompletionContext.FIELD_KEYWORD_ARG, object_type="Zone", prefix=""
        )
        items = build_completion_items(info, schema)
        assert len(items) > 0
        # All items should end with = in insert_text
        assert all(i.insert_text and i.insert_text.endswith("=") for i in items)

    def test_none_context_returns_empty(self, schema: SchemaCache) -> None:
        info = CompletionInfo(CompletionContext.NONE)
        items = build_completion_items(info, schema)
        assert items == []
