"""The declaration check, exercised against fixture trees rather than against this repository.

Each fixture is a whole small repository: a declaration, the manifest that routes documents to it,
the readme that renders it, and a server module that registers handlers. The failures this check
exists to catch are all disagreements between two files, and a disagreement needs both files to
exist before it can be written down.

Two tests do read this repository, and only two. The check reads the source server's handlers with
``ast`` rather than by importing it, so that reading is held against what pygls actually holds once
the module is imported. That is the fact the static scan stands in for, and it is the fact that
would go quietly wrong if the module ever named a request in a shape the scan does not recognise.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from .._common import repository_root
from ..check_declaration import check_declaration, fix_readme, read_registrations

if TYPE_CHECKING:
    from pathlib import Path

# Every method pygls handles for reasons of its own, on either side of the comparison. Wider than
# the check's own list, because pygls answers notebook synchronisation too and this repository does
# not declare a position on any of it.
_NOT_A_CAPABILITY = frozenset(
    {
        "$/setTrace",
        "exit",
        "initialize",
        "initialized",
        "notebookDocument/didChange",
        "notebookDocument/didClose",
        "notebookDocument/didOpen",
        "shutdown",
        "textDocument/didChange",
        "textDocument/didClose",
        "textDocument/didOpen",
        "window/workDoneProgress/cancel",
        "workspace/didChangeWorkspaceFolders",
    }
)

_SOURCE_CAPABILITIES: list[dict[str, Any]] = [
    {"request": "textDocument/completion", "state": "present"},
    {"request": "workspace/executeCommand", "state": "present", "editor_specific": True},
    {"request": "idfkit-lsp/versions", "state": "present"},
]

_MODEL_CAPABILITIES: list[dict[str, Any]] = [
    {
        "request": "textDocument/hover",
        "state": "absent_temporary",
        "tracked": "the language service, which is not published",
    }
]


def _write(root: Path, rel_path: str, text: str) -> None:
    path = root / rel_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _capabilities(
    root: Path, *, source: list[dict[str, Any]], model: list[dict[str, Any]]
) -> None:
    declaration = {
        "version": 1,
        "servers": [
            {
                "id": "source",
                "runtime": "the first language, over stdio",
                "documents": [{"language_id": "python", "extensions": [".py"]}],
                "capabilities": source,
            },
            {
                "id": "model",
                "runtime": "the second language, over stdio",
                "documents": [{"language_id": "idf", "extensions": [".idf"]}],
                "capabilities": model,
            },
        ],
    }
    _write(root, "capabilities.json", json.dumps(declaration))


def _manifest(root: Path, *, languages: list[dict[str, Any]], activation: list[str]) -> None:
    _write(
        root,
        "package.json",
        json.dumps(
            {
                "name": "idfkit-lsp",
                "activationEvents": activation,
                "contributes": {"languages": languages},
            }
        ),
    )


def _server_module(root: Path, *, handled: list[str], pygls_command: str | None = None) -> None:
    """A stand-in source server, supplying handlers the way the real one does.

    Handlers are supplied through the ``_handles`` gate and advertised from the declaration.
    Completion is written as a protocol constant and the rest as literals, because the real module
    uses both shapes and the scan has to read either. One lifecycle handler goes straight to pygls,
    because that is where lifecycle handlers really go.
    """
    lines = [
        "from lsprotocol import types",
        "from pygls.lsp.server import LanguageServer",
        "",
        'server = LanguageServer("fixture", "v0")',
        "",
        "",
        "def _handles(request, *, options=None, command=None):",
        "    return lambda function: function",
        "",
        "",
        "@server.feature(types.TEXT_DOCUMENT_DID_OPEN)",
        "def on_did_open(params):",
        "    return None",
        "",
    ]
    for index, request in enumerate(handled):
        named = (
            "types.TEXT_DOCUMENT_COMPLETION"
            if request == "textDocument/completion"
            else f'"{request}"'
        )
        lines += [
            f"@_handles({named})",
            f"def handler_{index}(params):",
            "    return None",
            "",
        ]
    if pygls_command is not None:
        lines += [
            f'@server.command("{pygls_command}")',
            "def on_command(args):",
            "    return None",
            "",
        ]
    _write(root, "server/src/idfkit_lsp/server.py", "\n".join(lines))


def _readme(root: Path, body: str) -> None:
    _write(root, "README.md", f"# fixture\n\n{body}\n")


def _agreeing_tree(root: Path) -> None:
    """A tree in which every restatement says what the declaration says.

    The readme is generated by the check's own ``--fix`` path rather than pasted here, so a test
    that changes the declaration does not also have to hand-render the block it produces.
    """
    _capabilities(root, source=_SOURCE_CAPABILITIES, model=_MODEL_CAPABILITIES)
    _manifest(
        root,
        languages=[{"id": "idf", "extensions": [".idf"]}],
        activation=["onLanguage:python", "onLanguage:idf"],
    )
    _server_module(
        root,
        handled=[
            "textDocument/completion",
            "workspace/executeCommand",
            "idfkit-lsp/versions",
        ],
    )
    _readme(root, "<!-- capabilities:begin -->\n<!-- capabilities:end -->")
    fix_readme(root)


def _failures(root: Path) -> str:
    report = check_declaration(root)
    assert not report.ok, "expected the check to fail"
    return "\n".join(report.failures)


class TestAgreement:
    def test_a_tree_that_agrees_passes(self, tmp_path: Path) -> None:
        _agreeing_tree(tmp_path)
        report = check_declaration(tmp_path)
        assert report.ok, report.failures


class TestManifest:
    def test_a_contributed_language_the_declaration_does_not_carry_fails(
        self, tmp_path: Path
    ) -> None:
        _agreeing_tree(tmp_path)
        _manifest(
            tmp_path,
            languages=[
                {"id": "idf", "extensions": [".idf"]},
                {"id": "epjson", "extensions": [".epjson"]},
            ],
            activation=["onLanguage:python", "onLanguage:idf", "onLanguage:epjson"],
        )

        failures = _failures(tmp_path)
        assert "package.json" in failures
        assert "'epjson'" in failures
        assert "capabilities.json does not carry" in failures

    def test_a_contributed_extension_the_declaration_does_not_carry_fails(
        self, tmp_path: Path
    ) -> None:
        _agreeing_tree(tmp_path)
        _manifest(
            tmp_path,
            languages=[{"id": "idf", "extensions": [".idf", ".imf"]}],
            activation=["onLanguage:python", "onLanguage:idf"],
        )

        failures = _failures(tmp_path)
        assert "package.json" in failures
        assert ".imf" in failures

    def test_a_declared_document_kind_the_manifest_never_reaches_fails(
        self, tmp_path: Path
    ) -> None:
        _agreeing_tree(tmp_path)
        _manifest(tmp_path, languages=[{"id": "idf", "extensions": [".idf"]}], activation=[])

        failures = _failures(tmp_path)
        assert "package.json" in failures
        assert "'python'" in failures
        assert "source server" in failures


class TestSourceServerRegistrations:
    def test_a_present_request_no_handler_registers_fails(self, tmp_path: Path) -> None:
        _agreeing_tree(tmp_path)
        _server_module(tmp_path, handled=["textDocument/completion", "workspace/executeCommand"])

        failures = _failures(tmp_path)
        assert "server/src/idfkit_lsp/server.py" in failures
        assert "'idfkit-lsp/versions'" in failures
        assert "supplies a handler for it" in failures

    def test_a_registered_handler_the_declaration_omits_fails(self, tmp_path: Path) -> None:
        _agreeing_tree(tmp_path)
        _server_module(
            tmp_path,
            handled=[
                "textDocument/completion",
                "workspace/executeCommand",
                "idfkit-lsp/versions",
                "textDocument/definition",
            ],
        )

        failures = _failures(tmp_path)
        assert "server/src/idfkit_lsp/server.py" in failures
        assert "'textDocument/definition'" in failures
        assert "does not carry" in failures

    def test_a_present_request_with_no_handler_at_all_fails(self, tmp_path: Path) -> None:
        _agreeing_tree(tmp_path)
        _server_module(tmp_path, handled=["textDocument/completion", "idfkit-lsp/versions"])

        assert "'workspace/executeCommand'" in _failures(tmp_path)

    def test_a_pygls_command_answers_execute_command(self, tmp_path: Path) -> None:
        _agreeing_tree(tmp_path)
        _server_module(
            tmp_path,
            handled=["textDocument/completion", "idfkit-lsp/versions"],
            pygls_command="idfkit.openDocumentation",
        )

        assert check_declaration(tmp_path).ok


class TestReadme:
    def test_a_block_that_no_longer_matches_fails(self, tmp_path: Path) -> None:
        _agreeing_tree(tmp_path)
        readme = tmp_path / "README.md"
        readme.write_text(
            readme.read_text(encoding="utf-8").replace("present", "absent"), encoding="utf-8"
        )

        failures = _failures(tmp_path)
        assert "README.md" in failures
        assert "--fix" in failures

    def test_a_readme_with_no_block_fails_and_fix_appends_one(self, tmp_path: Path) -> None:
        _agreeing_tree(tmp_path)
        _readme(tmp_path, "no generated block here")

        assert "carries no generated block" in _failures(tmp_path)
        assert fix_readme(tmp_path) == 0
        assert check_declaration(tmp_path).ok

    def test_the_block_states_each_state_and_what_closes_an_absence(self, tmp_path: Path) -> None:
        _agreeing_tree(tmp_path)
        block = (tmp_path / "README.md").read_text(encoding="utf-8")

        assert "`textDocument/completion` | present |" in block
        assert "present, editor-specific" in block
        assert "absent, temporary" in block
        assert "Tracked: the language service, which is not published" in block


class TestBrokenDeclaration:
    def test_a_declaration_breaking_its_own_rules_is_a_failure_not_a_traceback(
        self, tmp_path: Path
    ) -> None:
        _capabilities(
            tmp_path,
            source=[{"request": "textDocument/hover", "state": "absent_temporary"}],
            model=_MODEL_CAPABILITIES,
        )
        _manifest(
            tmp_path,
            languages=[{"id": "idf", "extensions": [".idf"]}],
            activation=["onLanguage:python", "onLanguage:idf"],
        )
        _server_module(tmp_path, handled=[])
        _readme(tmp_path, "<!-- capabilities:begin -->\n<!-- capabilities:end -->")

        failures = _failures(tmp_path)
        assert "capabilities.json" in failures
        assert "absent_temporary names the tracked item" in failures


class TestStaticScanAgreesWithPygls:
    """Why the static scan can be trusted: it covers what the running server actually holds.

    The source server advertises from the declaration, so pygls ends up holding what the
    declaration marks present. The scan reads what the module supplies, which is that set and
    possibly more. What it must never do is read less: a request pygls holds and the scan misses
    would pass the backward direction of the check while reaching editors unaccounted for.
    """

    def test_the_scan_misses_nothing_pygls_holds(self) -> None:
        root = repository_root()
        scanned = read_registrations(root / "server/src/idfkit_lsp/server.py")
        assert not scanned.problems, scanned.problems

        from idfkit_lsp import server as module

        manager = module.server.protocol.fm
        registered = set(manager.features)
        if manager.commands:
            registered.add("workspace/executeCommand")

        assert registered - _NOT_A_CAPABILITY <= scanned.methods

    def test_the_scan_covers_every_request_the_declaration_advertises(self) -> None:
        from idfkit_lsp.capabilities import load

        root = repository_root()
        scanned = read_registrations(root / "server/src/idfkit_lsp/server.py")

        assert load(root / "capabilities.json").source.present_requests <= scanned.methods
