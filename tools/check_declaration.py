"""Check ``capabilities.json`` against everything that repeats what it says.

The declaration is the one record of what each server serves and what it does not. Three other
files restate it for a different audience: the extension manifest tells the editor which documents
to route, the readme tells a reader, and the source server registers the handlers. A restatement
that has drifted is worse than no restatement, because an editor told an answer exists when nobody
can give it waits for something that never arrives. This check makes each of those three agree with
the declaration, in both directions, before review rather than at review.

The model server's registrations are deliberately not read here. Reading TypeScript from Python
would mean a second parser for a second language, and the protocol suite already drives that server
over the wire, which is the only reading that cannot be fooled.

How the source server's registrations are read: by walking the module's decorators with ``ast``,
not by importing it. Importing would report what pygls registered on the *installed* distribution,
and a process holds exactly one ``idfkit_lsp``, so an import could never inspect the tree this check
was pointed at. A check that cannot be aimed at a fixture tree is a check whose own failure paths
are untested. The scan is held to the imported truth instead by a test, which asserts that what it
reads from this repository's own ``server.py`` covers what pygls ends up holding.

The source server advertises from the declaration rather than beside each handler, so a handler it
supplies for an undeclared request is simply never advertised and nothing at runtime objects. That
is the direction this check exists for: a handler written and then silently unreachable is the
same silence as a capability promised and never given.

The declaration also states the model server's Node floor, which three more records repeat or
constrain: the package's ``engines.node``, the bundle's ``--target``, and the ``engines.node`` of
every package it installs, read from the lockfile so that no install is needed. A dependency bump
that raises its own floor changes nothing in this repository's text, so it is the one disagreement
no reviewer would be shown. Which Node an editor release ships cannot be read from any of these, so
``engines.vscode`` is not compared here.
"""

from __future__ import annotations

import argparse
import ast
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from lsprotocol import types as lsp_types

from idfkit_lsp.capabilities import (
    Capability,
    CapabilityDeclaration,
    CapabilityState,
    DeclarationError,
    DocumentKind,
    ServerDeclaration,
    load,
)

from ._common import Report, read_json, repository_root, validate_against_schema

SCHEMA_PATH = Path(__file__).resolve().parent / "schemas" / "capabilities.schema.json"

CAPABILITIES = "capabilities.json"
MANIFEST = "package.json"
README = "README.md"
SOURCE_SERVER_MODULE = "server/src/idfkit_lsp/server.py"
MODEL_SERVER_MANIFEST = "model-server/package.json"
MODEL_SERVER_LOCK = "model-server/package-lock.json"

_DECLARED_NODE_FLOOR = re.compile(r"\bNode (\d+) or newer\b")
_BUNDLE_TARGET = re.compile(r"--target=node(\d+)\b")
_RANGE_MAJOR = re.compile(r"^\s*(?:>=|\^|~)?\s*v?(\d+)")

BLOCK_BEGIN = "<!-- capabilities:begin -->"
BLOCK_END = "<!-- capabilities:end -->"

_FIX_HINT = (
    "run `uv run --project server python -m tools.check_declaration --fix` to regenerate it"
)

_EXECUTE_COMMAND = "workspace/executeCommand"

# pygls' own registrars, reached as attributes of the server object. ``command`` registers a
# command the server dispatches from workspace/executeCommand, so it answers that request and no
# other.
_PYGLS_REGISTRARS = frozenset({"feature", "command"})

# The source server's own gate: it supplies a handler for a request and leaves advertising to the
# declaration. A handler named here counts as registered, because whether it reaches the editor is
# exactly what this check is comparing against.
_GATE = "_handles"

# Lifecycle and document-synchronisation methods. Every server that speaks the protocol handles
# them, so handling one says nothing about what a server serves and the declaration does not carry
# them. Anything else a server registers is a capability and must be declared.
_NOT_A_CAPABILITY = frozenset(
    {
        "$/setTrace",
        "exit",
        "initialize",
        "initialized",
        "shutdown",
        "textDocument/didChange",
        "textDocument/didClose",
        "textDocument/didOpen",
        "textDocument/didSave",
        "textDocument/willSave",
        "workspace/didChangeConfiguration",
        "workspace/didChangeWatchedFiles",
        "workspace/didChangeWorkspaceFolders",
    }
)

# How a server is named in the readme. The declaration constrains the ids to these two, and a
# reader meets the servers by what they serve rather than by an identifier.
_SERVER_TITLES = {"source": "The source server", "model": "The model server"}

_STATE_WORDS = {
    CapabilityState.PRESENT: "present",
    CapabilityState.ABSENT_PERMANENT: "absent, permanent",
    CapabilityState.ABSENT_TEMPORARY: "absent, temporary",
}


@dataclass(frozen=True)
class Registrations:
    """What one server module registers, read statically.

    ``problems`` holds every decorator whose method name could not be read. They are reported
    rather than dropped: a scan that silently skips what it cannot understand is a scan that
    reports a server registers less than it does, which is the direction that passes wrongly.
    """

    methods: frozenset[str]
    problems: tuple[str, ...]


@dataclass(frozen=True)
class Contribution:
    """One ``contributes.languages`` entry of the extension manifest."""

    language_id: str
    extensions: frozenset[str]


def render_block(declaration: CapabilityDeclaration) -> str:
    """Render the readme's generated block, delimiters included, from the declaration."""
    sections = [_render_server(server) for server in declaration.servers]
    return f"{BLOCK_BEGIN}\n\n" + "\n\n".join(sections) + f"\n\n{BLOCK_END}"


def _render_server(server: ServerDeclaration) -> str:
    title = _SERVER_TITLES.get(server.id, f"The {server.id} server")
    served = ", ".join(_render_document(document) for document in server.documents)
    rows = "\n".join(_render_capability_row(item) for item in server.capabilities)
    return (
        f"### {title}\n\n"
        f"Runtime: {server.runtime}. Serves {served}.\n\n"
        f"| Request | State | Note |\n| --- | --- | --- |\n{rows}"
    )


def _render_document(document: DocumentKind) -> str:
    extensions = ", ".join(f"`{extension}`" for extension in document.extensions)
    return f"`{document.language_id}` ({extensions})"


def _render_capability_row(capability: Capability) -> str:
    state = _STATE_WORDS[capability.state]
    if capability.editor_specific:
        state = f"{state}, editor-specific"
    if capability.state is CapabilityState.ABSENT_PERMANENT:
        note = f"{capability.reason} Instead: {capability.instead}"
    elif capability.state is CapabilityState.ABSENT_TEMPORARY:
        note = f"Tracked: {capability.tracked}"
    else:
        note = ""
    return f"| `{capability.request}` | {state} | {_cell(note)} |"


def _cell(text: str) -> str:
    """One table cell: no newlines, and no bare pipe to end the row early."""
    return " ".join(text.split()).replace("|", r"\|") or " "


def _block_span(text: str) -> tuple[int, int] | None:
    """Where the generated block sits in the readme, delimiters included."""
    begin = text.find(BLOCK_BEGIN)
    end = text.find(BLOCK_END)
    if begin == -1 or end == -1 or end < begin:
        return None
    return begin, end + len(BLOCK_END)


def _check_manifest(root: Path, declaration: CapabilityDeclaration, report: Report) -> None:
    """The editor routes on the manifest, so the manifest and the declaration must name one set.

    Forward: a language id or extension the manifest advertises must be declared, or the editor
    sends documents to a server that has said nothing about them. Backward: a document kind
    declared for a server the extension launches must reach the editor, or the declaration promises
    an answer no user can ask for.
    """
    path = root / MANIFEST
    if not path.is_file():
        report.fail(MANIFEST, "the extension manifest is missing")
        return
    manifest = read_json(path)
    if not isinstance(manifest, dict):
        report.fail(MANIFEST, "is not a JSON object")
        return

    contributed = _contributions(manifest, report)
    activated = _activation_languages(manifest)
    declared = {
        document.language_id: (server, document)
        for server in declaration.servers
        for document in server.documents
    }

    for language_id, contribution in sorted(contributed.items()):
        found = declared.get(language_id)
        if found is None:
            report.fail(
                MANIFEST,
                f"contributes language id {language_id!r}, which {CAPABILITIES} does not carry "
                f"for either server",
            )
            continue
        unknown = sorted(contribution.extensions - set(found[1].extensions))
        if unknown:
            report.fail(
                MANIFEST,
                f"maps {', '.join(unknown)} to language id {language_id!r}, which {CAPABILITIES} "
                f"does not carry for it",
            )

    for language_id in sorted(activated - set(declared)):
        report.fail(
            MANIFEST,
            f"activates on language id {language_id!r}, which {CAPABILITIES} does not carry for "
            f"either server",
        )

    # The extension launches both servers: it bundles the model server and starts the source
    # server on the configured interpreter. So every declared document kind must reach the editor.
    for server in declaration.servers:
        for document in server.documents:
            contribution = contributed.get(document.language_id)
            if contribution is None:
                # A language the editor itself contributes is reached by activating on it, which
                # is how the first language arrives without this extension redefining it.
                if document.language_id not in activated:
                    report.fail(
                        MANIFEST,
                        f"neither contributes language id {document.language_id!r} nor activates "
                        f"on it, though {CAPABILITIES} declares it for the {server.id} server",
                    )
                continue
            missing = sorted(set(document.extensions) - contribution.extensions)
            if missing:
                report.fail(
                    MANIFEST,
                    f"contributes language id {document.language_id!r} without "
                    f"{', '.join(missing)}, which {CAPABILITIES} declares for the "
                    f"{server.id} server",
                )


def _contributions(manifest: dict[str, Any], report: Report) -> dict[str, Contribution]:
    contributes = manifest.get("contributes")
    entries = contributes.get("languages") if isinstance(contributes, dict) else None
    if not isinstance(entries, list):
        return {}
    contributions: dict[str, Contribution] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            report.fail(MANIFEST, "contributes a language entry that is not a JSON object")
            continue
        language_id = entry.get("id")
        if not isinstance(language_id, str) or not language_id:
            report.fail(MANIFEST, "contributes a language entry with no id")
            continue
        raw = entry.get("extensions")
        extensions = raw if isinstance(raw, list) else []
        contributions[language_id] = Contribution(
            language_id=language_id,
            extensions=frozenset(item for item in extensions if isinstance(item, str)),
        )
    return contributions


def _activation_languages(manifest: dict[str, Any]) -> set[str]:
    events = manifest.get("activationEvents")
    if not isinstance(events, list):
        return set()
    prefix = "onLanguage:"
    return {
        event[len(prefix) :]
        for event in events
        if isinstance(event, str) and event.startswith(prefix) and len(event) > len(prefix)
    }


def read_registrations(path: Path) -> Registrations:
    """Read every request a server module supplies a handler for, from its decorators."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    constants = _module_constants(tree)
    methods: set[str] = set()
    problems: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        for decorator in node.decorator_list:
            if not isinstance(decorator, ast.Call):
                continue
            registrar = decorator.func
            if isinstance(registrar, ast.Attribute):
                if registrar.attr not in _PYGLS_REGISTRARS:
                    continue
                if registrar.attr == "command":
                    methods.add(_EXECUTE_COMMAND)
                    continue
            elif not (isinstance(registrar, ast.Name) and registrar.id == _GATE):
                continue
            if not decorator.args:
                problems.append(
                    f"registers a handler at line {decorator.lineno} with no request name"
                )
                continue
            method = _method_name(decorator.args[0], constants)
            if method is None:
                problems.append(
                    f"registers a handler at line {decorator.lineno} whose request name cannot "
                    f"be read without running the module"
                )
                continue
            methods.add(method)
    return Registrations(methods=frozenset(methods), problems=tuple(problems))


def _module_constants(tree: ast.Module) -> dict[str, str]:
    """Module-level string constants, so a request named through one still reads as itself.

    A custom request has no protocol constant to name it, so a server binds it once at module level
    and uses that name. Following the binding is the difference between reading the request and
    reporting that it could not be read.
    """
    constants: dict[str, str] = {}
    for node in tree.body:
        if isinstance(node, ast.Assign):
            targets = node.targets
            value = node.value
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            targets = [node.target]
            value = node.value
        else:
            continue
        if not isinstance(value, ast.Constant) or not isinstance(value.value, str):
            continue
        for target in targets:
            if isinstance(target, ast.Name):
                constants[target.id] = value.value
    return constants


def _method_name(node: ast.expr, constants: dict[str, str]) -> str | None:
    """The protocol method a registration decorator names.

    Three shapes, and no fourth: a literal, a protocol constant from ``lsprotocol``, or a string
    the module itself bound at its top level.
    """
    if isinstance(node, ast.Constant):
        return node.value if isinstance(node.value, str) else None
    if isinstance(node, ast.Attribute):
        name = node.attr
    elif isinstance(node, ast.Name):
        if node.id in constants:
            return constants[node.id]
        name = node.id
    else:
        return None
    value = getattr(lsp_types, name, None)
    return value if isinstance(value, str) else None


def _check_source_server(root: Path, server: ServerDeclaration, report: Report) -> None:
    """Both directions between the declaration and the handlers the source server registers."""
    path = root / SOURCE_SERVER_MODULE
    if not path.is_file():
        report.fail(
            SOURCE_SERVER_MODULE,
            "is missing, so what the source server registers cannot be read",
        )
        return
    registrations = read_registrations(path)
    for problem in registrations.problems:
        report.fail(SOURCE_SERVER_MODULE, problem)

    for request in sorted(server.present_requests):
        if request not in registrations.methods:
            report.fail(
                SOURCE_SERVER_MODULE,
                f"{CAPABILITIES} marks {request!r} present on the source server, but nothing "
                f"here supplies a handler for it",
            )

    for method in sorted(registrations.methods - _NOT_A_CAPABILITY):
        capability = server.capability(method)
        if capability is None:
            report.fail(
                SOURCE_SERVER_MODULE,
                f"supplies a handler for {method!r}, which {CAPABILITIES} does not carry for "
                f"the source server",
            )
        elif not capability.is_present:
            report.fail(
                SOURCE_SERVER_MODULE,
                f"supplies a handler for {method!r}, which {CAPABILITIES} declares "
                f"{capability.state.value} on the source server, so it never reaches an editor",
            )


def _lowest_major(node_range: str) -> int | None:
    """The lowest major version an ``engines.node`` range admits, or None if it names none."""
    majors = [_RANGE_MAJOR.match(part) for part in node_range.split("||")]
    found = [int(major.group(1)) for major in majors if major is not None]
    return min(found) if found else None


def _engines_node(package: Any) -> str | None:
    engines = package.get("engines") if isinstance(package, dict) else None
    node = engines.get("node") if isinstance(engines, dict) else None
    return node if isinstance(node, str) else None


def _check_node_floor(root: Path, server: ServerDeclaration, report: Report) -> None:
    """The Node floor the declaration states is the one the model server is packaged and bundled
    for, and no package it installs at runtime asks for more."""
    stated = _DECLARED_NODE_FLOOR.search(server.runtime)
    if stated is None:
        report.fail(CAPABILITIES, "the model server's runtime states no 'Node N or newer' floor")
        return
    floor = int(stated.group(1))

    manifest_path = root / MODEL_SERVER_MANIFEST
    if not manifest_path.is_file():
        report.fail(MODEL_SERVER_MANIFEST, "is missing, so the Node floor cannot be compared")
        return
    manifest = read_json(manifest_path)

    node_range = _engines_node(manifest)
    if node_range is None or _lowest_major(node_range) != floor:
        report.fail(
            MODEL_SERVER_MANIFEST,
            f"engines.node is {node_range!r}, but {CAPABILITIES} states Node {floor} or newer",
        )

    scripts = manifest.get("scripts") if isinstance(manifest, dict) else None
    build = scripts.get("build") if isinstance(scripts, dict) else None
    target = _BUNDLE_TARGET.search(build) if isinstance(build, str) else None
    if target is None or int(target.group(1)) != floor:
        report.fail(
            MODEL_SERVER_MANIFEST,
            f"the build script does not bundle for --target=node{floor}, the floor "
            f"{CAPABILITIES} states",
        )

    lock_path = root / MODEL_SERVER_LOCK
    if not lock_path.is_file():
        report.fail(MODEL_SERVER_LOCK, "is missing, so the installed floors cannot be compared")
        return
    lock = read_json(lock_path)
    packages = lock.get("packages") if isinstance(lock, dict) else None
    for name, package in sorted(packages.items() if isinstance(packages, dict) else []):
        # The empty key is the model server itself, compared above. A dev dependency never reaches
        # a user, so its floor is the toolchain's business.
        if not name or (isinstance(package, dict) and package.get("dev")):
            continue
        required = _engines_node(package)
        lowest = _lowest_major(required) if required is not None else None
        if lowest is not None and lowest > floor:
            report.fail(
                MODEL_SERVER_LOCK,
                f"{name} requires Node {required}, above the Node {floor} {CAPABILITIES} states",
            )


def _check_readme(root: Path, declaration: CapabilityDeclaration, report: Report) -> None:
    """The readme states what is served and what is not by rendering the declaration, not by
    restating it, so the two cannot drift apart in prose."""
    path = root / README
    if not path.is_file():
        report.fail(README, "is missing, and it is where the declaration is stated to a reader")
        return
    text = path.read_text(encoding="utf-8")
    span = _block_span(text)
    if span is None:
        report.fail(
            README,
            f"carries no generated block delimited by {BLOCK_BEGIN} and {BLOCK_END}: {_FIX_HINT}",
        )
        return
    if text[span[0] : span[1]] != render_block(declaration):
        report.fail(
            README,
            f"its generated block no longer says what {CAPABILITIES} says: {_FIX_HINT}",
        )


def _declaration(root: Path, report: Report) -> CapabilityDeclaration | None:
    """Validate the record and read it through the loader both servers read it with."""
    source = root / CAPABILITIES
    validate_against_schema(read_json(source), SCHEMA_PATH, report, source)
    try:
        # The loader owns the state rules and the disjointness of document kinds across servers.
        # They are applied here by loading, not by being written a second time.
        return load(source)
    except DeclarationError as exc:
        report.fail(CAPABILITIES, str(exc).removeprefix(f"{source.resolve()}: "))
        return None


def check_declaration(root: Path) -> Report:
    """Run every declaration rule against one repository tree and return what it found."""
    report = Report("check_declaration")
    declaration = _declaration(root, report)
    if declaration is None:
        return report
    _check_manifest(root, declaration, report)
    _check_source_server(root, declaration.source, report)
    _check_node_floor(root, declaration.model, report)
    _check_readme(root, declaration, report)
    return report


def fix_readme(root: Path) -> int:
    """Rewrite the readme's generated block from the declaration, appending it when absent."""
    report = Report("check_declaration")
    declaration = _declaration(root, report)
    if declaration is None:
        return report.finish()

    path = root / README
    if not path.is_file():
        report.fail(README, "is missing, and this check does not write a readme from nothing")
        return report.finish()

    text = path.read_text(encoding="utf-8")
    block = render_block(declaration)
    span = _block_span(text)
    if span is None:
        updated = f"{text.rstrip()}\n\n{block}\n"
    else:
        updated = text[: span[0]] + block + text[span[1] :]
    if updated == text:
        print(f"{report.check}: {README} already says what {CAPABILITIES} says")
        return 0
    path.write_text(updated, encoding="utf-8")
    print(f"{report.check}: regenerated the capabilities block in {README}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="check_declaration",
        description="Check capabilities.json against the manifest, the readme, and the servers.",
    )
    parser.add_argument(
        "--fix",
        action="store_true",
        help="rewrite the readme's generated block from capabilities.json",
    )
    args = parser.parse_args(argv)
    root = repository_root()
    if args.fix:
        return fix_readme(root)
    return check_declaration(root).finish()


if __name__ == "__main__":
    raise SystemExit(main())
