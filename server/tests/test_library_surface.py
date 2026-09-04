"""Tests for deriving the source server's library knowledge from the installed library.

Nothing here asserts against a list of names written in this file. Every expectation is either
read back out of the installed library or is about the shape of the derivation, because a test
holding the table the code deleted would put the table straight back.
"""

from __future__ import annotations

import inspect
import typing
from typing import TYPE_CHECKING, Any

import idfkit
import pytest

from idfkit_lsp import library_surface
from idfkit_lsp.analyzer import IdfKitType
from idfkit_lsp.library_surface import (
    LibrarySurface,
    derive_surface,
    load_library_surface,
    public_members,
)

if TYPE_CHECKING:
    from collections.abc import Iterator


@pytest.fixture
def uncached() -> Iterator[None]:
    """Run with the process-wide cache cleared before and after."""
    load_library_surface.cache_clear()
    yield
    load_library_surface.cache_clear()


@pytest.fixture
def surface() -> LibrarySurface:
    return derive_surface(public_members())


def _returned_type(name: str) -> Any:
    """What the installed library says the public callable *name* returns."""
    return inspect.signature(getattr(idfkit, name), eval_str=True).return_annotation


class TestPublicMembers:
    def test_reads_the_installed_library(self) -> None:
        members = public_members()
        assert members
        assert all(not name.startswith("_") for name in members)
        assert all(getattr(idfkit, name) is obj for name, obj in members.items())


class TestDerivation:
    def test_source_is_derived(self, surface: LibrarySurface) -> None:
        assert surface.source == "derived"

    def test_every_factory_is_a_public_callable(self, surface: LibrarySurface) -> None:
        assert surface.document_factories
        for name in surface.document_factories:
            assert callable(getattr(idfkit, name))

    def test_finds_the_plainly_document_returning_factories(self, surface: LibrarySurface) -> None:
        # Read the expectation out of the library: every public callable whose return annotation
        # resolves to the document type must be found, however many there happen to be.
        document_type = library_surface._document_type(public_members())
        assert document_type is not None
        expected = {
            name
            for name, obj in public_members().items()
            if callable(obj) and not inspect.isclass(obj) and not inspect.ismodule(obj)
            for returned in [library_surface._resolve_return(obj)]
            if returned is not None and library_surface._unwrap(returned) is document_type
        }
        assert expected
        assert expected <= surface.document_factories

    def test_finds_an_entry_point_that_carries_a_document_in_a_result(
        self, surface: LibrarySurface
    ) -> None:
        # The diagnostics-carrying entry point hands the document back inside a result object.
        # A factory table written by hand had no way to notice it arriving.
        document_type = library_surface._document_type(public_members())
        assert document_type is not None
        assert surface.document_carriers, (
            "nothing carries a document; the carrier route is untested"
        )
        for name, attributes in surface.document_carriers.items():
            returned = _returned_type(name)
            assert library_surface._unwrap(returned) is not document_type
            assert attributes == library_surface._document_attributes(returned, document_type)

    def test_a_carrier_is_never_also_a_factory(self, surface: LibrarySurface) -> None:
        # The two sets answer different questions. A name in both would let the analyzer bind a
        # result object as a document, which is the wrong answer this split exists to prevent.
        assert not (surface.document_factories & set(surface.document_carriers))

    def test_the_two_named_regressions_are_covered(self, surface: LibrarySurface) -> None:
        # These two are named because they are the regressions this work exists to close, not
        # because the set is written down: the direct entry point the old table had, and the
        # carrier entry point it did not. They land in different sets because they return
        # different things, and the analyzer has to tell them apart to stay truthful.
        assert "load_idf" in surface.document_factories
        assert "load_idf_with_diagnostics" in surface.document_carriers

    def test_type_names_cover_the_three_kinds(self, surface: LibrarySurface) -> None:
        # The three container kinds, and only those. DOCUMENT_CARRIER names what an entry point
        # returns rather than a type an annotation can mention, so no name maps to it.
        containers = set(IdfKitType) - {IdfKitType.DOCUMENT_CARRIER}
        assert set(surface.type_names.values()) == containers

    def test_type_names_are_the_library_s_own_classes(self, surface: LibrarySurface) -> None:
        for name in surface.type_names:
            assert inspect.isclass(getattr(idfkit, name))
            assert getattr(idfkit, name).__name__ == name

    def test_document_kind_is_what_the_factories_return(self, surface: LibrarySurface) -> None:
        document_type = library_surface._document_type(public_members())
        assert document_type is not None
        assert surface.type_names[document_type.__name__] is IdfKitType.DOCUMENT


class TestFallback:
    def test_nothing_to_derive_from_yields_an_empty_surface(self) -> None:
        empty = derive_surface({})
        assert empty.source == "fallback"
        assert empty.document_factories == frozenset()
        assert dict(empty.document_carriers) == {}
        assert dict(empty.type_names) == {}

    def test_a_surface_without_a_document_type_yields_nothing(self) -> None:
        def plain() -> str:
            return ""

        assert derive_surface({"plain": plain}).source == "fallback"

    def test_loader_reports_fallback_rather_than_substituting_a_table(
        self, monkeypatch: pytest.MonkeyPatch, uncached: None
    ) -> None:
        monkeypatch.setattr(library_surface, "public_members", dict)
        loaded = load_library_surface()
        assert loaded.source == "fallback"
        assert loaded.document_factories == frozenset()
        assert dict(loaded.document_carriers) == {}
        assert dict(loaded.type_names) == {}


class TestCaching:
    def test_derived_once_per_process(self, uncached: None) -> None:
        assert load_library_surface() is load_library_surface()

    def test_the_loader_derives_from_the_installed_library(self, uncached: None) -> None:
        assert load_library_surface() == derive_surface(public_members())


class TestUnwrapping:
    def test_a_generic_subscript_reduces_to_its_origin(self, surface: LibrarySurface) -> None:
        # The single step that closes both silent regressions: the document type is generic, so
        # its factories' return annotations arrive subscripted and must reduce to their origin.
        document_type = library_surface._document_type(public_members())
        assert document_type is not None
        subscripted = [
            returned
            for name in surface.document_factories
            for returned in [_returned_type(name)]
            if typing.get_args(returned) and library_surface._unwrap(returned) is document_type
        ]
        assert subscripted, "the document type is no longer generic; this route is untested"
