# Implementation Plan: Two Servers, One Client, One Capability Story

**Branch**: `001-two-server-editor-support` | **Date**: 2026-09-04 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/001-two-server-editor-support/spec.md`

## Summary

Make this repository what its constitution says it is: a translator with two servers, one thin
client, one declared capability story, and no knowledge of its own.

Four things are built. A **capability declaration** at the root records what each server serves and
every absence with its kind and reason, and becomes the thing the test suite asserts against in both
directions. A **level declaration** records every library this repository resolves and why it is
where it is, checked locally and pointed at by the consumer register. A **model server**, written in
the second language and bundled in the extension, serves model text by wrapping the language service
feature 005 delivers, translating positions and nothing else. A **single protocol suite** drives
both servers over stdio with no editor present.

Two things are removed. The source server's tables of library names go, replaced by derivation from
the installed library, which is both a constitutional requirement and a live bug fix: at
`idfkit==1.0.0rc1` those tables already miss a document-producing entry point and already fail on an
annotated document, silently in both cases. And the pin moves from `0.15.0` to `1.0.0rc1`, which is
the gap this feature exists to stop hiding.

## Technical Context

**Language/Version**: Python 3.10 through 3.13 (source server, checks, protocol suite); TypeScript
on the editor's bundled runtime, ESM, Node 18 or newer (model server, client)

**Primary Dependencies**: `idfkit==1.0.0rc1`, `pygls==2.1.1` and `lsprotocol==2025.0.0`, every one pinned exactly per Principle III (source server);
`idfkit` and its language service component at exact pinned versions, with the protocol server
library for the second language (model server); `vscode-languageclient` (client). The language
service component does not exist yet; `contracts/language-service-expected.md` is the surface this
plan is built against.

**Storage**: none. Both servers hold per-document state in memory for the life of a session and
persist nothing.

**Testing**: pytest for unit tests and for the cross-runtime protocol suite; the second language's
own runner for the model server's unit tests. One protocol suite covers both servers.

**Target Platform**: developer machines on macOS, Linux, and Windows, running the targeted editor
(`^1.86.0`) or any editor that speaks the protocol

**Project Type**: language tooling. Two protocol servers plus a thin editor client, in one
repository, in two languages.

**Performance Goals**: an answer at a cursor in model text within one frame at 60 hertz, measured at
the protocol boundary. This repository's own share of that budget is the transport and the position
translation; the answer itself is the language service's budget and is not renegotiated here.

**Constraints**: no schema, grammar, or model-text position knowledge anywhere in this repository
except one named translation module; nothing advertised that the declaration does not carry; no
capability provable only by opening an editor; every resolved library pinned exactly and declared.

**Scale/Scope**: two servers, roughly 1,400 lines of existing Python plus a new second-language
server; five advertised answers for model text; three for source text today.

## Constitution Check

*GATE: evaluated before Phase 0, re-evaluated after Phase 1. Both results recorded.*

| Principle | Gate | Pre-Phase 0 | Post-Phase 1 | Post-implementation |
|---|---|---|---|---|
| I. The extension translates, it never knows | No schema table, grammar pattern, or model-text position arithmetic outside the one declared translation module | FAIL, two tables in the source server | PASS with one tracked exception and one recorded residual, both in Complexity Tracking | PASS. Both tables are deleted and derived. `make check-knowledge` passes with zero suppressions, and rejects each of the three shapes on demand. Three residuals recorded below |
| II. Two servers, one client, one capability story | Each server serves its own document kind; one declaration carries both | FAIL, one server and no declaration | PASS | PASS. `capabilities.json` carries both servers, both advertise from it, and `tests/protocol/test_declaration.py` asserts it in both directions |
| III. Levels are pinned and declared | Every resolved library pinned exactly, declared, and registered | FAIL, pinned and undeclared, and behind | PASS | PASS. Seven libraries, every one pinned exactly and declared. `make check-levels` names both files on a disagreement. The register entry is drafted; submitting it is cross-repository |
| IV. An absent capability is stated, never faked | No locally assembled answers; every absence recorded with a kind | PASS today, at risk once model text arrives | PASS | PASS, and tested. `absence.ts` makes the three outcomes impossible to flatten, and the completion handler's tests assert there is no local fallback list to fall back to |
| V. The client stays thin | Wiring and launch only | PASS, with one editor-specific command to record | PASS | PASS. The client locates, launches, declares and surfaces, and reads its document selectors from the declaration. `test_no_client.py` asserts every present capability is answered with no client loaded |
| VI. Editor-facing behaviour is tested without an editor | Protocol in, protocol out, both servers, in CI | PARTIAL, one server, POSIX-only harness | PASS | PASS. One suite, both servers, no editor, on Linux and Windows in CI. The POSIX-only reader is deleted |

**Pre-Phase 0 verdict**: three failures, all of them the reason this feature exists rather than
objections to it. No gate blocks the work.

**Post-Phase 1 verdict**: passes, with two items carried into Complexity Tracking rather than
waved through. Neither is a licence to add knowledge; both are bounded, named, and tested.

**Post-implementation verdict**: all six pass against the built repository. The three failures this
feature existed to fix are fixed, and the two Complexity Tracking items are both still bounded, both
now recorded in `capabilities.json` under `retained_knowledge` rather than only in this file, and
both covered by tests. One item is added below that was found during the audit rather than predicted
by it.

The one thing that is not finished, and it is external: `@idfkit/language` does not exist, so the
model server's five model-text answers stand at `absent_temporary` with a tracked item rather than at
`present`. That is the declaration being true rather than the feature being incomplete: the handlers
are written and their translations are tested, and `tests/protocol/test_model_server.py` carries the
groups that prove them, skipping with a message that names the missing component. When it ships, the
five entries flip and thirteen skipped tests start running.

## Project Structure

### Documentation (this feature)

```text
specs/001-two-server-editor-support/
├── plan.md              # This file
├── research.md          # Phase 0 output
├── data-model.md        # Phase 1 output
├── quickstart.md        # Phase 1 output
├── contracts/           # Phase 1 output
│   ├── capabilities.schema.json
│   ├── levels.schema.json
│   ├── model-server.md
│   ├── source-server.md
│   ├── language-service-expected.md
│   └── consumer-register-entry.toml   # drafted at implementation, submitted to the register
├── checklists/
│   └── requirements.md
└── tasks.md             # Phase 2 output, not created here
```

### Source Code (repository root)

```text
capabilities.json                     # the one capability declaration (new)
levels.json                           # every library resolved, and why it is where it is (new)

server/                               # source server, first language, exists
├── src/idfkit_lsp/
│   ├── server.py                     # advertises from capabilities.json rather than inline
│   ├── analyzer.py                   # tables removed, generic annotations unwrapped
│   ├── library_surface.py            # NEW: derives factories and type names from idfkit
│   ├── schema_cache.py               # unchanged
│   ├── completion.py, hover.py, signature_help.py, document_state.py, utils.py
│   └── capabilities.py               # NEW: typed loader for capabilities.json
└── tests/                            # unit tests only, protocol tests move out

model-server/                         # model server, second language (new)
├── package.json                      # exact pins; ESM
├── src/
│   ├── main.ts                       # protocol wiring, advertises from capabilities.json
│   ├── service.ts                    # the single import of the language service, with its guard
│   ├── positions.ts                  # the ONLY arithmetic over model text in this repository
│   ├── documents.ts                  # one service handle per open document
│   └── handlers/                     # classify, diagnostics, completion, hover, definition
└── tests/                            # unit tests for translation, in its own runner

client/src/extension.ts               # launches both servers; nothing else added

tests/protocol/                       # ONE suite, both servers, no editor (new)
├── harness.py                        # portable stdio JSON-RPC client
├── conftest.py                       # spawns each server; candidate-build switch
├── test_declaration.py               # declaration and servers agree, both directions
├── test_source_server.py             # moved from server/tests/test_server_integration.py
└── test_model_server.py

tools/
├── check_knowledge.py                # Principle I, before review
└── check_levels.py                   # levels.json against the real pins
```

**Structure Decision**: the existing two-directory split (`server/`, `client/`) becomes a
four-directory one. `model-server/` sits beside `server/` because it is a peer, not a subordinate:
Principle II says neither reimplements the other, and putting one inside the other would invite
exactly that. `tests/protocol/` moves to the root because it now covers two servers and belongs to
neither. `capabilities.json` and `levels.json` sit at the root because each is read from both
languages, and a file that lives inside one server's directory is a file the other server's authors
will not think to update.

## Complexity Tracking

> Three items are recorded here rather than passed silently. All three are bounded and tested. The
> first two were predicted; the third was found by the FR-024 audit that closes this feature.
>
> The audit also found one thing the check cannot do, recorded here rather than left implied: the two
> tables this feature deletes were four and three entries long, below the five-literal threshold
> `tools/check_knowledge.py` uses, so the check would not have caught them. That is the honest limit
> of a shape-based check, and it is why the tables are removed by derivation rather than left for the
> check to police. Lowering the threshold would reject ordinary tuples of protocol method names and
> make the check a nuisance, which is the failure mode research R9 names.

| Violation | Why Needed | Simpler Alternative Rejected Because |
|---|---|---|
| `model-server/src/positions.ts` performs arithmetic over model text, which Principle I forbids | The protocol demands positions in a unit the language service does not speak, and feature 005 requires conversion to be possible without the service knowing a protocol exists. The conversion is therefore on this side by construction | Asking the service for protocol units was rejected by feature 005 itself, which forbids the service naming a protocol's types. Confining the arithmetic to one named module, with the knowledge check treating that module as its single exception, is what keeps the rule enforceable rather than aspirational. It needs no schema and no grammar: it converts between text encodings, not between meanings |
| `server/src/idfkit_lsp/analyzer.py` retains knowledge of the library's own API shape, that a subscript on a document yields a collection and that adding yields an object | No library publishes that as data, and inference over first-language source is the source server's whole job. The drift-prone half, the names of the entry points, is derived rather than written down after this feature | Deriving the shape too would mean implementing a type checker, which is not smaller. Recording it as a known deviation with a tracked item, and covering it with tests that fail when the library renames the members involved, keeps it visible. It is API shape and not schema: no object type and no field name appears in this file, and none may |
| `server/src/idfkit_lsp/completion.py` and `signature_help.py` match patterns against the line under the cursor | Found by the FR-024 audit rather than predicted by it. A line being typed is by definition incomplete, so it does not parse, and the analyzer's AST cannot reach it. Something has to read a partial expression | It is a pattern over first-language source, not over model text, and it carries no schema: every pattern matches identifiers, brackets and quotes, and every object type and field name it yields is read back out of `idfkit`. Moving it into the library would mean asking a model library to parse Python. `tools/check_knowledge.py` scopes its pattern shape to model text for exactly this reason, which research R9 records as a limit rather than an oversight |
