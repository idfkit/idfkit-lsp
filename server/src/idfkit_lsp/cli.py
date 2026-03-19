"""CLI entrypoint for idfkit-lint — cross-version EnergyPlus compatibility checker."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from idfkit_lsp.config import load_config
from idfkit_lsp.linter import LintDiagnostic, lint_paths


def _parse_version(s: str) -> tuple[int, int, int]:
    """Parse a version string like '24.1.0' or '24.1' into a tuple."""
    parts = s.strip().split(".")
    if len(parts) == 2:
        parts.append("0")
    if len(parts) != 3:
        raise argparse.ArgumentTypeError(f"Invalid version: {s!r} (expected X.Y.Z)")
    try:
        return (int(parts[0]), int(parts[1]), int(parts[2]))
    except ValueError as err:
        raise argparse.ArgumentTypeError(f"Invalid version: {s!r}") from err


def _format_diagnostic(d: LintDiagnostic) -> str:
    return f"{d.file}:{d.line}:{d.col}: {d.message}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="idfkit-lint",
        description="Check idfkit code for cross-version EnergyPlus compatibility.",
    )
    parser.add_argument(
        "paths",
        nargs="*",
        type=Path,
        help="Python files or directories to check (default: from config or '.')",
    )
    parser.add_argument(
        "--versions",
        type=str,
        default=None,
        help="Comma-separated E+ versions to check (e.g. '23.1,24.1,25.2'). Default: all",
    )
    parser.add_argument(
        "--min-version",
        type=_parse_version,
        default=None,
        help="Only check versions >= this (e.g. '22.1.0')",
    )
    parser.add_argument(
        "--max-version",
        type=_parse_version,
        default=None,
        help="Only check versions <= this (e.g. '25.2.0')",
    )
    parser.add_argument(
        "--exclude",
        action="append",
        default=None,
        help="Glob pattern to exclude (repeatable, e.g. --exclude 'tests/*')",
    )
    parser.add_argument(
        "--no-gitignore",
        action="store_true",
        default=False,
        help="Disable gitignore-aware file discovery (use plain rglob)",
    )

    args = parser.parse_args(argv)

    # Build CLI overrides
    cli_versions: tuple[tuple[int, int, int], ...] | None = None
    if args.versions:
        cli_versions = tuple(_parse_version(v) for v in args.versions.split(","))

    cli_paths = tuple(args.paths) if args.paths else None
    cli_exclude = tuple(args.exclude) if args.exclude else None
    cli_respect_gitignore: bool | None = False if args.no_gitignore else None

    config = load_config(
        cli_paths=cli_paths,
        cli_versions=cli_versions,
        cli_min_version=args.min_version,
        cli_max_version=args.max_version,
        cli_exclude=cli_exclude,
        cli_respect_gitignore=cli_respect_gitignore,
    )

    diagnostics = lint_paths(config)

    for d in diagnostics:
        print(_format_diagnostic(d), file=sys.stderr)

    if diagnostics:
        print(f"\n{len(diagnostics)} issue(s) found.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
