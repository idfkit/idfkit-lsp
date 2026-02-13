"""Per-document analysis state tracking."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from idfkit_lsp.analyzer import IdfKitAnalyzer, InferredType

log = logging.getLogger(__name__)


@dataclass
class DocumentState:
    """Cached analysis state for a single open Python document."""

    uri: str
    source: str = ""
    bindings: dict[str, InferredType] = field(default_factory=dict)
    version: int = 0
    has_idfkit_import: bool = False


class DocumentStateManager:
    """Manages per-document analysis state, re-analysing on changes."""

    def __init__(self) -> None:
        self._states: dict[str, DocumentState] = {}

    def update(self, uri: str, source: str, version: int) -> DocumentState:
        """Re-analyse the document and cache the results."""
        state = self._states.get(uri)
        if state and state.version == version:
            log.debug("update: cache hit for %s v%d", uri, version)
            return state

        analyzer = IdfKitAnalyzer()
        bindings = analyzer.analyze(source)
        has_import = bool(analyzer.imported_names)

        state = DocumentState(
            uri=uri,
            source=source,
            bindings=bindings,
            version=version,
            has_idfkit_import=has_import,
        )
        self._states[uri] = state
        log.info(
            "update: analysed %s v%d — idfkit=%s bindings=%d",
            uri, version, has_import, len(bindings),
        )
        return state

    def get(self, uri: str) -> DocumentState | None:
        return self._states.get(uri)

    def remove(self, uri: str) -> None:
        self._states.pop(uri, None)
        log.debug("remove: dropped state for %s", uri)

    def get_bindings_at_line(self, uri: str, line: int) -> dict[str, InferredType]:
        """Get type bindings visible at a specific line (for completion context).

        *line* is 1-based (matching AST lineno convention).
        """
        state = self._states.get(uri)
        if not state:
            return {}
        analyzer = IdfKitAnalyzer()
        return analyzer.analyze_at_line(state.source, line)
