"""Tests for the AST-based idfkit type inference engine."""

from __future__ import annotations

from idfkit_lsp.analyzer import IdfKitAnalyzer, IdfKitType, InferredType


class TestImportTracking:
    def test_from_import(self) -> None:
        src = "from idfkit import load_idf\n"
        a = IdfKitAnalyzer()
        a.analyze(src)
        assert "load_idf" in a.imported_names

    def test_import_module(self) -> None:
        src = "import idfkit\n"
        a = IdfKitAnalyzer()
        a.analyze(src)
        assert "idfkit" in a.imported_names

    def test_aliased_import(self) -> None:
        src = "from idfkit import load_idf as li\n"
        a = IdfKitAnalyzer()
        a.analyze(src)
        assert "li" in a.imported_names

    def test_no_idfkit_import_yields_empty(self) -> None:
        src = "import os\ndoc = some_func()\n"
        a = IdfKitAnalyzer()
        bindings = a.analyze(src)
        assert len(bindings) == 0


class TestDocumentFactories:
    def test_load_idf(self) -> None:
        src = 'from idfkit import load_idf\ndoc = load_idf("model.idf")\n'
        bindings = IdfKitAnalyzer().analyze(src)
        assert bindings["doc"] == InferredType(IdfKitType.DOCUMENT)

    def test_load_epjson(self) -> None:
        src = 'from idfkit import load_epjson\ndoc = load_epjson("m.epJSON")\n'
        bindings = IdfKitAnalyzer().analyze(src)
        assert bindings["doc"].is_document

    def test_new_document(self) -> None:
        src = "from idfkit import new_document\ndoc = new_document()\n"
        bindings = IdfKitAnalyzer().analyze(src)
        assert bindings["doc"].is_document

    def test_qualified_call(self) -> None:
        src = 'import idfkit\ndoc = idfkit.load_idf("x.idf")\n'
        bindings = IdfKitAnalyzer().analyze(src)
        assert bindings["doc"].is_document

    def test_load_idf_with_diagnostics(self) -> None:
        # A document-producing entry point the written factory table never heard of. It hands the
        # document back inside a result object, so only a derived surface finds it, and only
        # reading the attribute that holds it yields a document.
        src = (
            "from idfkit import load_idf_with_diagnostics\n"
            'result = load_idf_with_diagnostics("m.idf")\n'
            "doc = result.document\n"
        )
        bindings = IdfKitAnalyzer().analyze(src)
        assert bindings["doc"].is_document

    def test_a_result_object_is_not_itself_a_document(self) -> None:
        # The result carries a document; it is not one. Offering document members on it would be
        # an answer a user cannot tell apart from a real one, which Principle IV forbids.
        src = (
            "from idfkit import load_idf_with_diagnostics\n"
            'result = load_idf_with_diagnostics("m.idf")\n'
        )
        bindings = IdfKitAnalyzer().analyze(src)
        assert not bindings["result"].is_document
        assert bindings["result"].is_document_carrier

    def test_an_unrelated_attribute_of_a_result_is_not_a_document(self) -> None:
        src = (
            "from idfkit import load_idf_with_diagnostics\n"
            'result = load_idf_with_diagnostics("m.idf")\n'
            "problems = result.diagnostics\n"
        )
        bindings = IdfKitAnalyzer().analyze(src)
        assert "problems" not in bindings

    def test_unrecognised_call_not_tracked(self) -> None:
        src = "from idfkit import load_idf\nresult = other_func()\n"
        bindings = IdfKitAnalyzer().analyze(src)
        assert "result" not in bindings


class TestSubscriptInference:
    def test_doc_subscript_gives_collection(self) -> None:
        src = 'from idfkit import load_idf\ndoc = load_idf("x.idf")\nzones = doc["Zone"]\n'
        bindings = IdfKitAnalyzer().analyze(src)
        assert bindings["zones"] == InferredType(IdfKitType.COLLECTION, "Zone")

    def test_collection_subscript_gives_object(self) -> None:
        src = (
            "from idfkit import load_idf\n"
            'doc = load_idf("x.idf")\n'
            'zones = doc["Zone"]\n'
            'z = zones["Office"]\n'
        )
        bindings = IdfKitAnalyzer().analyze(src)
        assert bindings["z"] == InferredType(IdfKitType.OBJECT, "Zone")

    def test_chained_subscript(self) -> None:
        src = 'from idfkit import load_idf\ndoc = load_idf("x.idf")\nz = doc["Zone"]["Office"]\n'
        bindings = IdfKitAnalyzer().analyze(src)
        assert bindings["z"] == InferredType(IdfKitType.OBJECT, "Zone")


class TestDocAdd:
    def test_add_with_string_type(self) -> None:
        src = (
            'from idfkit import load_idf\ndoc = load_idf("x.idf")\nz = doc.add("Zone", "Office")\n'
        )
        bindings = IdfKitAnalyzer().analyze(src)
        assert bindings["z"] == InferredType(IdfKitType.OBJECT, "Zone")

    def test_add_without_type_string(self) -> None:
        src = 'from idfkit import load_idf\ndoc = load_idf("x.idf")\nz = doc.add(obj_type, name)\n'
        bindings = IdfKitAnalyzer().analyze(src)
        # We know it's an IDFObject but don't know the object_type
        assert bindings["z"].is_object
        assert bindings["z"].object_type is None


class TestForLoopIteration:
    def test_for_over_collection(self) -> None:
        src = (
            "from idfkit import load_idf\n"
            'doc = load_idf("x.idf")\n'
            'for z in doc["Zone"]:\n'
            "    pass\n"
        )
        bindings = IdfKitAnalyzer().analyze(src)
        assert bindings["z"] == InferredType(IdfKitType.OBJECT, "Zone")

    def test_for_over_named_collection(self) -> None:
        src = (
            "from idfkit import load_idf\n"
            'doc = load_idf("x.idf")\n'
            'zones = doc["Zone"]\n'
            "for z in zones:\n"
            "    pass\n"
        )
        bindings = IdfKitAnalyzer().analyze(src)
        assert bindings["z"] == InferredType(IdfKitType.OBJECT, "Zone")


class TestAnnotations:
    def test_annotated_document(self) -> None:
        src = "from idfkit import IDFDocument\ndoc: IDFDocument\n"
        bindings = IdfKitAnalyzer().analyze(src)
        assert bindings["doc"].is_document

    def test_annotated_object(self) -> None:
        src = "from idfkit import IDFObject\nobj: IDFObject\n"
        bindings = IdfKitAnalyzer().analyze(src)
        assert bindings["obj"].is_object

    def test_subscripted_annotation(self) -> None:
        # The document type is generic now, so a written annotation carries a subscript. Matching
        # the annotation name without unwrapping it to its origin silently stopped inferring.
        src = (
            "from typing import Literal\n"
            "from idfkit import IDFDocument\n"
            "doc: IDFDocument[Literal[True]] = obtain()\n"
        )
        bindings = IdfKitAnalyzer().analyze(src)
        assert bindings["doc"].is_document

    def test_subscripted_param_annotation(self) -> None:
        src = (
            "from idfkit import IDFDocument\n"
            "def process(doc: IDFDocument[bool]):\n"
            '    zones = doc["Zone"]\n'
        )
        bindings = IdfKitAnalyzer().analyze(src)
        assert bindings["zones"] == InferredType(IdfKitType.COLLECTION, "Zone")

    def test_function_param_annotation(self) -> None:
        src = (
            "from idfkit import IDFDocument\n"
            "def process(doc: IDFDocument):\n"
            '    zones = doc["Zone"]\n'
        )
        bindings = IdfKitAnalyzer().analyze(src)
        assert bindings["zones"] == InferredType(IdfKitType.COLLECTION, "Zone")

    def test_value_overrides_annotation(self) -> None:
        src = 'from idfkit import load_idf, IDFDocument\ndoc: IDFDocument = load_idf("x.idf")\n'
        bindings = IdfKitAnalyzer().analyze(src)
        assert bindings["doc"].is_document


class TestAnalyzeAtLine:
    def test_stops_at_line(self) -> None:
        src = (
            "from idfkit import load_idf\n"  # line 1
            'doc = load_idf("x.idf")\n'  # line 2
            'zones = doc["Zone"]\n'  # line 3
            'zone = zones["Office"]\n'  # line 4
        )
        bindings = IdfKitAnalyzer().analyze_at_line(src, 3)
        assert "zones" in bindings
        assert "zone" not in bindings

    def test_includes_exact_line(self) -> None:
        src = 'from idfkit import load_idf\ndoc = load_idf("x.idf")\n'
        bindings = IdfKitAnalyzer().analyze_at_line(src, 2)
        assert "doc" in bindings


class TestCollectionFirst:
    def test_first_returns_object(self) -> None:
        src = 'from idfkit import load_idf\ndoc = load_idf("x.idf")\nz = doc["Zone"].first()\n'
        bindings = IdfKitAnalyzer().analyze(src)
        assert bindings["z"] == InferredType(IdfKitType.OBJECT, "Zone")


class TestSyntaxError:
    def test_invalid_source(self) -> None:
        src = "this is not valid python {{{}}}"
        bindings = IdfKitAnalyzer().analyze(src)
        assert bindings == {}
