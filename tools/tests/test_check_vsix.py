"""The VSIX check, against unpacked trees built here and a stand-in server that speaks the protocol."""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from typing import TYPE_CHECKING

import pytest

from .._common import Report, repository_root
from ..check_vsix import (
    BUNDLE,
    DECLARATION,
    MANIFEST,
    MODEL_PROVIDERS,
    TERMINATE_SCRIPT,
    check_advertisement,
    check_extension,
)

if TYPE_CHECKING:
    from pathlib import Path

CLIENT_ENTRY = "client/dist/extension.js"
CLIENT_SCRIPT = f"client/dist/{TERMINATE_SCRIPT}"
GUARD_MESSAGE = "the language service could not be resolved here"
ALL_PROVIDERS = tuple(MODEL_PROVIDERS.values())

needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="no node runtime is on PATH")

# A minimal server over stdio. It refuses to start without `--stdio` or with NODE_PATH set, which is
# how the tests observe that the check launches it as the client does and in a clean environment.
_STAND_IN = """
if (!process.argv.includes('--stdio') || process.env.NODE_PATH) process.exit(3);
const providers = PROVIDERS;
const guard = GUARD;
let buffer = Buffer.alloc(0);
const send = (message) => {
  const body = JSON.stringify({ jsonrpc: '2.0', ...message });
  process.stdout.write(`Content-Length: ${Buffer.byteLength(body)}\\r\\n\\r\\n${body}`);
};
process.stdin.on('data', (chunk) => {
  buffer = Buffer.concat([buffer, chunk]);
  for (;;) {
    const end = buffer.indexOf('\\r\\n\\r\\n');
    if (end < 0) return;
    const length = Number(/content-length: (\\d+)/i.exec(buffer.toString('ascii', 0, end))[1]);
    if (buffer.length < end + 4 + length) return;
    const message = JSON.parse(buffer.toString('utf8', end + 4, end + 4 + length));
    buffer = buffer.subarray(end + 4 + length);
    if (message.method === 'exit') process.exit(0);
    if (message.method === 'initialized' && guard) {
      send({ method: 'window/showMessage', params: { type: 2, message: guard } });
    }
    if (message.id !== undefined) {
      const capabilities = Object.fromEntries(providers.map((provider) => [provider, true]));
      send({ id: message.id, result: message.method === 'initialize' ? { capabilities } : null });
    }
  }
});
"""


@dataclass(frozen=True)
class Tree:
    """A repository holding the declaration, and an extension unpacked outside it."""

    root: Path
    extension: Path


def _tree(tmp_path: Path, *, providers: tuple[str, ...] = ALL_PROVIDERS, guard: str = "") -> Tree:
    root = tmp_path / "repository"
    root.mkdir()
    declaration = (repository_root() / DECLARATION).read_bytes()
    (root / DECLARATION).write_bytes(declaration)

    extension = tmp_path / "unpacked" / "extension"
    (extension / "client" / "dist").mkdir(parents=True)
    (extension / MANIFEST).write_text(json.dumps({"main": f"./{CLIENT_ENTRY}"}), encoding="utf-8")
    (extension / CLIENT_ENTRY).write_text("", encoding="utf-8")
    (extension / CLIENT_SCRIPT).write_text("", encoding="utf-8")
    (extension / CLIENT_SCRIPT).chmod(0o755)
    (extension / DECLARATION).write_bytes(declaration)
    (extension / BUNDLE).parent.mkdir(parents=True)
    (extension / BUNDLE).write_text(
        _STAND_IN.replace("PROVIDERS", json.dumps(list(providers))).replace(
            "GUARD", json.dumps(guard)
        ),
        encoding="utf-8",
    )
    return Tree(root, extension)


def _failures(tree: Tree) -> list[str]:
    return check_extension(tree.root, tree.extension).failures


@needs_node
def test_a_server_advertising_every_declared_answer_passes(tmp_path: Path) -> None:
    assert _failures(_tree(tmp_path)) == []


@needs_node
def test_a_vsix_without_the_language_service_fails_and_says_why(tmp_path: Path) -> None:
    failures = _failures(_tree(tmp_path, providers=(), guard=GUARD_MESSAGE))
    assert len(failures) == 1
    assert all(request in failures[0] for request in MODEL_PROVIDERS)
    assert GUARD_MESSAGE in failures[0]


@needs_node
@pytest.mark.parametrize(("request_name", "provider"), sorted(MODEL_PROVIDERS.items()))
def test_each_answer_is_required_on_its_own(
    tmp_path: Path, request_name: str, provider: str
) -> None:
    remaining = tuple(name for name in ALL_PROVIDERS if name != provider)
    failures = _failures(_tree(tmp_path, providers=remaining, guard=GUARD_MESSAGE))
    assert len(failures) == 1
    assert request_name in failures[0]


@needs_node
def test_a_server_that_exits_on_start_fails(tmp_path: Path) -> None:
    tree = _tree(tmp_path)
    (tree.extension / BUNDLE).write_text(
        "console.error('cannot start'); process.exit(1);", encoding="utf-8"
    )
    failures = _failures(tree)
    assert len(failures) == 1
    assert "did not answer initialize" in failures[0]
    assert "cannot start" in failures[0]


@needs_node
def test_an_inherited_node_path_does_not_reach_the_server(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("NODE_PATH", str(tmp_path))
    assert _failures(_tree(tmp_path)) == []


@needs_node
def test_a_server_that_warns_on_start_fails_though_it_advertises_everything(
    tmp_path: Path,
) -> None:
    failures = _failures(_tree(tmp_path, guard=GUARD_MESSAGE))
    assert len(failures) == 1
    assert GUARD_MESSAGE in failures[0]


@pytest.mark.parametrize("missing", [BUNDLE, CLIENT_ENTRY, CLIENT_SCRIPT, DECLARATION, MANIFEST])
def test_a_missing_file_fails_without_starting_anything(tmp_path: Path, missing: str) -> None:
    tree = _tree(tmp_path)
    (tree.extension / missing).unlink()
    failures = _failures(tree)
    assert len(failures) == 1
    assert missing in failures[0]


def test_a_terminate_script_that_is_not_executable_fails(tmp_path: Path) -> None:
    tree = _tree(tmp_path)
    (tree.extension / CLIENT_SCRIPT).chmod(0o644)
    failures = _failures(tree)
    assert len(failures) == 1
    assert "not executable" in failures[0]


def test_the_terminate_script_is_required_beside_the_client_bundle(tmp_path: Path) -> None:
    tree = _tree(tmp_path)
    elsewhere = tree.extension / "elsewhere.js"
    elsewhere.write_text("", encoding="utf-8")
    (tree.extension / MANIFEST).write_text(
        json.dumps({"main": f"./{elsewhere.name}"}), encoding="utf-8"
    )
    failures = _failures(tree)
    assert len(failures) == 1
    assert TERMINATE_SCRIPT in failures[0]
    assert CLIENT_SCRIPT not in failures[0]


def test_the_entry_point_is_read_from_the_packaged_manifest(tmp_path: Path) -> None:
    tree = _tree(tmp_path)
    (tree.extension / MANIFEST).write_text(
        json.dumps({"main": "./elsewhere.js"}), encoding="utf-8"
    )
    failures = _failures(tree)
    assert len(failures) == 1
    assert "elsewhere.js" in failures[0]


def test_a_stale_declaration_fails(tmp_path: Path) -> None:
    tree = _tree(tmp_path)
    (tree.extension / DECLARATION).write_text("{}", encoding="utf-8")
    failures = _failures(tree)
    assert len(failures) == 1
    assert "stale" in failures[0]


def test_an_extension_inside_the_repository_is_refused(tmp_path: Path) -> None:
    tree = _tree(tmp_path)
    inside = tree.root / "unpacked" / "extension"
    shutil.copytree(tree.extension, inside)
    assert any("outside this repository" in f for f in check_extension(tree.root, inside).failures)


def test_a_node_modules_above_the_extension_is_refused(tmp_path: Path) -> None:
    tree = _tree(tmp_path)
    (tree.extension.parent / "node_modules").mkdir()
    assert any("node_modules" in failure for failure in _failures(tree))


def test_a_directory_that_does_not_exist_is_refused(tmp_path: Path) -> None:
    tree = _tree(tmp_path)
    assert check_extension(tree.root, tree.extension / "absent").failures


def _advertisement_failures(declared: set[str], providers: tuple[str, ...]) -> list[str]:
    report = Report("test")
    check_advertisement(
        frozenset(declared), dict.fromkeys(providers, True), report, "extension", None
    )
    return report.failures


def test_an_empty_options_object_counts_as_advertised() -> None:
    report = Report("test")
    declared = frozenset(MODEL_PROVIDERS) - {"textDocument/hover"}
    advertised = {provider: {} for provider in ALL_PROVIDERS}
    check_advertisement(declared, advertised, report, "extension", None)
    assert len(report.failures) == 1
    assert "advertises textDocument/hover" in report.failures[0]


def test_a_server_advertising_beyond_the_declaration_fails() -> None:
    declared = set(MODEL_PROVIDERS) - {"textDocument/hover"}
    failures = _advertisement_failures(declared, ALL_PROVIDERS)
    assert len(failures) == 1
    assert "textDocument/hover" in failures[0]


def test_a_declared_request_with_no_provider_entry_fails() -> None:
    failures = _advertisement_failures({*MODEL_PROVIDERS, "textDocument/rename"}, ALL_PROVIDERS)
    assert len(failures) == 1
    assert "textDocument/rename" in failures[0]


def test_a_declaration_marking_no_answer_present_fails() -> None:
    assert _advertisement_failures({"idfkit-lsp/versions"}, ())
