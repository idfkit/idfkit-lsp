"""The launch probe contract: the exit status of ``python -m idfkit_lsp --version``.

The editor client runs this command before it starts the source server, and another editor's launch
configuration can run the same command, so the contract is tested here rather than in the client.

Each case runs the command against one of three interpreter states: the server fully installed,
nothing installed, or the server present without its libraries.
"""

from __future__ import annotations

import os
import subprocess
import sys
import venv
from importlib import metadata
from typing import TYPE_CHECKING

import pytest

from .conftest import REPOSITORY_ROOT
from .test_no_client import _client_text

if TYPE_CHECKING:
    from pathlib import Path

    from .harness import ServerDescription

_PROBE_ARGS = ("-m", "idfkit_lsp", "--version")

# Long enough for an interpreter compiling the server's modules on a slow runner.
_PROBE_TIMEOUT = 60.0


def _probe(
    interpreter: str, cwd: Path, *, python_path: str | None = None
) -> subprocess.CompletedProcess[str]:
    """Run the probe with standard input open and silent, the case that could wait forever.

    ``subprocess.run`` closes a ``PIPE`` before it waits, which a server would read as end of file
    and exit. The read end of a pipe held open here is passed instead, so a probe that fell through
    to the server reaches the timeout.
    """
    environment = {key: value for key, value in os.environ.items() if key != "PYTHONPATH"}
    if python_path is not None:
        environment["PYTHONPATH"] = python_path
    read_end, write_end = os.pipe()
    try:
        return subprocess.run(
            [interpreter, *_PROBE_ARGS],
            cwd=str(cwd),
            env=environment,
            stdin=read_end,
            capture_output=True,
            text=True,
            timeout=_PROBE_TIMEOUT,
            check=False,
        )
    finally:
        os.close(read_end)
        os.close(write_end)


@pytest.fixture(scope="module")
def clean_interpreter(tmp_path_factory: pytest.TempPathFactory) -> str:
    """An interpreter with nothing installed, as ``python3`` is on a machine new to this server."""
    root = tmp_path_factory.mktemp("clean-environment")
    # Symbolic links, as `python -m venv` itself uses on POSIX: a copied interpreter cannot find its
    # shared library when the base installation is relocatable, as uv's is.
    venv.EnvBuilder(with_pip=False, symlinks=sys.platform != "win32").create(root)
    relative = "Scripts/python.exe" if sys.platform == "win32" else "bin/python"
    return str(root / relative)


class TestAnInterpreterThatCanRunTheServer:
    def test_exits_zero_and_names_the_installed_level(
        self, source_server_description: ServerDescription, tmp_path: Path
    ) -> None:
        # The description's overlay carries a rehearsal's candidate library, when there is one.
        overlay = source_server_description.env or {}
        completed = _probe(
            source_server_description.command, tmp_path, python_path=overlay.get("PYTHONPATH")
        )

        assert completed.returncode == 0, completed.stderr
        assert completed.stdout.strip() == f"idfkit-lsp {metadata.version('idfkit-lsp')}"


class TestAnInterpreterThatCannotRunTheServer:
    def test_without_the_package_it_fails_and_says_why(
        self, clean_interpreter: str, tmp_path: Path
    ) -> None:
        completed = _probe(clean_interpreter, tmp_path)

        assert completed.returncode != 0
        assert "idfkit_lsp" in completed.stderr

    def test_with_the_package_but_not_its_libraries_it_fails_and_says_why(
        self, clean_interpreter: str, tmp_path: Path
    ) -> None:
        """An import probe that stopped at the package itself would call this interpreter able."""
        completed = _probe(
            clean_interpreter, tmp_path, python_path=str(REPOSITORY_ROOT / "server" / "src")
        )

        assert completed.returncode != 0
        assert "No module named" in completed.stderr


class TestTheClientAsksTheSameQuestion:
    def test_the_client_source_states_the_probe_this_suite_holds_to(self) -> None:
        """The client and this suite must not drift to two different questions."""
        text = _client_text()

        assert '"--version"' in text
        assert '"-m", "idfkit_lsp"' in text

    def test_a_cleared_setting_reaches_the_probe_as_the_default_interpreter(self) -> None:
        """An empty command makes the probe refuse the spawn, and the setting means the default."""
        assert 'return configured || "python3";' in _client_text()
