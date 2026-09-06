"""Derive what the source server knows about idfkit from idfkit itself.

Principle I: this repository owns protocol, not knowledge. Which callables produce a document,
and which type names are worth inferring, are facts the library already carries in its own
resolved annotations. Reading them at startup means a rename or an addition in the library
changes this server's behaviour with nobody editing this server, which is the failure the two
written tables here used to hide: at 1.0.0rc1 the document type became generic and a new
document-producing entry point appeared, and neither raised so much as a warning.

What remains is API shape, not schema: that subscripting a document yields a collection, and that
adding to one yields an object. No library publishes that as data. No object type and no field
name appears in this module, and none may.

When derivation yields nothing the surface is empty and says so. Principle IV applied to this
server's knowledge of itself: a server that cannot tell a document from a string offers nothing
rather than falling back on a table that was wrong the day it was written.
"""

from __future__ import annotations

import inspect
import logging
import typing
from dataclasses import dataclass
from functools import lru_cache
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:
    from collections.abc import Mapping

    from idfkit_lsp.analyzer import IdfKitType

log = logging.getLogger(__name__)

# The library's Python API shape, which is the residual recorded in the plan's Complexity
# Tracking. These are method names on idfkit's own containers, never schema: `__getitem__` on a
# document names the collection type, and `add` on a document names the object type.
_COLLECTION_ROUTE = "__getitem__"
_OBJECT_ROUTE = "add"


@dataclass(frozen=True)
class LibrarySurface:
    """What the analyzer needs to know about the installed library, derived from it."""

    #: Public callables whose resolved return annotation IS the document type.
    document_factories: frozenset[str]
    #: Public callables that hand the document back INSIDE a result object, mapped to the
    #: attributes of that object which hold one. A call to one of these is not a document, and
    #: saying it is would offer document members on an object that has none.
    document_carriers: Mapping[str, frozenset[str]]
    type_names: Mapping[str, IdfKitType]
    source: Literal["derived", "fallback"]


_EMPTY_SURFACE = LibrarySurface(
    document_factories=frozenset(),
    document_carriers=MappingProxyType({}),
    type_names=MappingProxyType({}),
    source="fallback",
)


# ---------------------------------------------------------------------------
# Annotation resolution
# ---------------------------------------------------------------------------


def _resolve_return(func: Any) -> Any | None:
    """Resolve *func*'s return annotation against the module that defines it.

    idfkit uses ``from __future__ import annotations``, so annotations arrive as strings and are
    meaningless until resolved. An annotation that cannot be resolved skips the name it belongs
    to; it never propagates out of here, because an unresolvable annotation in a library release
    must not stop the server from starting.
    """
    try:
        hints = typing.get_type_hints(func)
    except Exception:
        # Any resolution failure means "skip this name", never "stop the server".
        log.debug("library_surface: get_type_hints failed for %r", func, exc_info=True)
    else:
        if "return" in hints:
            return hints["return"]

    try:
        annotation = inspect.signature(func, eval_str=True).return_annotation
    except Exception:
        log.debug("library_surface: signature failed for %r", func, exc_info=True)
        return None
    return None if annotation is inspect.Signature.empty else annotation


def _unwrap(annotation: Any) -> Any:
    """Reduce a generic subscript to its origin, so ``Doc[bool]`` reads as ``Doc``."""
    origin = typing.get_origin(annotation)
    return annotation if origin is None else origin


def _resolved_class(owner: type, method_name: str) -> type | None:
    """The class a method of *owner* returns, or None when that cannot be established."""
    method = getattr(owner, method_name, None)
    if method is None:
        return None
    returned = _resolve_return(method)
    if returned is None:
        return None
    candidate = _unwrap(returned)
    return candidate if inspect.isclass(candidate) else None


# ---------------------------------------------------------------------------
# Derivation
# ---------------------------------------------------------------------------


def _callables(members: Mapping[str, Any]) -> list[tuple[str, Any]]:
    """Public callables worth resolving, in a stable order.

    Classes and modules are excluded: a document factory is a function that hands a document
    back, and the document type is identified by what those functions return rather than by
    being named here.
    """
    return [
        (name, obj)
        for name, obj in sorted(members.items())
        if callable(obj) and not inspect.isclass(obj) and not inspect.ismodule(obj)
    ]


def _returns(members: Mapping[str, Any]) -> dict[str, Any]:
    """Each public callable's resolved return annotation, resolved once.

    ``typing.get_type_hints`` imports and evaluates a module's namespace, so resolving the same
    callable twice costs twice; both passes below read this instead.
    """
    resolved: dict[str, Any] = {}
    for name, obj in _callables(members):
        returned = _resolve_return(obj)
        if returned is not None:
            resolved[name] = returned
    return resolved


def _document_type(returns: Mapping[str, Any]) -> type | None:
    """The document type: a class a public callable returns that behaves like a document.

    "Behaves like a document" is the API shape above, and it is the anchor the whole derivation
    hangs from: a returned class whose subscript yields some other class, and which can be added
    to. Nothing here names a type.
    """
    for _, returned in sorted(returns.items()):
        candidate = _unwrap(returned)
        if not inspect.isclass(candidate):
            continue
        collection = _resolved_class(candidate, _COLLECTION_ROUTE)
        if collection is None or collection is candidate:
            continue
        if _resolved_class(candidate, _OBJECT_ROUTE) is None:
            continue
        return candidate
    return None


def _document_attributes(returned: Any, document_type: type) -> frozenset[str]:
    """The attributes of a result type that hold a document, empty when it holds none.

    This is how a diagnostics-carrying entry point is found. Naming the attributes rather than
    reporting a boolean is what keeps the answer true: the call returns the result object, and
    only reading the named attribute off it yields a document. Reporting the call itself as a
    document would offer document members on an object that has none, which is precisely the
    plausible-but-wrong answer Principle IV forbids.
    """
    container = _unwrap(returned)
    if not inspect.isclass(container):
        return frozenset()
    try:
        fields = typing.get_type_hints(container)
    except Exception:
        # An unresolvable result type simply carries nothing.
        log.debug("library_surface: get_type_hints failed for %r", container, exc_info=True)
        return frozenset()
    return frozenset(name for name, field in fields.items() if _unwrap(field) is document_type)


def _document_factories(returns: Mapping[str, Any], document_type: type) -> frozenset[str]:
    """Callables that return the document itself, which is the only kind that binds directly."""
    return frozenset(
        name for name, returned in returns.items() if _unwrap(returned) is document_type
    )


def _document_carriers(
    returns: Mapping[str, Any], document_type: type
) -> Mapping[str, frozenset[str]]:
    """Callables that return something holding a document, mapped to where it is held."""
    carriers = {
        name: attributes
        for name, returned in returns.items()
        if _unwrap(returned) is not document_type
        and (attributes := _document_attributes(returned, document_type))
    }
    return MappingProxyType(carriers)


def _type_names(document_type: type) -> Mapping[str, IdfKitType]:
    """Map the three container type names onto the kinds the analyzer infers.

    Every name comes from the library's own classes. The document is the anchor, its subscript
    names the collection, and the collection's subscript names the object where it can, falling
    back to what adding to a document returns when the collection's is a type variable.
    """
    from idfkit_lsp.analyzer import IdfKitType

    collection_type = _resolved_class(document_type, _COLLECTION_ROUTE)
    if collection_type is None:
        return MappingProxyType({})

    object_type = _resolved_class(collection_type, _COLLECTION_ROUTE)
    if object_type is None or object_type is collection_type:
        object_type = _resolved_class(document_type, _OBJECT_ROUTE)
    if object_type is None:
        return MappingProxyType({})

    return MappingProxyType(
        {
            document_type.__name__: IdfKitType.DOCUMENT,
            collection_type.__name__: IdfKitType.COLLECTION,
            object_type.__name__: IdfKitType.OBJECT,
        }
    )


def derive_surface(members: Mapping[str, Any]) -> LibrarySurface:
    """Derive a surface from a library's public members, or report that it could not be."""
    returns = _returns(members)
    document_type = _document_type(returns)
    if document_type is None:
        log.warning("library_surface: no document type found; the surface is empty")
        return _EMPTY_SURFACE

    factories = _document_factories(returns, document_type)
    carriers = _document_carriers(returns, document_type)
    type_names = _type_names(document_type)
    if not factories or not type_names:
        log.warning("library_surface: derivation incomplete; the surface is empty")
        return _EMPTY_SURFACE

    log.debug(
        "library_surface: derived %d factories, %d carriers and %d type names",
        len(factories),
        len(carriers),
        len(type_names),
    )
    return LibrarySurface(
        document_factories=factories,
        document_carriers=carriers,
        type_names=type_names,
        source="derived",
    )


def public_members() -> Mapping[str, Any]:
    """The installed library's public surface, as name to object."""
    try:
        import idfkit
    except Exception:
        # A server whose library is missing still has to start, and then answer nothing.
        log.warning("library_surface: idfkit could not be imported", exc_info=True)
        return {}

    members: dict[str, Any] = {}
    for name in dir(idfkit):
        if name.startswith("_"):
            continue
        try:
            members[name] = getattr(idfkit, name)
        except Exception:
            # A lazy attribute that raises on access is simply not part of the surface.
            log.debug("library_surface: %s could not be read", name, exc_info=True)
    return members


@lru_cache(maxsize=1)
def load_library_surface() -> LibrarySurface:
    """The derived surface, resolved once and held for the life of the process."""
    return derive_surface(public_members())
