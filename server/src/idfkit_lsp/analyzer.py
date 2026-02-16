"""AST-based type inference engine for idfkit usage patterns.

Performs a single-pass walk over a Python AST to infer which variables
hold idfkit types (IDFDocument, IDFCollection, IDFObject) and, where
possible, what EnergyPlus object type they are parameterised with.
"""

from __future__ import annotations

import ast
import logging
from dataclasses import dataclass, field
from enum import Enum

log = logging.getLogger(__name__)


class IdfKitType(Enum):
    """The three idfkit container types we track."""

    DOCUMENT = "IDFDocument"
    COLLECTION = "IDFCollection"
    OBJECT = "IDFObject"


@dataclass(frozen=True)
class InferredType:
    """Represents the inferred idfkit type of a variable."""

    kind: IdfKitType
    object_type: str | None = None  # e.g. "Zone", "BuildingSurface:Detailed"

    @property
    def is_document(self) -> bool:
        return self.kind == IdfKitType.DOCUMENT

    @property
    def is_collection(self) -> bool:
        return self.kind == IdfKitType.COLLECTION

    @property
    def is_object(self) -> bool:
        return self.kind == IdfKitType.OBJECT


# ---------------------------------------------------------------------------
# Scope chain for variable tracking
# ---------------------------------------------------------------------------


@dataclass
class Scope:
    """A lexical scope that maps variable names to inferred types."""

    parent: Scope | None = None
    bindings: dict[str, InferredType] = field(default_factory=dict)

    def lookup(self, name: str) -> InferredType | None:
        if name in self.bindings:
            return self.bindings[name]
        if self.parent:
            return self.parent.lookup(name)
        return None

    def bind(self, name: str, typ: InferredType) -> None:
        self.bindings[name] = typ


# ---------------------------------------------------------------------------
# Functions / constructors that produce IDFDocument
# ---------------------------------------------------------------------------

_DOCUMENT_FACTORIES: frozenset[str] = frozenset({"load_idf", "load_epjson", "new_document"})

# Type annotation names → IdfKitType
_TYPE_NAMES: dict[str, IdfKitType] = {
    "IDFDocument": IdfKitType.DOCUMENT,
    "IDFCollection": IdfKitType.COLLECTION,
    "IDFObject": IdfKitType.OBJECT,
}


# ---------------------------------------------------------------------------
# Robust parsing
# ---------------------------------------------------------------------------


def _robust_parse(source: str) -> ast.Module | None:
    """Try to parse *source*; on SyntaxError, progressively drop trailing lines.

    This handles the common case where the user is mid-edit and the current
    line is incomplete (e.g. ``doc["Zon`` with no closing quote).  All lines
    *above* the cursor are typically valid Python and contain the type
    information the LSP providers need.
    """
    try:
        return ast.parse(source)
    except SyntaxError:
        pass

    lines = source.splitlines(keepends=True)
    for drop in range(1, min(len(lines), 5)):
        truncated = "".join(lines[: len(lines) - drop])
        try:
            tree = ast.parse(truncated)
            log.debug("robust_parse: succeeded after dropping %d trailing line(s)", drop)
            return tree
        except SyntaxError:
            continue
    log.debug("robust_parse: failed even after dropping up to 4 trailing lines")
    return None


# ---------------------------------------------------------------------------
# Analyzer
# ---------------------------------------------------------------------------


class IdfKitAnalyzer(ast.NodeVisitor):
    """Single-pass AST visitor that builds variable → InferredType mappings."""

    def __init__(self) -> None:
        self.scope = Scope()
        self.imported_names: dict[str, str] = {}  # local_name → qualified_name
        # Accumulate all bindings across all scopes (inner scopes override)
        self._all_bindings: dict[str, InferredType] = {}

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def analyze(self, source: str) -> dict[str, InferredType]:
        """Parse *source* and return all bindings found across all scopes.

        If the full source has syntax errors (common during editing), we
        progressively trim trailing lines until parsing succeeds.
        """
        tree = _robust_parse(source)
        if tree is None:
            log.debug("analyze: parse returned None — no bindings")
            return {}
        self.visit(tree)
        bindings = self._collect_bindings()
        log.debug(
            "analyze: %d binding(s), imports=%s",
            len(bindings),
            list(self.imported_names.keys()),
        )
        return bindings

    def analyze_at_line(self, source: str, line: int) -> dict[str, InferredType]:
        """Analyze statements up to and including *line* (1-based)."""
        tree = _robust_parse(source)
        if tree is None:
            return {}
        return self.analyze_tree_at_line(tree, line)

    def analyze_tree_at_line(self, tree: ast.Module, line: int) -> dict[str, InferredType]:
        """Analyze a pre-parsed AST up to and including *line* (1-based)."""
        for node in ast.iter_child_nodes(tree):
            if hasattr(node, "lineno") and node.lineno > line:  # pyright: ignore[reportAttributeAccessIssue]
                break
            self.visit(node)
        return self._collect_bindings()

    # ------------------------------------------------------------------
    # Import tracking
    # ------------------------------------------------------------------

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            if alias.name == "idfkit" or alias.name.startswith("idfkit."):
                local = alias.asname or alias.name
                self.imported_names[local] = alias.name

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        if node.module and (node.module == "idfkit" or node.module.startswith("idfkit.")):
            for alias in node.names:
                local = alias.asname or alias.name
                self.imported_names[local] = f"{node.module}.{alias.name}"

    # ------------------------------------------------------------------
    # Assignments
    # ------------------------------------------------------------------

    def visit_Assign(self, node: ast.Assign) -> None:
        inferred = self._infer_type(node.value)
        if inferred:
            for target in node.targets:
                if isinstance(target, ast.Name):
                    self._bind(target.id, inferred)
        self.generic_visit(node)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        # Prefer the value over the annotation (value is more specific)
        if node.value:
            inferred = self._infer_type(node.value)
            if inferred and isinstance(node.target, ast.Name):
                self._bind(node.target.id, inferred)
                self.generic_visit(node)
                return
        # Fall back to the annotation
        inferred = self._infer_from_annotation(node.annotation)
        if inferred and isinstance(node.target, ast.Name):
            self._bind(node.target.id, inferred)
        self.generic_visit(node)

    # ------------------------------------------------------------------
    # For-loop iteration
    # ------------------------------------------------------------------

    def visit_For(self, node: ast.For) -> None:
        iter_type = self._infer_type(node.iter)
        if iter_type and iter_type.is_collection and isinstance(node.target, ast.Name):
            self._bind(
                node.target.id,
                InferredType(IdfKitType.OBJECT, object_type=iter_type.object_type),
            )
        # Visit body and orelse
        for child in node.body:
            self.visit(child)
        for child in node.orelse:
            self.visit(child)

    # ------------------------------------------------------------------
    # Function definitions (scoped parameters)
    # ------------------------------------------------------------------

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        inner = Scope(parent=self.scope)
        for arg in node.args.args:
            if arg.annotation:
                inferred = self._infer_from_annotation(arg.annotation)
                if inferred:
                    inner.bind(arg.arg, inferred)
                    self._all_bindings[arg.arg] = inferred
        old = self.scope
        self.scope = inner
        for child in node.body:
            self.visit(child)
        self.scope = old

    visit_AsyncFunctionDef = visit_FunctionDef  # type: ignore[assignment]

    # ------------------------------------------------------------------
    # With-statement (context manager)
    # ------------------------------------------------------------------

    def visit_With(self, node: ast.With) -> None:
        for item in node.items:
            if item.optional_vars and isinstance(item.optional_vars, ast.Name):
                inferred = self._infer_type(item.context_expr)
                if inferred:
                    self._bind(item.optional_vars.id, inferred)
        for child in node.body:
            self.visit(child)

    # ------------------------------------------------------------------
    # Expression type inference
    # ------------------------------------------------------------------

    def _infer_type(self, node: ast.expr) -> InferredType | None:
        # Call: load_idf(...), doc.add(...)
        if isinstance(node, ast.Call):
            return self._infer_call(node)

        # Subscript: doc["Zone"], collection["name"]
        if isinstance(node, ast.Subscript):
            return self._infer_subscript(node)

        # Name: look up variable
        if isinstance(node, ast.Name):
            return self.scope.lookup(node.id)

        # Attribute: could be idfkit.load_idf etc. — but that's handled in _infer_call
        return None

    def _infer_call(self, node: ast.Call) -> InferredType | None:
        # Direct call: load_idf(...)
        if isinstance(node.func, ast.Name):
            if node.func.id in _DOCUMENT_FACTORIES and node.func.id in self.imported_names:
                return InferredType(IdfKitType.DOCUMENT)

        # Qualified call: idfkit.load_idf(...)
        if isinstance(node.func, ast.Attribute):
            # module.factory()
            if (
                node.func.attr in _DOCUMENT_FACTORIES
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id in self.imported_names
            ):
                return InferredType(IdfKitType.DOCUMENT)

            # doc.add("Zone", ...) → IDFObject("Zone")
            if node.func.attr == "add":
                owner = self._infer_type(node.func.value)
                if owner and owner.is_document:
                    obj_type = self._extract_string_arg(node, 0)
                    return InferredType(IdfKitType.OBJECT, object_type=obj_type)

            # collection.first() → IDFObject with same object_type
            if node.func.attr == "first":
                owner = self._infer_type(node.func.value)
                if owner and owner.is_collection:
                    return InferredType(IdfKitType.OBJECT, object_type=owner.object_type)

        return None

    def _infer_subscript(self, node: ast.Subscript) -> InferredType | None:
        value_type = self._infer_type(node.value)
        if value_type is None:
            return None

        key_str = self._extract_string_slice(node)

        # doc["Zone"] → IDFCollection("Zone")
        if value_type.is_document and key_str:
            return InferredType(IdfKitType.COLLECTION, object_type=key_str)

        # collection["name"] → IDFObject(same object_type)
        if value_type.is_collection:
            return InferredType(IdfKitType.OBJECT, object_type=value_type.object_type)

        return None

    # ------------------------------------------------------------------
    # Annotation inference
    # ------------------------------------------------------------------

    def _infer_from_annotation(self, annotation: ast.expr) -> InferredType | None:
        if isinstance(annotation, ast.Name) and annotation.id in _TYPE_NAMES:
            return InferredType(_TYPE_NAMES[annotation.id])
        if isinstance(annotation, ast.Attribute) and annotation.attr in _TYPE_NAMES:
            return InferredType(_TYPE_NAMES[annotation.attr])
        return None

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _bind(self, name: str, typ: InferredType) -> None:
        """Bind a name in the current scope and record it globally."""
        self.scope.bind(name, typ)
        self._all_bindings[name] = typ

    @staticmethod
    def _extract_string_arg(call: ast.Call, index: int) -> str | None:
        """Extract a constant string from positional argument *index*."""
        if index < len(call.args):
            arg = call.args[index]
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                return arg.value
        return None

    @staticmethod
    def _extract_string_slice(node: ast.Subscript) -> str | None:
        """Extract a constant string from a subscript slice."""
        sl = node.slice
        if isinstance(sl, ast.Constant) and isinstance(sl.value, str):
            return sl.value
        return None

    def _collect_bindings(self) -> dict[str, InferredType]:
        """Return all bindings accumulated during traversal."""
        return dict(self._all_bindings)
