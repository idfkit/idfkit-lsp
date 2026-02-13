"""Schema loading, caching, and query layer wrapping idfkit's schema system."""

from __future__ import annotations

import logging
from functools import lru_cache
from typing import Any

from idfkit import LATEST_VERSION, get_schema
from idfkit.introspection import (
    ObjectDescription,
    describe_object_type,
)
from idfkit.objects import to_python_name
from idfkit.schema import EpJSONSchema

log = logging.getLogger(__name__)


class SchemaCache:
    """Wraps an EpJSONSchema and pre-computes lookup structures for the LSP."""

    def __init__(self, version: tuple[int, int, int] = LATEST_VERSION) -> None:
        self._schema: EpJSONSchema = get_schema(version)
        self._object_types: list[str] = self._schema.object_types
        # Lowercase → canonical mapping for case-insensitive matching
        self._object_type_lower: dict[str, str] = {ot.lower(): ot for ot in self._object_types}
        # Lazy cache: obj_type → {python_name: idf_name}
        self._field_map_cache: dict[str, dict[str, str]] = {}
        log.info(
            "SchemaCache loaded: version=%s object_types=%d",
            ".".join(str(v) for v in version),
            len(self._object_types),
        )

    @property
    def object_types(self) -> list[str]:
        return self._object_types

    def __contains__(self, obj_type: str) -> bool:
        return obj_type in self._schema

    def _ensure_field_map(self, obj_type: str) -> dict[str, str]:
        """Build and cache the python_name → idf_name mapping for an object type."""
        if obj_type not in self._field_map_cache:
            idf_names = self._schema.get_field_names(obj_type)
            self._field_map_cache[obj_type] = {to_python_name(name): name for name in idf_names}
        return self._field_map_cache[obj_type]

    def get_field_python_names(self, obj_type: str) -> list[str]:
        """Return field names as snake_case python attribute names."""
        return list(self._ensure_field_map(obj_type).keys())

    def get_field_idf_name(self, obj_type: str, python_name: str) -> str | None:
        """Reverse lookup: python_name → IDF field name."""
        return self._ensure_field_map(obj_type).get(python_name)

    def get_field_schema(self, obj_type: str, idf_field_name: str) -> dict[str, Any] | None:
        """Return the raw schema dict for a field (type, units, default, min, max, enum)."""
        return self._schema.get_field_schema(obj_type, idf_field_name)

    def get_required_fields(self, obj_type: str) -> list[str]:
        """Return required IDF field names for an object type."""
        return self._schema.get_required_fields(obj_type)

    def get_group(self, obj_type: str) -> str | None:
        """Return the IDD group name for an object type."""
        return self._schema.get_group(obj_type)

    @lru_cache(maxsize=128)
    def describe(self, obj_type: str) -> ObjectDescription:
        """Return full introspection description with all field metadata."""
        return describe_object_type(self._schema, obj_type)

    def match_object_types(self, prefix: str) -> list[str]:
        """Return object types matching a case-insensitive prefix."""
        prefix_lower = prefix.lower()
        return [ot for ot in self._object_types if ot.lower().startswith(prefix_lower)]
