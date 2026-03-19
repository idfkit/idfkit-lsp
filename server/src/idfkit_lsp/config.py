"""Configuration and file discovery for idfkit-lint."""

from __future__ import annotations

import fnmatch
import subprocess
import sys
import typing
from dataclasses import dataclass

if typing.TYPE_CHECKING:
    from pathlib import Path


@dataclass(frozen=True)
class LintConfig:
    """Resolved lint configuration from CLI args and pyproject.toml."""

    paths: tuple[Path, ...]
    versions: tuple[tuple[int, int, int], ...] | None = None
    exclude: tuple[str, ...] = ()
    respect_gitignore: bool = True


def find_pyproject(start: Path | None = None) -> Path | None:
    """Walk from *start* (default: cwd) upward, return first pyproject.toml found."""
    from pathlib import Path

    current = (start or Path.cwd()).resolve()
    while True:
        candidate = current / "pyproject.toml"
        if candidate.is_file():
            return candidate
        parent = current.parent
        if parent == current:
            return None
        current = parent


def _load_toml(path: Path) -> dict[str, typing.Any]:
    """Load a TOML file using tomllib (3.11+) or tomli (3.10)."""
    if sys.version_info >= (3, 11):
        import tomllib
    else:
        try:
            import tomli as tomllib  # type: ignore[no-redef]
        except ImportError as err:
            raise ImportError(
                "tomli is required on Python <3.11. Install idfkit-lsp[lint]."
            ) from err

    with open(path, "rb") as f:
        return tomllib.load(f)


def _parse_version(s: str) -> tuple[int, int, int]:
    parts = s.strip().split(".")
    if len(parts) == 2:
        parts.append("0")
    if len(parts) != 3:
        raise ValueError(f"Invalid version: {s!r}")
    return (int(parts[0]), int(parts[1]), int(parts[2]))


def load_pyproject_config(pyproject_path: Path) -> dict[str, typing.Any]:
    """Extract ``[tool.idfkit-lint]`` from a pyproject.toml, return raw dict."""
    data = _load_toml(pyproject_path)
    return data.get("tool", {}).get("idfkit-lint", {})


def _resolve_versions(
    cfg: dict[str, typing.Any],
    *,
    cli_versions: tuple[tuple[int, int, int], ...] | None,
    cli_min_version: tuple[int, int, int] | None,
    cli_max_version: tuple[int, int, int] | None,
) -> tuple[tuple[int, int, int], ...] | None:
    """Resolve versions from CLI args and config, CLI takes precedence."""
    from idfkit import ENERGYPLUS_VERSIONS

    if cli_versions is not None:
        return cli_versions

    if cli_min_version is not None or cli_max_version is not None:
        versions = list(ENERGYPLUS_VERSIONS)
        if cli_min_version is not None:
            versions = [v for v in versions if v >= cli_min_version]
        if cli_max_version is not None:
            versions = [v for v in versions if v <= cli_max_version]
        return tuple(versions)

    # Fall back to config file
    cfg_versions_raw = cfg.get("versions")
    if cfg_versions_raw is not None:
        return tuple(_parse_version(v) for v in cfg_versions_raw)

    cfg_min = cfg.get("min-version")
    cfg_max = cfg.get("max-version")
    if cfg_min is not None or cfg_max is not None:
        versions = list(ENERGYPLUS_VERSIONS)
        if cfg_min is not None:
            min_v = _parse_version(cfg_min)
            versions = [v for v in versions if v >= min_v]
        if cfg_max is not None:
            max_v = _parse_version(cfg_max)
            versions = [v for v in versions if v <= max_v]
        return tuple(versions)

    return None


def load_config(
    *,
    cli_paths: tuple[Path, ...] | None = None,
    cli_versions: tuple[tuple[int, int, int], ...] | None = None,
    cli_min_version: tuple[int, int, int] | None = None,
    cli_max_version: tuple[int, int, int] | None = None,
    cli_exclude: tuple[str, ...] | None = None,
    cli_respect_gitignore: bool | None = None,
) -> LintConfig:
    """Merge CLI args, pyproject.toml, and defaults into a `LintConfig`."""
    from pathlib import Path

    pyproject_path = find_pyproject()
    cfg: dict[str, typing.Any] = {}
    if pyproject_path is not None:
        cfg = load_pyproject_config(pyproject_path)

    # Paths: CLI > config "include" > current directory
    if cli_paths is not None and len(cli_paths) > 0:
        paths = cli_paths
    elif cfg.get("include"):
        paths = tuple(Path(p) for p in cfg["include"])
    else:
        paths = (Path("."),)

    versions = _resolve_versions(
        cfg,
        cli_versions=cli_versions,
        cli_min_version=cli_min_version,
        cli_max_version=cli_max_version,
    )

    # Exclude: CLI > config > empty
    if cli_exclude is not None:
        exclude = cli_exclude
    elif cfg.get("exclude"):
        exclude = tuple(cfg["exclude"])
    else:
        exclude = ()

    # Gitignore: CLI > config > True
    if cli_respect_gitignore is not None:
        respect_gitignore = cli_respect_gitignore
    elif "respect-gitignore" in cfg:
        respect_gitignore = bool(cfg["respect-gitignore"])
    else:
        respect_gitignore = True

    return LintConfig(
        paths=paths,
        versions=versions,
        exclude=exclude,
        respect_gitignore=respect_gitignore,
    )


def _git_ls_files(directory: Path) -> list[Path] | None:
    """Run ``git ls-files`` to get tracked + untracked-but-not-ignored .py files.

    Returns None on failure (not a git repo, git not installed, etc.).
    """
    try:
        result = subprocess.run(
            ["git", "ls-files", "--cached", "--others", "--exclude-standard", "*.py"],
            cwd=directory,
            capture_output=True,
            text=True,
            check=True,
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None

    files: list[Path] = []
    for line in result.stdout.splitlines():
        line = line.strip()
        if line:
            files.append(directory / line)
    return files


def discover_files(config: LintConfig) -> list[Path]:
    """Discover Python files to lint based on *config*."""
    collected: list[Path] = []

    for path in config.paths:
        path = path.resolve()
        if path.is_file():
            collected.append(path)
        elif path.is_dir():
            if config.respect_gitignore:
                git_files = _git_ls_files(path)
                if git_files is not None:
                    collected.extend(git_files)
                else:
                    collected.extend(path.rglob("*.py"))
            else:
                collected.extend(path.rglob("*.py"))

    # Apply exclude patterns
    if config.exclude:
        filtered: list[Path] = []
        for f in collected:
            rel = str(f)
            if not any(fnmatch.fnmatch(rel, pat) for pat in config.exclude):
                filtered.append(f)
        collected = filtered

    return sorted(set(collected))
