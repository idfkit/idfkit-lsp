"""Fixtures that put each server behind the same harness, in the runtime it actually runs in.

One suite covers both servers, so the difference between them lives here and nowhere else: the
source server is started from the first language's virtual environment, the model server from the
second language's bundle, and every test past this file asks a :class:`ProtocolClient` questions
without knowing which of the two it is holding.

**Candidate builds.** Two environment variables let the suite rehearse against an unpublished
build of either library without changing any level this repository declares, which is what FR-037
asks for and what research R8 records:

``CANDIDATE_FIRST``
    A directory holding a candidate build of the first language's library. It is placed ahead of
    the virtual environment on ``PYTHONPATH`` for the spawned source server, so that server
    resolves the candidate while ``server/pyproject.toml`` keeps declaring the pinned level.

``CANDIDATE_SECOND``
    A directory holding a candidate build of the second language's library. It is placed ahead of
    ``NODE_PATH`` for the spawned model server, so that server resolves the candidate while
    ``model-server/package.json`` keeps declaring the pinned level. ``NODE_PATH`` reaches a
    candidate laid out as an installed package tree; a candidate laid out some other way is one
    this switch cannot reach, and the session header says which build a run actually used.

Neither variable is set in ordinary use, and the header says so plainly rather than letting a run
against the published levels pass for a run against a candidate.

**The packed model server.** ``MODEL_SERVER_PACKAGE`` names a directory where the published
package was installed from its tarball (``<prefix>/node_modules/@idfkit/language-server``). The
model server is then started from that directory's bundle and resolves its libraries from that
install, not from this checkout, which is what a user of the npm package runs. A packed server that
cannot answer is a broken package rather than a missing component, so where the model server would
otherwise be skipped it fails instead.
"""

from __future__ import annotations

import inspect
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, NoReturn

import pytest

from .harness import ProtocolClient, ServerDescription, start_server

if TYPE_CHECKING:
    from collections.abc import Iterator

# The suite is run from the repository root, from ``server/``, and by a hook, so the root is taken
# from this file's own place in the tree rather than from wherever the caller was standing.
REPOSITORY_ROOT = Path(__file__).resolve().parents[2]

CANDIDATE_FIRST = "CANDIDATE_FIRST"
CANDIDATE_SECOND = "CANDIDATE_SECOND"
MODEL_SERVER_PACKAGE = "MODEL_SERVER_PACKAGE"

_SUBPATH = "@idfkit/idfkit/language"
_PROBE_TIMEOUT = 60.0

# Resolution is asked of the runtime rather than answered by looking for a directory: an export
# map, a workspace link, and a candidate on NODE_PATH all resolve, and only the runtime knows.
# The specifiers the model server accepts, in the order it accepts them. Only the shared name's
# subpath, now that ``@idfkit/idfkit`` is published. The probe has to agree with the server, because
# a probe that accepted a name the server does not would run model-text groups the server cannot
# answer. ``model-server/src/service.ts`` holds the order itself.
_ACCEPTED = (_SUBPATH,)

_PROBE = (
    "const accepted = "
    + repr(list(_ACCEPTED)).replace("'", '"')
    + "; let found = false; let last = 'nothing was tried';"
    " for (const specifier of accepted) {"
    "   try { await import(specifier); found = true; break; }"
    "   catch (error) { last = specifier + ': ' + (error?.message ?? String(error)); }"
    " }"
    " process.stdout.write(found ? 'present' : 'absent: ' + last);"
)


@dataclass(frozen=True)
class CandidateBuilds:
    """Which unpublished builds this run was pointed at, if any."""

    first: Path | None
    second: Path | None

    @classmethod
    def from_environment(cls) -> CandidateBuilds:
        return cls(first=_directory(CANDIDATE_FIRST), second=_directory(CANDIDATE_SECOND))

    def describe(self) -> str:
        if self.first is None and self.second is None:
            return (
                f"candidate builds: none. Neither {CANDIDATE_FIRST} nor {CANDIDATE_SECOND} is "
                "set, so both servers resolve the levels this repository declares."
            )
        first = (
            f"{CANDIDATE_FIRST}={self.first}, ahead of the virtual environment on PYTHONPATH"
            if self.first is not None
            else f"{CANDIDATE_FIRST} not set"
        )
        second = (
            f"{CANDIDATE_SECOND}={self.second}, ahead of NODE_PATH"
            if self.second is not None
            else f"{CANDIDATE_SECOND} not set"
        )
        return f"candidate builds: {first}; {second}"


@dataclass(frozen=True)
class ComponentProbe:
    """Whether the language service resolves for the model server, in the runtime's own words."""

    resolved: bool
    detail: str


def _directory(variable: str) -> Path | None:
    value = os.environ.get(variable, "").strip()
    if not value:
        return None
    path = Path(value).expanduser()
    if not path.is_dir():
        raise pytest.UsageError(f"{variable}={value}: not a directory")
    return path.resolve()


def _ahead_of(existing: str | None, addition: Path) -> str:
    """Put a candidate build first on a search path, keeping whatever the caller already had."""
    parts = [str(addition), *(part for part in (existing or "").split(os.pathsep) if part)]
    return os.pathsep.join(parts)


def _source_interpreter() -> str:
    """The interpreter the source server's dependencies are installed against.

    Falling back to the interpreter running the suite is right rather than merely convenient: in
    continuous integration the suite already runs on the environment under test.
    """
    for relative in ("bin/python", "Scripts/python.exe"):
        candidate = REPOSITORY_ROOT / "server" / ".venv" / relative
        if candidate.is_file():
            return str(candidate)
    return sys.executable


def _model_package() -> Path:
    """The directory the model server runs from: this checkout's, or an installed tarball's."""
    return _directory(MODEL_SERVER_PACKAGE) or REPOSITORY_ROOT / "model-server"


def _model_bundle() -> Path:
    return _model_package() / "dist" / "main.js"


def _model_description(node: str, builds: CandidateBuilds) -> ServerDescription:
    environment: dict[str, str] = {}
    if builds.second is not None:
        environment["NODE_PATH"] = _ahead_of(os.environ.get("NODE_PATH"), builds.second)
    return ServerDescription(
        name="model server",
        command=node,
        args=(str(_model_bundle()), "--stdio"),
        cwd=_model_package(),
        env=environment or None,
    )


def _probe_component(environment: dict[str, str]) -> ComponentProbe:
    node = shutil.which("node")
    if node is None:
        return ComponentProbe(False, "no node runtime is on PATH")
    merged = dict(os.environ)
    merged.update(environment)
    try:
        completed = subprocess.run(
            [node, "--input-type=module", "-e", _PROBE],
            cwd=str(_model_package()),
            env=merged,
            capture_output=True,
            text=True,
            timeout=_PROBE_TIMEOUT,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return ComponentProbe(False, f"the resolution probe could not run: {exc}")
    output = completed.stdout.strip() or completed.stderr.strip()
    return ComponentProbe(output == "present", output or "the probe said nothing")


def _missing_bundle() -> str:
    if _directory(MODEL_SERVER_PACKAGE) is not None:
        return f"the installed package has no bundle at {_model_bundle()}"
    return (
        f"the bundle {_model_bundle().relative_to(REPOSITORY_ROOT)} has not been built "
        "(make build)"
    )


def _missing_component(probe: ComponentProbe) -> str:
    return f"the language service resolves under none of {', '.join(_ACCEPTED)} ({probe.detail})"


def pytest_report_header(config: pytest.Config) -> list[str]:
    """Say at session start which builds this run resolves, so no run is silently ordinary."""
    return [
        CandidateBuilds.from_environment().describe(),
        f"source server: {_source_interpreter()} -m idfkit_lsp",
        f"model server: {_model_bundle()}",
    ]


def _skip_or_fail(reason: str) -> NoReturn:
    """Skip in a checkout, where an absence is not this repository being wrong; fail when packed."""
    if _directory(MODEL_SERVER_PACKAGE) is not None:
        pytest.fail(
            f"{MODEL_SERVER_PACKAGE} is set, so this is the published package failing: {reason}"
        )
    pytest.skip(reason)


@pytest.fixture(scope="session")
def candidate_builds() -> CandidateBuilds:
    return CandidateBuilds.from_environment()


@pytest.fixture(scope="session")
def source_server_description(candidate_builds: CandidateBuilds) -> ServerDescription:
    """How the source server is launched, for a test that needs one of its own."""
    environment: dict[str, str] = {}
    if candidate_builds.first is not None:
        environment["PYTHONPATH"] = _ahead_of(os.environ.get("PYTHONPATH"), candidate_builds.first)
    return ServerDescription(
        name="source server",
        command=_source_interpreter(),
        args=("-m", "idfkit_lsp"),
        cwd=REPOSITORY_ROOT,
        env=environment or None,
    )


@pytest.fixture(scope="session")
def model_server_description(candidate_builds: CandidateBuilds) -> ServerDescription:
    """How the model server is launched, requiring only what starting it at all requires.

    The language service is deliberately not required here: the test that asserts what the server
    says when the component is absent needs the server to start without it.
    """
    node = shutil.which("node")
    if node is None:
        pytest.skip("no node runtime is on PATH, so the model server cannot be started")
    if not _model_bundle().is_file():
        _skip_or_fail(f"the model server cannot be started: {_missing_bundle()}")
    return _model_description(node, candidate_builds)


@pytest.fixture(scope="session")
def source_server(source_server_description: ServerDescription) -> Iterator[ProtocolClient]:
    """A started, initialized source server, shared by the session: startup loads a schema."""
    client = start_server(source_server_description)
    try:
        yield client
    finally:
        client.stop()


@pytest.fixture(scope="session")
def model_server(candidate_builds: CandidateBuilds) -> Iterator[ProtocolClient]:
    """A started, initialized model server, skipped while it has nothing to answer from.

    Two things must be present and the skip names whichever is not, both of them when both are:
    the bundle this repository builds, and the language service that bundle reads every answer
    from. Neither absence is a failure, because neither is this repository being wrong; the
    component is feature 005 of the unification and is not published yet.
    """
    node = shutil.which("node")
    if node is None:
        pytest.skip("no node runtime is on PATH, so the model server cannot be started")
    description = _model_description(node, candidate_builds)
    missing: list[str] = []
    if not _model_bundle().is_file():
        missing.append(_missing_bundle())
    probe = _probe_component(description.environment())
    if not probe.resolved:
        missing.append(_missing_component(probe))
    if missing:
        _skip_or_fail("the model server cannot answer yet: " + "; and ".join(missing))
    client = start_server(description)
    try:
        yield client
    finally:
        client.stop()


@pytest.fixture(scope="session")
def declaration() -> Any:
    """The capability declaration, loaded by the loader the servers themselves read it with.

    Imported inside the fixture so that collection succeeds while the loader is still being
    written, and so that its absence reads as a skip naming the loader rather than an error
    naming this file.
    """
    try:
        from idfkit_lsp import capabilities as loader
    except ImportError as exc:
        pytest.skip(f"idfkit_lsp.capabilities is not available yet: {exc}")
    load = getattr(loader, "load", None)
    if not callable(load):
        pytest.skip("idfkit_lsp.capabilities has no load() yet")
    if inspect.signature(load).parameters:
        return load(REPOSITORY_ROOT / "capabilities.json")
    return load()
