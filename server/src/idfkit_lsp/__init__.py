"""idfkit Language Server - intelligent editing support for idfkit EnergyPlus code."""

from importlib.metadata import PackageNotFoundError, version

# Read from the installed distribution rather than written here. This line said "0.1.0" while
# server/pyproject.toml said "0.2.0", two statements of one fact that had already drifted; the
# `idfkit-lsp/versions` request reads the same metadata, so the two answers now cannot disagree.
try:
    __version__ = version("idfkit-lsp")
except PackageNotFoundError:  # a source tree that was never installed
    __version__ = "0.0.0+unknown"
