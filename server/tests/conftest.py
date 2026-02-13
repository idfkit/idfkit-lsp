"""Shared fixtures for idfkit-lsp tests."""

from __future__ import annotations

import pytest

from idfkit_lsp.schema_cache import SchemaCache


@pytest.fixture(scope="session")
def schema() -> SchemaCache:
    """A real SchemaCache backed by idfkit's bundled schema (latest version)."""
    return SchemaCache()
