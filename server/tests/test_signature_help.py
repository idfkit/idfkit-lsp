"""Tests for the signature help provider."""

from __future__ import annotations

from idfkit_lsp.analyzer import IdfKitType, InferredType
from idfkit_lsp.signature_help import build_signature_help, detect_add_call
from idfkit_lsp.schema_cache import SchemaCache


class TestDetectAddCall:
    def test_basic_add(self) -> None:
        bindings = {"doc": InferredType(IdfKitType.DOCUMENT)}
        result = detect_add_call("doc.add(", 8, bindings)
        assert result is not None
        var, obj_type, param_idx = result
        assert var == "doc"
        assert obj_type is None
        assert param_idx == 0

    def test_add_with_type(self) -> None:
        bindings = {"doc": InferredType(IdfKitType.DOCUMENT)}
        result = detect_add_call('doc.add("Zone", ', 16, bindings)
        assert result is not None
        _, obj_type, param_idx = result
        assert obj_type == "Zone"
        assert param_idx == 1

    def test_add_with_kwargs(self) -> None:
        bindings = {"doc": InferredType(IdfKitType.DOCUMENT)}
        result = detect_add_call('doc.add("Zone", "Office", x_origin=0, ', 38, bindings)
        assert result is not None
        _, obj_type, param_idx = result
        assert obj_type == "Zone"
        assert param_idx == 3

    def test_not_an_add_call(self) -> None:
        bindings = {"doc": InferredType(IdfKitType.DOCUMENT)}
        result = detect_add_call("doc.remove(", 11, bindings)
        assert result is None

    def test_non_document_variable(self) -> None:
        bindings = {"zones": InferredType(IdfKitType.COLLECTION, "Zone")}
        result = detect_add_call("zones.add(", 10, bindings)
        assert result is None


class TestBuildSignatureHelp:
    def test_generic_signature(self, schema: SchemaCache) -> None:
        sig = build_signature_help(None, 0, schema)
        assert len(sig.signatures) == 1
        assert "obj_type" in sig.signatures[0].label

    def test_zone_signature(self, schema: SchemaCache) -> None:
        sig = build_signature_help("Zone", 0, schema)
        assert len(sig.signatures) == 1
        assert '"Zone"' in sig.signatures[0].label
        assert "name: str" in sig.signatures[0].label

    def test_active_parameter_clamped(self, schema: SchemaCache) -> None:
        sig = build_signature_help("Zone", 99, schema)
        num_params = len(sig.signatures[0].parameters)
        assert sig.active_parameter < num_params

    def test_unknown_type_uses_generic(self, schema: SchemaCache) -> None:
        sig = build_signature_help("NotARealType", 0, schema)
        assert "obj_type" in sig.signatures[0].label
