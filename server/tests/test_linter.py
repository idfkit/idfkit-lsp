"""Tests for cross-version EnergyPlus compatibility linter."""

from pathlib import Path

from idfkit_lsp.analyzer import IdfKitAnalyzer
from idfkit_lsp.linter import lint_source

# ---------------------------------------------------------------------------
# Analyzer usage tracking tests
# ---------------------------------------------------------------------------


class TestUsageTracking:
    """Verify that IdfKitAnalyzer collects usage sites when track_usages=True."""

    def test_doc_subscript_tracks_object_type(self):
        source = """\
from idfkit import load_idf
doc = load_idf("test.idf")
zones = doc["Zone"]
"""
        analyzer = IdfKitAnalyzer(track_usages=True)
        analyzer.analyze(source)
        assert len(analyzer.object_type_usages) == 1
        usage = analyzer.object_type_usages[0]
        assert usage.object_type == "Zone"
        assert usage.line == 3

    def test_doc_add_tracks_object_type(self):
        source = """\
from idfkit import new_document
doc = new_document()
zone = doc.add("Zone", "Office")
"""
        analyzer = IdfKitAnalyzer(track_usages=True)
        analyzer.analyze(source)
        assert len(analyzer.object_type_usages) == 1
        assert analyzer.object_type_usages[0].object_type == "Zone"

    def test_doc_add_tracks_keyword_fields(self):
        source = """\
from idfkit import new_document
doc = new_document()
zone = doc.add("Zone", "Office", x_origin=0.0, y_origin=0.0)
"""
        analyzer = IdfKitAnalyzer(track_usages=True)
        analyzer.analyze(source)
        field_names = [u.field_name for u in analyzer.field_usages]
        assert "x_origin" in field_names
        assert "y_origin" in field_names
        for u in analyzer.field_usages:
            assert u.object_type == "Zone"

    def test_attribute_access_tracks_field(self):
        source = """\
from idfkit import load_idf
doc = load_idf("test.idf")
zone = doc["Zone"]["Office"]
print(zone.x_origin)
"""
        analyzer = IdfKitAnalyzer(track_usages=True)
        analyzer.analyze(source)
        field_names = [u.field_name for u in analyzer.field_usages]
        assert "x_origin" in field_names

    def test_attribute_write_tracks_field(self):
        source = """\
from idfkit import load_idf
doc = load_idf("test.idf")
zone = doc["Zone"]["Office"]
zone.x_origin = 10.0
"""
        analyzer = IdfKitAnalyzer(track_usages=True)
        analyzer.analyze(source)
        field_names = [u.field_name for u in analyzer.field_usages]
        assert "x_origin" in field_names

    def test_no_tracking_when_disabled(self):
        source = """\
from idfkit import load_idf
doc = load_idf("test.idf")
zones = doc["Zone"]
"""
        analyzer = IdfKitAnalyzer(track_usages=False)
        analyzer.analyze(source)
        assert len(analyzer.object_type_usages) == 0

    def test_multiple_usages(self):
        source = """\
from idfkit import new_document
doc = new_document()
zones = doc["Zone"]
surfaces = doc["BuildingSurface:Detailed"]
zone = doc.add("Zone", "Office")
"""
        analyzer = IdfKitAnalyzer(track_usages=True)
        analyzer.analyze(source)
        obj_types = [u.object_type for u in analyzer.object_type_usages]
        assert "Zone" in obj_types
        assert "BuildingSurface:Detailed" in obj_types
        # "Zone" appears twice: subscript + add
        assert obj_types.count("Zone") == 2


# ---------------------------------------------------------------------------
# Linter tests
# ---------------------------------------------------------------------------


DUMMY_FILE = Path("test.py")


class TestLintSource:
    """Test lint_source with real schemas."""

    def test_valid_object_type_no_diagnostics(self):
        source = """\
from idfkit import new_document
doc = new_document()
zones = doc["Zone"]
"""
        diagnostics = lint_source(source, DUMMY_FILE)
        # "Zone" exists in all versions
        assert len(diagnostics) == 0

    def test_no_idfkit_usage_no_diagnostics(self):
        source = """\
x = 1 + 2
print(x)
"""
        diagnostics = lint_source(source, DUMMY_FILE)
        assert len(diagnostics) == 0

    def test_nonexistent_object_type(self):
        source = """\
from idfkit import new_document
doc = new_document()
x = doc["CompletelyFakeObject"]
"""
        diagnostics = lint_source(source, DUMMY_FILE)
        assert len(diagnostics) == 1
        assert "CompletelyFakeObject" in diagnostics[0].message
        assert "not available" in diagnostics[0].message

    def test_version_specific_object_type(self):
        # Check a type that only exists in recent versions against older ones
        # We check against a small set of versions to keep the test fast
        source = """\
from idfkit import new_document
doc = new_document()
x = doc["Zone"]
"""
        # Zone exists in all versions, so no diagnostics
        diagnostics = lint_source(source, DUMMY_FILE, versions=[(8, 9, 0), (25, 2, 0)])
        assert len(diagnostics) == 0

    def test_diagnostics_include_file_and_line(self):
        source = """\
from idfkit import new_document
doc = new_document()
x = doc["TotallyFakeType"]
"""
        diagnostics = lint_source(source, DUMMY_FILE)
        assert len(diagnostics) >= 1
        d = diagnostics[0]
        assert d.file == DUMMY_FILE
        assert d.line == 3
        assert d.col >= 0

    def test_field_lint_nonexistent_field(self):
        source = """\
from idfkit import new_document
doc = new_document()
zone = doc.add("Zone", "Office", completely_fake_field=1.0)
"""
        diagnostics = lint_source(source, DUMMY_FILE, versions=[(25, 2, 0)])
        field_diags = [d for d in diagnostics if "completely_fake_field" in d.message]
        assert len(field_diags) == 1
        assert "not available" in field_diags[0].message

    def test_valid_field_no_diagnostics(self):
        source = """\
from idfkit import new_document
doc = new_document()
zone = doc.add("Zone", "Office", x_origin=0.0)
"""
        diagnostics = lint_source(source, DUMMY_FILE, versions=[(25, 2, 0)])
        assert len(diagnostics) == 0
