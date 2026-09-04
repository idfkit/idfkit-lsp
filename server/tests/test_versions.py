"""The version request answers from the installed distribution, never from a literal.

Every assertion here compares what the handler returned against what ``importlib.metadata`` says
right now, rather than against a version typed into this file. A test that spelled the level out
would pass on the day it was written and go on passing after the pin moved, which is the failure
it exists to catch.
"""

from __future__ import annotations

import dataclasses
from importlib import metadata

import pytest
from lsprotocol import converters

from idfkit_lsp import capabilities
from idfkit_lsp.server import (
    DISTRIBUTION,
    VERSIONS_REQUEST,
    LibraryLevel,
    VersionReport,
    _level,
    on_versions,
    server,
)


@pytest.fixture(scope="module")
def report() -> VersionReport:
    return on_versions(None)


class TestVersionReport:
    def test_reports_this_server_own_level(self, report: VersionReport) -> None:
        assert report.version == metadata.version(DISTRIBUTION)

    def test_names_the_server_the_declaration_names(self, report: VersionReport) -> None:
        assert report.server_id == capabilities.load().source.id

    def test_reports_every_library_it_imports(self, report: VersionReport) -> None:
        imported = {library.name for library in report.libraries}
        assert {"idfkit", "pygls", "lsprotocol"} <= imported

    def test_reports_no_library_it_only_installs_for_a_test_run(
        self, report: VersionReport
    ) -> None:
        # pytest is resolved right now, in this process, and is still not a library the running
        # server imports. Reporting it would make the answer a list of what is installed rather
        # than of what this server read from.
        assert "pytest" not in {library.name for library in report.libraries}

    def test_reads_each_level_from_the_installed_distribution(self, report: VersionReport) -> None:
        for library in report.libraries:
            assert library.level == metadata.version(library.name)

    def test_reports_the_pinned_library_at_the_level_it_resolved(
        self, report: VersionReport
    ) -> None:
        levels = {library.name: library.level for library in report.libraries}
        assert levels["idfkit"] == metadata.version("idfkit")

    def test_is_a_frozen_typed_result_rather_than_a_dictionary(
        self, report: VersionReport
    ) -> None:
        assert dataclasses.is_dataclass(report)
        with pytest.raises(dataclasses.FrozenInstanceError):
            report.version = "0.0.0"  # type: ignore[misc]

    def test_serialises_to_the_response_the_editor_reads(self, report: VersionReport) -> None:
        payload = converters.get_converter().unstructure(report)
        assert payload["version"] == metadata.version(DISTRIBUTION)
        assert {"name": "idfkit", "level": metadata.version("idfkit")} in payload["libraries"]


class TestMissingDistribution:
    def test_a_library_with_no_installed_distribution_reports_no_level(self) -> None:
        assert _level("idfkit-lsp-no-such-distribution") is None

    def test_an_unreadable_level_is_stated_rather_than_invented(self) -> None:
        assert LibraryLevel(name="absent", level=None).level is None


class TestAdvertised:
    def test_the_request_is_registered_with_the_protocol(self) -> None:
        assert VERSIONS_REQUEST in server.protocol.fm.features
