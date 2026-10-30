"""Check the VS Code extension as a user receives it, not as this checkout holds it.

The protocol suite and ``check_package`` cover the model server in a checkout and as an npm package.
Neither covers the VSIX, whose contents ``vsce`` and ``.vscodeignore`` decide, and whose model server
resolves its libraries only from inside the unpacked extension. This check starts that server from
the unpacked extension, the way the client starts it, and holds what it advertises against
``capabilities.json``.

    python -m tools.check_vsix --extension <unpacked>/extension

``<unpacked>`` is where the VSIX was unzipped, and it must lie outside this repository. A server that
cannot load the language service still starts and answers ``initialize``, but advertises none of the
model-text answers, so the comparison is what detects a VSIX without the language service. A server
that advertises them all but warns on start cannot resolve what they are answered from, and fails
too. Run by CI on every change.
"""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path
from typing import TYPE_CHECKING, Any

from tests.protocol.harness import ProtocolClient, ProtocolError, ServerDescription

from idfkit_lsp.capabilities import load

from ._common import Report, read_json, repository_root

if TYPE_CHECKING:
    from collections.abc import Mapping

BUNDLE = "model-server/dist/main.js"
DECLARATION = "capabilities.json"
MANIFEST = "package.json"

# Which entry of an `initialize` result announces which model-text request. Protocol knowledge, not
# knowledge of a model. The declaration decides which of them are expected.
MODEL_PROVIDERS: Mapping[str, str] = {
    "textDocument/semanticTokens/full": "semanticTokensProvider",
    "textDocument/diagnostic": "diagnosticProvider",
    "textDocument/completion": "completionProvider",
    "textDocument/hover": "hoverProvider",
    "textDocument/definition": "definitionProvider",
}

# Requests the declaration can mark present that `initialize` has no entry for. Anything else without
# a provider above fails the check, so the table cannot fall behind the declaration unnoticed.
_VERSIONS_REQUEST = "idfkit-lsp/versions"
_ANNOUNCED_NOWHERE = frozenset({"textDocument/publishDiagnostics", _VERSIONS_REQUEST})

_SHOW_MESSAGE = "window/showMessage"
_STARTUP_SECONDS = 30.0


def _check_location(root: Path, extension: Path, report: Report) -> None:
    """Refuse a location where the server could resolve a library the VSIX does not carry.

    Node searches every ``node_modules`` above a module, so a result from such a location would
    describe that directory rather than the VSIX.
    """
    if extension.is_relative_to(root):
        report.fail(extension, "the extension must be unpacked outside this repository")
    for parent in extension.parents:
        if (parent / "node_modules").exists():
            report.fail(
                extension,
                f"{parent / 'node_modules'} is above the extension, so the server could resolve "
                "a library from there that the VSIX does not carry",
            )


def _check_files(root: Path, extension: Path, report: Report) -> None:
    """The files the editor and the client read at activation, each at the path it is read from."""
    required = [BUNDLE]
    if (extension / MANIFEST).is_file():
        required.append(str(read_json(extension / MANIFEST)["main"]))
    else:
        report.fail(extension, f"the VSIX does not carry {MANIFEST}")
    for relative in required:
        if not (extension / relative).is_file():
            report.fail(extension, f"the VSIX does not carry {relative}")
    packaged = extension / DECLARATION
    if not packaged.is_file():
        report.fail(extension, f"the VSIX does not carry {DECLARATION}")
    elif packaged.read_bytes() != (root / DECLARATION).read_bytes():
        report.fail(
            extension,
            f"{DECLARATION} differs from the root {DECLARATION}, so the extension would advertise "
            "from a stale declaration",
        )


def _is_advertised(advertised: Mapping[str, Any], provider: str) -> bool:
    """Whether a provider is announced. The protocol's empty options object ``{}`` announces it."""
    return advertised.get(provider) not in (None, False)


def unadvertised(declared: frozenset[str], advertised: Mapping[str, Any]) -> list[str]:
    """The model-text answers the declaration marks present that the server did not advertise."""
    return sorted(
        request
        for request, provider in MODEL_PROVIDERS.items()
        if request in declared and not _is_advertised(advertised, provider)
    )


def check_advertisement(
    declared: frozenset[str],
    advertised: Mapping[str, Any],
    report: Report,
    where: Path | str,
    guard_message: str | None = None,
) -> None:
    """Hold what the server advertised against what the declaration marks present, both ways."""
    if not declared & MODEL_PROVIDERS.keys():
        report.fail(DECLARATION, "marks no model-text answer present for the model server")
    for request in sorted(declared - MODEL_PROVIDERS.keys() - _ANNOUNCED_NOWHERE):
        report.fail(
            DECLARATION,
            f"marks {request} present, which this check has no provider for; add it to "
            "MODEL_PROVIDERS",
        )
    missing = unadvertised(declared, advertised)
    if missing:
        detail = f" The server said: {guard_message}" if guard_message else ""
        report.fail(
            where,
            f"the packaged model server does not advertise {', '.join(missing)}, which "
            f"{DECLARATION} marks present. The server advertises no model-text answer when it "
            f"cannot load the language service, so the VSIX may not carry it.{detail}",
        )
    for request, provider in sorted(MODEL_PROVIDERS.items()):
        if request not in declared and _is_advertised(advertised, provider):
            report.fail(
                where,
                f"the packaged model server advertises {request}, which {DECLARATION} does not "
                "mark present",
            )


def _startup_warnings(client: ProtocolClient, report: Report, where: Path) -> list[str]:
    """What the server told the user as it started, which names the cause of any absence.

    The server warns while handling ``initialized`` and handles messages in order, so the answer to
    a request sent after it means every warning has already arrived.
    """
    try:
        client.initialized()
        client.request(_VERSIONS_REQUEST, timeout=_STARTUP_SECONDS)
    except ProtocolError as exc:
        report.fail(where, f"the server answered initialize and then stopped answering: {exc}")
    warnings: list[str] = []
    for notification in client.received_notifications:
        params = notification.params
        message = params.get("message") if isinstance(params, dict) else None
        if notification.method == _SHOW_MESSAGE and isinstance(message, str):
            warnings.append(message)
    return warnings


def _check_server(root: Path, extension: Path, report: Report) -> None:
    """Start the packaged bundle with the arguments the client uses, and read what it advertises."""
    node = shutil.which("node")
    if node is None:
        report.fail(extension, "no node runtime is on PATH, so the model server cannot be started")
        return
    declared = load(root / DECLARATION).model.present_requests
    client = ProtocolClient(
        ServerDescription(
            name="packaged model server",
            command=node,
            args=(str(extension / BUNDLE), "--stdio"),
            cwd=extension,
            # An empty value disables the variable, which would otherwise offer the server a library
            # the VSIX does not carry.
            env={"NODE_PATH": ""},
        )
    )
    try:
        with client:
            response = client.initialize(timeout=_STARTUP_SECONDS)
            if not response.ok:
                report.fail(extension, f"the server refused initialize: {response.error}")
                return
            advertised = client.server_capabilities
            warnings = _startup_warnings(client, report, extension)
    except ProtocolError as exc:
        report.fail(extension, f"the server did not answer initialize: {exc}")
        return
    said = "\n".join(warnings)
    check_advertisement(declared, advertised, report, extension, said or None)
    if said and not unadvertised(declared, advertised):
        report.fail(
            extension,
            "the packaged model server advertises every declared answer but warned on start, so "
            f"it cannot give them. The server said: {said}",
        )


def check_extension(root: Path, extension: Path) -> Report:
    """Run every rule against one unpacked extension and return what it found."""
    report = Report("check_vsix")
    resolved = extension.resolve()
    if not resolved.is_dir():
        report.fail(extension, "is not a directory, so no VSIX was unpacked there")
        return report
    _check_location(root.resolve(), resolved, report)
    _check_files(root, resolved, report)
    if report.ok:
        _check_server(root, resolved, report)
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n", 1)[0])
    parser.add_argument("--extension", type=Path, required=True)
    args = parser.parse_args(argv)
    return check_extension(repository_root(), args.extension).finish()


if __name__ == "__main__":
    raise SystemExit(main())
