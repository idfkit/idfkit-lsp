"""Cross-version EnergyPlus compatibility linter.

Analyses Python source files that use idfkit and reports object types or
fields that do not exist in all targeted EnergyPlus schema versions.
"""

from __future__ import annotations

import typing
from dataclasses import dataclass

from idfkit import ENERGYPLUS_VERSIONS

from idfkit_lsp.analyzer import IdfKitAnalyzer
from idfkit_lsp.schema_cache import SchemaCache

if typing.TYPE_CHECKING:
    from pathlib import Path

    from idfkit_lsp.config import LintConfig


@dataclass(frozen=True)
class LintDiagnostic:
    """A single lint finding with location and version information."""

    file: Path
    line: int  # 1-based
    col: int  # 0-based
    message: str
    missing_versions: list[tuple[int, int, int]]


def _version_str(v: tuple[int, int, int]) -> str:
    return f"{v[0]}.{v[1]}.{v[2]}"


def _format_version_range(versions: list[tuple[int, int, int]]) -> str:
    """Format a list of versions into a human-readable range string."""
    if not versions:
        return ""
    sorted_v = sorted(versions)
    if len(sorted_v) <= 3:
        return ", ".join(_version_str(v) for v in sorted_v)
    return f"{_version_str(sorted_v[0])}-{_version_str(sorted_v[-1])} ({len(sorted_v)} versions)"


def lint_source(
    source: str,
    file: Path,
    *,
    versions: list[tuple[int, int, int]] | None = None,
) -> list[LintDiagnostic]:
    """Lint a single source string for cross-version compatibility issues.

    Args:
        source: Python source code.
        file: Path used for diagnostic messages.
        versions: E+ versions to check against. Defaults to all supported versions.

    Returns:
        List of diagnostics, one per incompatible usage.
    """
    versions = versions or list(ENERGYPLUS_VERSIONS)

    analyzer = IdfKitAnalyzer(track_usages=True)
    analyzer.analyze(source)

    if not analyzer.object_type_usages and not analyzer.field_usages:
        return []

    # Load schemas for all target versions
    schemas: dict[tuple[int, int, int], SchemaCache] = {}
    for v in versions:
        schemas[v] = SchemaCache(version=v)

    diagnostics: list[LintDiagnostic] = []

    # Check object type usages
    for usage in analyzer.object_type_usages:
        missing = [v for v, schema in schemas.items() if usage.object_type not in schema]
        if missing:
            diagnostics.append(
                LintDiagnostic(
                    file=file,
                    line=usage.line,
                    col=usage.col,
                    message=(
                        f'Object type "{usage.object_type}" not available in E+ '
                        f"{_format_version_range(missing)}"
                    ),
                    missing_versions=sorted(missing),
                )
            )

    # Check field usages
    for usage in analyzer.field_usages:
        missing: list[tuple[int, int, int]] = []
        for v, schema in schemas.items():
            if usage.object_type not in schema:
                continue  # object type itself missing — already reported above
            fields = schema.get_field_python_names(usage.object_type)
            if usage.field_name not in fields:
                missing.append(v)
        if missing:
            diagnostics.append(
                LintDiagnostic(
                    file=file,
                    line=usage.line,
                    col=usage.col,
                    message=(
                        f'Field "{usage.field_name}" on "{usage.object_type}" not available in E+ '
                        f"{_format_version_range(missing)}"
                    ),
                    missing_versions=sorted(missing),
                )
            )

    return diagnostics


def lint_file(
    path: Path,
    *,
    versions: list[tuple[int, int, int]] | None = None,
) -> list[LintDiagnostic]:
    """Lint a single Python file."""
    source = path.read_text(encoding="utf-8")
    return lint_source(source, path, versions=versions)


def lint_paths(config: LintConfig) -> list[LintDiagnostic]:
    """Lint files discovered via *config* for cross-version compatibility."""
    from idfkit_lsp.config import discover_files

    files = discover_files(config)
    versions = list(config.versions) if config.versions else None
    all_diagnostics: list[LintDiagnostic] = []
    for py_file in files:
        all_diagnostics.extend(lint_file(py_file, versions=versions))
    return all_diagnostics
