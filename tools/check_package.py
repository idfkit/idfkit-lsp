"""Check the model server's npm package as a user receives it, not as this checkout holds it.

The protocol suite proves the bundle answers. It cannot prove the tarball carries the bundle, that
the declaration inside it is the root's, or that the command a user types starts anything: all
three are facts about ``npm pack`` and ``npm install``, which a checkout never runs. This check
reads the tarball ``npm pack`` wrote and starts the command an install of it put on the path.

    python -m tools.check_package --tarball <file.tgz> --installed <prefix>

``<prefix>`` is the directory the tarball was installed into, the one holding ``node_modules``.
Run by CI on every change and by the release workflow before anything is published.
"""

from __future__ import annotations

import argparse
import shutil
import tarfile
from pathlib import Path

from tests.protocol.harness import ProtocolClient, ProtocolError, ServerDescription

from ._common import Report, has_source_map_comment, read_json, repository_root

MANIFEST = "model-server/package.json"

# What the package must carry, and nothing else: a file missing breaks an install, and a file
# nobody listed is source or a map nobody meant to publish.
EXPECTED_MEMBERS = frozenset(
    {
        "package/package.json",
        "package/LICENSE",
        "package/README.md",
        "package/dist/main.js",
        "package/dist/capabilities.json",
    }
)

_STARTUP_SECONDS = 30.0


def _check_tarball(root: Path, tarball: Path, report: Report) -> None:
    with tarfile.open(tarball, "r:gz") as archive:
        members = {member.name for member in archive.getmembers() if member.isfile()}
        for missing in sorted(EXPECTED_MEMBERS - members):
            report.fail(tarball, f"the package does not carry {missing}")
        for extra in sorted(members - EXPECTED_MEMBERS):
            report.fail(tarball, f"the package carries {extra}, which nothing asked it to publish")
        if "package/dist/capabilities.json" in members:
            packed = archive.extractfile("package/dist/capabilities.json")
            declared = (root / "capabilities.json").read_bytes()
            if packed is None or packed.read() != declared:
                report.fail(
                    tarball,
                    "dist/capabilities.json differs from the root capabilities.json, so the "
                    "published server would advertise from a stale declaration",
                )
        if "package/dist/main.js" in members:
            bundle = archive.extractfile("package/dist/main.js")
            if bundle is None or has_source_map_comment(bundle.read()):
                report.fail(tarball, "dist/main.js names a source map the package does not carry")


def _check_command(installed: Path, name: str, command: str, report: Report) -> None:
    """Start the installed command and ask it who it is.

    Spoken to through the protocol suite's own client, which frames the messages, answers anything
    the server asks first, and carries the server's standard error into the failure when it does not
    answer: a command that crashes on start says why in that output and nowhere else.
    """
    executable = shutil.which(command, path=str(installed / "node_modules" / ".bin"))
    if executable is None:
        report.fail(installed, f"installing the package put no {command!r} command on the path")
        return
    client = ProtocolClient(
        ServerDescription(name=command, command=executable, args=("--stdio",), cwd=installed)
    )
    try:
        with client:
            response = client.initialize(timeout=_STARTUP_SECONDS)
    except ProtocolError as exc:
        report.fail(installed, f"{command} --stdio did not answer initialize: {exc}")
        return
    if not response.ok:
        report.fail(installed, f"{command} --stdio refused initialize: {response.error}")
        return
    result = response.result if isinstance(response.result, dict) else {}
    info = result.get("serverInfo")
    served = info.get("name") if isinstance(info, dict) else None
    if served != name:
        report.fail(
            installed,
            f"{command} --stdio answered initialize as {served!r}, not as {name!r}",
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n", 1)[0])
    parser.add_argument("--tarball", type=Path, required=True)
    parser.add_argument("--installed", type=Path, required=True)
    args = parser.parse_args(argv)

    root = repository_root()
    manifest = read_json(root / MANIFEST)
    name: str = manifest["name"]
    commands: dict[str, str] = manifest.get("bin", {})

    report = Report("check_package")
    _check_tarball(root, args.tarball, report)
    if len(commands) != 1:
        report.fail(MANIFEST, "declares other than one command, so `npx <package>` is ambiguous")
    for command in commands:
        _check_command(args.installed.resolve(), name, command, report)
    return report.finish()


if __name__ == "__main__":
    raise SystemExit(main())
