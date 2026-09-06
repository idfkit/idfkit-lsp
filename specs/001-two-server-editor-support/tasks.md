---

description: "Task list for feature 001-two-server-editor-support"
---

# Tasks: Two Servers, One Client, One Capability Story

**Input**: Design documents from `/specs/001-two-server-editor-support/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/

**Tests**: Included, and not optional here. The spec makes testing a user story of its own (US5) and
requires it in FR-033 through FR-037, and the constitution's Principle VI makes an untested
editor-facing behaviour unmergeable.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (US1 through US7)
- Every task names the exact file it touches

## Path Conventions

Paths are repository-relative from `idfkit-lsp/`. Four trees: `server/` (first language, exists),
`model-server/` (second language, new), `client/` (editor client, exists), `tests/protocol/` (one
suite, both servers, new). Two declared records sit at the root: `capabilities.json` and
`levels.json`.

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: make room for the four new trees before anything is written into them.

- [X] T001 [P] Create `model-server/` with `package.json` (`"type": "module"`, ESM, exact pins only, `engines.node >= 18`), `tsconfig.json` (strict, `NodeNext` module resolution), and `.gitignore` for `node_modules/` and `dist/`
- [X] T002 [P] Create `tests/protocol/` and `tools/` as packages, each with an `__init__.py`, and add `tests/protocol` to the pytest search path in `server/pyproject.toml` under `[tool.pytest.ini_options] testpaths`
- [X] T003 [P] Extend the root `Makefile` with empty-but-declared targets `check-declaration`, `check-levels`, `check-knowledge`, `test-protocol`, and `bench-protocol`, and extend `install` to install both runtimes
- [X] T004 [P] Extend `.vscodeignore` so the packaged extension carries `model-server/dist/` and `capabilities.json` and excludes `model-server/src/`, `model-server/node_modules/`, and `tests/`

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: the shared plumbing every check and both servers read. Nothing here answers a user
question; everything here is what the answers are loaded through.

**⚠️ CRITICAL**: No user story work can begin until this phase is complete

- [X] T005 Create `tools/_common.py` with repository-root resolution, a JSON reader that fails loudly on a malformed declared record, and a shared failure reporter that prints the offending file and the rule broken
- [X] T006 [P] Add `tools` and `tests` to the linted and type-checked surface: extend `src = [...]` and the ruff/pyright `include` lists in `server/pyproject.toml`, and extend the `files:` patterns in `.pre-commit-config.yaml` so hooks reach `tools/` and `tests/protocol/`
- [X] T007 [P] Copy `specs/001-two-server-editor-support/contracts/capabilities.schema.json` and `contracts/levels.schema.json` to `tools/schemas/` so the checks validate against a schema that ships with the code rather than one that lives in a spec directory
- [X] T008 Add a `check` aggregate to the root `Makefile` that runs `check-declaration`, `check-levels`, `check-knowledge`, the existing `server/` gate, and `test-protocol`, so that one command is what a change is held to

**Checkpoint**: the trees exist, the checks have a place to live, and every new file is linted.

---

## Phase 3: User Story 1 - The repository says what it serves, and what it does not (Priority: P1) 🎯 MVP

**Goal**: one file answers "what does this extension do, and what does it not do", with every
absence carrying its kind and its reason. It lands applied to the repository exactly as it stands,
before either server changes.

**Independent Test**: read `capabilities.json` with no code changed. It names the source server, the
documents it serves, and every request it answers today. It names the model server, records every
model-text request as not yet answered, and records on the source server that installing with `pip`
alone yields no answers about model text, that this is permanent, and what to install instead. Then
mark one present capability `absent_permanent` and `make check-declaration` fails.

### Tests for User Story 1

- [X] T009 [P] [US1] Write `server/tests/test_capabilities.py` asserting the loader's state rules fail closed: `absent_permanent` without `reason` or without `instead`, `absent_temporary` without `tracked`, `present` carrying any of the three, two servers claiming one language id, and two servers claiming one extension
- [X] T010 [P] [US1] Write `tools/tests/test_check_declaration.py` asserting the check fails when the extension manifest advertises a document kind the declaration does not carry, and when the declaration marks present a request `server.py` does not register

### Implementation for User Story 1

- [X] T011 [US1] Create `capabilities.json` at the repository root: `version`, the `source` server with `textDocument/completion`, `textDocument/hover`, `textDocument/signatureHelp` present and `workspace/executeCommand` present with `editor_specific: true`, every model-text request on it as `absent_permanent` with the reason feature 005 records and `instead` naming the model server, and the `model` server entry with its five requests as `absent_temporary` tracked to user stories 3 and 4
- [X] T012 [US1] Create `server/src/idfkit_lsp/capabilities.py`: frozen dataclasses `CapabilityDeclaration`, `ServerDeclaration`, `DocumentKind`, and `Capability` with a `CapabilityState` enum, a `load()` that reads the root `capabilities.json`, and validation that raises on every state rule in data-model.md rather than returning a dictionary
- [X] T013 [US1] Create `tools/check_declaration.py`: validate `capabilities.json` against `tools/schemas/capabilities.schema.json`, apply the state rules through `capabilities.py`, assert document kinds are disjoint across servers, and cross-read `package.json` and `README.md` for agreement with what the declaration says is served
- [X] T014 [US1] Rewrite the feature registrations in `server/src/idfkit_lsp/server.py` to read from `capabilities.py` rather than an inline list, so a capability the declaration does not carry cannot be advertised
- [X] T015 [P] [US1] Update the `description` in `package.json` and the capability section of `README.md` to state both what is served and what is not, matching the declaration exactly (FR-006)
- [X] T016 [US1] Fill in the `check-declaration` target in the root `Makefile` to run `tools/check_declaration.py`
- [X] T017 [US1] Add a `declaration` job to `.github/workflows/ci.yml` running `make check-declaration`, and add a local `check-declaration` hook to `.pre-commit-config.yaml`

**Checkpoint**: a reader has one place to look, and a change that contradicts it fails before review.

---

## Phase 4: User Story 2 - Every level this repository resolves is pinned and declared (Priority: P1)

**Goal**: every library either server resolves is pinned exactly, declared once, pointed at from the
consumer register, and carries a reason when it is behind. The `0.15.0` pin moves to `1.0.0rc1`.

**Independent Test**: read `levels.json` with no code changed. This repository appears once per
library it resolves, each entry names where that level is declared and how it is acquired, and
anything behind the current published level carries a standing and a reason. Then change the pin in
one declared file and not the other, and `make check-levels` refuses to start.

### Tests for User Story 2

- [X] T018 [P] [US2] Write `tools/tests/test_check_levels.py` asserting the check fails when a path in `declared_in` states a level different from `level`, when `standing` is not `current` and `reason` is missing, and when `behind_temporary` is missing `tracked`
- [X] T019 [P] [US2] Write `server/tests/test_versions.py` asserting the source server's version request returns its own version and the resolved level of every library it imports, read from the installed distribution rather than from a literal

### Implementation for User Story 2

- [X] T020 [US2] Create `levels.json` at the repository root: `register` pointing at the consumer register feature 004 defines, and one `ResolvedLibrary` entry per library, starting with `idfkit` declared in `server/pyproject.toml` and `server/uv.lock`, resolution "exact pin", `standing` and `reason` per the decision in research.md R1
- [X] T021 [US2] Create `tools/check_levels.py`: validate `levels.json` against `tools/schemas/levels.schema.json`, parse each path in `declared_in` for the level it actually states (`server/pyproject.toml`, `server/uv.lock`, and later `model-server/package.json`), and exit non-zero naming both files when two disagree (FR-012)
- [X] T022 [US2] Move the pin from `idfkit==0.15.0` to `idfkit==1.0.0rc1` in `server/pyproject.toml` and regenerate `server/uv.lock` with `make lock`
- [X] T023 [US2] Add an `idfkit-lsp/versions` custom request to `server/src/idfkit_lsp/server.py` returning the server's own version and every resolved library level via `importlib.metadata` (FR-014)
- [X] T024 [US2] Add `idfkit-lsp/versions` to the `source` server's capabilities in `capabilities.json` as present
- [X] T025 [US2] Fill in the `check-levels` target in the root `Makefile` and add a `levels` job to `.github/workflows/ci.yml` running it
- [X] T026 [US2] Update `.github/workflows/bump-idfkit.yml` so an automated bump also updates `level` in `levels.json` and re-runs `make check-levels`, since a bump that leaves the declaration behind is exactly the silence this story removes
- [X] T027 [US2] Draft this repository's consumer-register entry pointing at `levels.json`, and record in `specs/001-two-server-editor-support/tasks.md` progress notes that the entry is submitted to the register repository (cross-repository; this repository's own checks cover only its side, per research.md R6)

**Checkpoint**: the level question is answerable from one file in under a minute, and being behind is a decision on the record.

---

## Phase 5: User Story 3 - A modeller's model file stops being grey (Priority: P1)

**Goal**: the model server exists, the client launches it for model text and only for model text,
and every character of an open model file is classified from the language service's regions.

**Independent Test**: open a model file and every character is classified. Send the same text to the
model server at the protocol boundary with no editor running: the regions cover the text exactly,
with no gaps and no overlaps, and concatenating what they select reproduces the input. Do it for a
file missing a terminator and get a complete classification anyway.

**Depends on**: the language service from feature 005. Until it ships, T031's guard path and T038
are what run, and they must pass on their own.

### Tests for User Story 3

- [X] T028 [P] [US3] Write `model-server/tests/positions.test.ts` covering conversion between the unit the service states and each protocol position encoding, over text containing characters outside the basic plane, over both line-ending conventions, and over text mixing them
- [X] T029 [P] [US3] Write `model-server/tests/capabilities.test.ts` asserting the TypeScript loader applies the same state rules as the Python one and refuses the same malformed declarations
- [X] T030 [P] [US3] Write `model-server/tests/service.test.ts` asserting that a missing language service produces the guard's own message unchanged, and that nothing else in startup swallows it

### Implementation for User Story 3

- [X] T031 [P] [US3] Create `model-server/src/capabilities.ts`: typed loader for the root `capabilities.json`, mirroring `server/src/idfkit_lsp/capabilities.py`, with the same state rules failing at load
- [X] T032 [P] [US3] Create `model-server/src/positions.ts`: the only arithmetic over model text in this repository, converting service offsets to protocol positions and back, honouring the client's negotiated position encoding, with a file-level comment naming it as the single declared exception to Principle I
- [X] T033 [US3] Create `model-server/src/service.ts`: the single import of the language service, through the shared name's subpath per research.md R2, catching the guard's error and re-reporting it unchanged
- [X] T034 [US3] Create `model-server/src/documents.ts`: one service handle per open document keyed by URI, holding `uri`, `version`, `handle`, and `encoding`, fed edits under incremental synchronisation, with the text-only fallback isolated here per `contracts/language-service-expected.md`
- [X] T035 [US3] Create `model-server/src/handlers/semanticTokens.ts`: translate the service's regions into `textDocument/semanticTokens/full`, reordering only where the protocol requires it, adding, dropping, merging, and reclassifying nothing
- [X] T036 [US3] Create `model-server/src/main.ts`: protocol wiring over stdio, advertising from `capabilities.ts`, negotiating incremental document synchronisation, and answering a request for an unserved document as unsupported rather than by guessing
- [X] T037 [US3] Add an `idfkit-lsp/versions` handler to `model-server/src/main.ts` reporting the model server's version and its resolved library levels, and add the entry to `model-server/package.json` in `declared_in` within `levels.json`
- [X] T038 [US3] Contribute the model-text document kind in `package.json`: a `contributes.languages` entry mapping the extension to a language id, an `onLanguage` activation event for it, and `engines.vscode` raised to `^1.86.0` per research.md R3
- [X] T039 [US3] Extend `client/src/extension.ts` to launch the model server as a second independent client, resolving the runtime via `process.execPath` with `ELECTRON_RUN_AS_NODE=1` and an `idfkitLsp.nodePath` override, with its own output channel and its own document selector
- [X] T040 [US3] Add the `idfkitLsp.nodePath` setting to `package.json` configuration, mirroring `idfkitLsp.pythonPath`
- [X] T041 [US3] Add a build step for the model server to the root `package.json` scripts, bundling `model-server/src/main.ts` to `model-server/dist/`, and make `vscode:prepublish` run it alongside the client build
- [ ] T042 [US3] Flip the model server's `textDocument/semanticTokens/full` entry in `capabilities.json` from `absent_temporary` to `present`, and remove its tracked item. **Deferred, and deliberately.** `@idfkit/language` is not published, so the server cannot answer this request and the declaration must not say it can: `tests/protocol/test_declaration.py` is the thing that would catch the lie. The handler and its translation are written and tested. This is a one-line edit the day the component ships

**Checkpoint**: a model file opens coloured, the source server is untouched, and the model server's absence is a message rather than a crash.

---

## Phase 6: User Story 4 - The other four answers reach the editor (Priority: P2)

**Goal**: findings, completion, explanation, and declaration all reach the editor, each a
translation of what the language service returned and nothing more. Findings first, because a
finding tells a modeller they have a problem and completion only helps them avoid one.

**Independent Test**: at the protocol boundary with no editor, send a file with one known bad field
and receive a diagnostic whose range selects the offending value character for character. Ask for
completion at a known field and receive exactly what the schema permits. Ask for hover on a field
and receive the schema's own words. Ask where a name is declared and receive the declaring object's
name region, and every one of them when a name is declared more than once.

### Tests for User Story 4

- [X] T043 [P] [US4] Write `model-server/tests/handlers.diagnostics.test.ts` asserting message, severity, and code pass through unchanged, that findings from reading and from validating arrive on the same terms, and that no finding is produced locally
- [X] T044 [P] [US4] Write `model-server/tests/handlers.completion.test.ts` asserting that "the schema constrains nothing here" returns an empty list marked complete, that "no schema is available" does not return an empty list at all, and that no local fallback list exists to fall back to
- [X] T045 [P] [US4] Write `model-server/tests/handlers.hover.test.ts` asserting that whitespace, a separator, and a comment each return nothing rather than the nearest field

### Implementation for User Story 4

- [X] T046 [US4] Create `model-server/src/absence.ts`: the three-way outcome type distinguishing "permits nothing", "constrains nothing", and "cannot answer, no schema", so that no handler can flatten them into one empty result (FR-021)
- [X] T047 [US4] Create `model-server/src/handlers/diagnostics.ts`: serve `textDocument/diagnostic` on request where the client advertises it can request, publish on change only where it cannot, translating each finding's region and nothing else (research.md R11)
- [X] T048 [P] [US4] Create `model-server/src/handlers/completion.ts`: translate what the service says the schema permits at an offset, returning the empty-and-complete result for "constrains nothing" and the absence signal for "no schema"
- [X] T049 [P] [US4] Create `model-server/src/handlers/hover.ts`: translate the service's explanation at an offset, returning nothing where the service returns nothing
- [X] T050 [P] [US4] Create `model-server/src/handlers/definition.ts`: return every region the service reports for the name under the offset, never one chosen here
- [X] T051 [US4] Register the four handlers in `model-server/src/main.ts` and drop a computed answer whose document version the editor has since superseded
- [ ] T052 [US4] Flip `textDocument/diagnostic`, `textDocument/publishDiagnostics`, `textDocument/completion`, `textDocument/hover`, and `textDocument/definition` to `present` on the model server in `capabilities.json`. **Deferred for the same reason as T042**, and on the same terms: the four handlers exist, their translations are tested against fixed service results, and the protocol groups that prove them skip with a message naming the missing component

**Checkpoint**: all five answers reach the editor, and the three absences reach it as three.

---

## Phase 7: User Story 5 - Both servers are proved without an editor (Priority: P2)

**Goal**: one suite, two servers, protocol in and protocol out, no editor anywhere, in CI on every
change, asserting the declaration against the servers in both directions.

**Independent Test**: with no editor installed on the machine, run the suite. Both servers start,
answer, and shut down, every advertised request is exercised, and a capability advertised in the
declaration but absent from a server fails the run.

### Implementation for User Story 5

- [X] T053 [US5] Create `tests/protocol/harness.py`: a portable stdio JSON-RPC client reading with a blocking reader on a thread rather than `fcntl` and `select`, so it runs on Windows (research.md R7)
- [X] T054 [US5] Create `tests/protocol/conftest.py`: fixtures spawning each server as a subprocess in its own runtime, plus `CANDIDATE_FIRST` and `CANDIDATE_SECOND` switches that resolve either library from an unpublished build without changing any declared level, saying so plainly when neither is given (FR-037, research.md R8)
- [X] T055 [US5] Create `tests/protocol/test_declaration.py`: for every capability marked present, assert the owning server answers it; for every request either server answers, assert it appears in the declaration; fail naming the discrepancy in either direction (FR-035, SC-001)
- [X] T056 [US5] Move `server/tests/test_server_integration.py` to `tests/protocol/test_source_server.py`, port it onto `harness.py`, and delete the POSIX-only reader it used
- [X] T057 [US5] Create `tests/protocol/test_model_server.py` with a `classify` group asserting total coverage with no gaps or overlaps on parseable text, on text missing a terminator, and on text whose version cannot be determined (US3 acceptance 2, 3, 5)
- [X] T058 [US5] Extend `tests/protocol/test_model_server.py` with the four remaining answers: a character-for-character diagnostic range including inside an extensible group and across a comment, completion against the schema, hover returning nothing off a field, multiple declarations for one name, and a range over text outside the basic plane (US4 acceptance 1 through 7)
- [X] T059 [US5] Add a `missing_component` group to `tests/protocol/test_model_server.py` asserting that startup without the language service reports what to install in the guard's own words and that the source server is unaffected, passing whether or not the component is installed (US3 acceptance 6, quickstart scenario 7)
- [X] T060 [US5] Add an ownership group to `tests/protocol/test_model_server.py`: opening a model document starts the model server and not the source server and the reverse, a request for an unserved document is answered as unsupported, and one server stopping leaves the other serving (US3 acceptance 1, FR-030)
- [X] T061 [US5] Create `tests/protocol/test_budget.py` measuring an answer at a cursor after a single-character edit at the protocol boundary, and wire it to `bench-protocol` in the root `Makefile` (SC-012)
- [X] T062 [US5] Fill in the `test-protocol` target in the root `Makefile` with `ARGS` pass-through, and add a `protocol` job to `.github/workflows/ci.yml` running it across Python 3.10 through 3.13 and on the model server's runtime (FR-034)

**Checkpoint**: every advertised capability is proved mechanically, and the declaration can no longer describe a server that does not behave that way.

---

## Phase 8: User Story 6 - Knowledge cannot get in (Priority: P2)

**Goal**: a check rejects a schema table, a grammar pattern, or offset arithmetic before review, and
the two tables already in the source server are derived from the installed library instead of
written down.

**Independent Test**: add a dictionary of field names, a grammar pattern, and a function computing a
field index from an offset, each in a separate change, and each is rejected by `make check-knowledge`
rather than by a reader. Then audit the repository as it stands and find zero of the three present.

### Tests for User Story 6

- [X] T063 [P] [US6] Write `tools/tests/test_check_knowledge.py` with a fixture tree containing each of the three forbidden shapes and asserting each is rejected, that `model-server/src/positions.ts` is exempt, and that a suppression without a reason at the point of suppression fails
- [X] T064 [P] [US6] Add the two silent-regression cases to `server/tests/test_analyzer.py`: a document bound through a subscripted annotation now that the document type is generic, and a document obtained from `load_idf_with_diagnostics`. Both must infer. Both fail before T066 lands, which is the demonstration the written tables were wrong (research.md R1)
- [X] T065 [P] [US6] Write `server/tests/test_library_surface.py` asserting derivation finds the document-producing callables and the recognised type names from the installed library, and that a derivation yielding nothing records the capability as temporarily absent rather than substituting a table

### Implementation for User Story 6

- [X] T066 [US6] Create `tools/check_knowledge.py`: scan `server/src/`, `model-server/src/`, and `client/src/` for collections of string literals shaped like object types or field names, pattern literals applied to model text, and arithmetic deriving an element from a text offset; exempt `model-server/src/positions.ts` by name; require a reason at the point of any suppression (FR-025, research.md R9)
- [X] T067 [US6] Create `server/src/idfkit_lsp/library_surface.py`: derive `document_factories` and `type_names` from the installed `idfkit` by resolving annotations against the defining module's globals, unwrapping a generic subscript to its origin, cached for the process, recording `source` as derived or fallback (research.md R4)
- [X] T068 [US6] Delete `_DOCUMENT_FACTORIES` and `_TYPE_NAMES` from `server/src/idfkit_lsp/analyzer.py` and read from `library_surface.py` instead, unwrapping a subscripted annotation to its origin so an annotated document infers again
- [X] T069 [US6] Audit `server/src/`, `model-server/src/`, and `client/src/` against FR-024 and record every residual in the Complexity Tracking table of `specs/001-two-server-editor-support/plan.md` with what will remove it (FR-027)
- [X] T070 [US6] Record the analyzer's retained API-shape knowledge as a capability note in `capabilities.json` or a tracked item, per the plan's second Complexity Tracking row, so it is visible rather than assumed
- [X] T071 [US6] Fill in the `check-knowledge` target in the root `Makefile`, add a local hook for it to `.pre-commit-config.yaml`, and add a `knowledge` job to `.github/workflows/ci.yml`

**Checkpoint**: the helpful contribution that would have been correct on the day it landed is now rejected on that day.

---

## Phase 9: User Story 7 - A second editor costs a wrapper, not a port (Priority: P3)

**Goal**: everything a user sees comes from a server, so an editor that is not the targeted one
needs a launch configuration and nothing else.

**Independent Test**: read the client. It locates and starts each server, declares which documents
each serves, surfaces server output, and does nothing else. Then drive the two servers from a plain
protocol client and every capability marked present in the declaration is answered with no part of
this repository's client loaded.

### Tests for User Story 7

- [X] T072 [P] [US7] Write `tests/protocol/test_no_client.py` asserting every capability marked present in the declaration is answered while no client code is loaded, and that what remains reachable only through the client is exactly the set marked `editor_specific` (FR-031, SC-010)

### Implementation for User Story 7

- [X] T073 [US7] Audit `client/src/extension.ts` against FR-028 and FR-029 and remove anything that is not server location, server launch, document-kind declaration, or output surfacing
- [X] T074 [US7] Mark `workspace/executeCommand` for the documentation lookup as `editor_specific: true` in `capabilities.json` with a note that the server resolves the address and opening it is the editor's act (research.md R13, FR-032)
- [X] T075 [US7] Add a launch-configuration example for a non-targeted editor to `README.md`, driving both servers over stdio, so the claim that a wrapper is all it costs is demonstrable rather than asserted

**Checkpoint**: nothing a user depends on lives in the client.

---

## Phase 10: Polish & Cross-Cutting Concerns

- [X] T076 [P] Rewrite `README.md` to render `capabilities.json` rather than restate it, so a capability change updates the readme by construction (FR-006)
- [X] T077 [P] Update `CLAUDE.md` for the four-tree structure, the two declared records, the three checks, and the model server's runtime and pins
- [X] T078 [P] Update `.github/workflows/bump-idfkit.yml` instructions to name `make check` at the root rather than `cd server && uv run pytest`, since the gate has moved
- [X] T079 Run every scenario in `specs/001-two-server-editor-support/quickstart.md` end to end, including the deliberate breakages in scenarios 1, 2, and 8, and record any that do not behave as written
- [X] T080 Re-evaluate the Constitution Check table in `specs/001-two-server-editor-support/plan.md` against the built repository and record the post-implementation result
- [X] T081 [P] Bump `version` in `package.json`, `client/package.json`, `model-server/package.json`, and `server/pyproject.toml` together, and confirm `make check-levels` still passes
- [X] T082 Complete `specs/001-two-server-editor-support/checklists/requirements.md` against the delivered work

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: no dependencies
- **Foundational (Phase 2)**: depends on Setup. Blocks every user story
- **US1 (Phase 3)**: depends on Foundational. Blocks US3, US4, US5, US7, because all four read or assert against the declaration
- **US2 (Phase 4)**: depends on Foundational. Independent of US1
- **US3 (Phase 5)**: depends on US1 (the declaration the model server advertises from) and on Setup T001. Blocked on feature 005 for T033 through T035
- **US4 (Phase 6)**: depends on US3. The server must exist before four more handlers hang off it
- **US5 (Phase 7)**: depends on US1 for T055, on US3 for T057, on US4 for T058. T053, T054, T056 depend on Foundational alone
- **US6 (Phase 8)**: depends on Foundational. T064 depends on US2 T022, because the regressions appear at the adopted level
- **US7 (Phase 9)**: depends on US1 and on US5's harness
- **Polish (Phase 10)**: depends on every story that is being shipped

### External Dependencies

- Feature 005 of the unification ships the language service. Until it does, T033, T034, T035, and every handler in US4 are blocked on `contracts/language-service-expected.md` being reconciled. T030 and T059, the paths where the component is absent, are not blocked and must pass on their own.
- Feature 004 of the unification defines the consumer register. T027 writes into another repository; `levels.json` and `check_levels.py` are this repository's enforceable half and are not blocked.

### Within Each User Story

- Tests before the implementation they cover, and failing before it lands
- Loaders before the code that reads them
- Handlers before the declaration entry that marks them present, so the declaration is never ahead of the server
- Story complete and independently testable before the next priority

### Parallel Opportunities

- Every Setup task is `[P]`
- T006 and T007 run alongside each other once T005 exists
- US1 and US2 are fully independent and can run side by side: neither touches a file the other touches
- US6 is independent of US3 and US4 except for T064, so the knowledge check can land while the model server is blocked on feature 005
- Within US3, T031 and T032 are independent of the service and can land before feature 005
- Within US4, the three handler tests and the three non-diagnostic handlers are each on their own file

---

## Parallel Example: User Story 1

```bash
# Tests first, both files independent:
Task: "Loader state rules in server/tests/test_capabilities.py"
Task: "Check behaviour in tools/tests/test_check_declaration.py"

# Then the declaration and the two readers of it:
Task: "capabilities.json at the repository root"
Task: "Typed loader in server/src/idfkit_lsp/capabilities.py"
```

## Parallel Example: US1 and US2 together

```bash
# Two developers, no shared file:
Developer A: T009 through T017   # capabilities.json, its loader, its check
Developer B: T018 through T027   # levels.json, its check, the pin move
```

---

## Implementation Strategy

### MVP First

The spec puts three stories at P1, and they are not one increment. Ship them in this order and stop
after each:

1. Phase 1 and Phase 2
2. **US1**. Delivers alone, against the repository exactly as it stands, and turns today's silence into a readable fact. This is the smallest thing worth shipping
3. **US2**. Delivers alone, costs one file and one pin move, and makes every later story safe
4. **US3**. Blocked on feature 005 for its three service-facing tasks. Everything else in it, including the client wiring and the absent-component path, lands before feature 005 does

### Incremental Delivery

1. Foundation → US1 → a reader can answer "what does this do" (ship)
2. → US2 → a maintainer can answer "what does it run on" (ship)
3. → US6 → knowledge cannot get in, and the two live regressions at the new pin are fixed (ship)
4. → US3 → model files stop being grey (ship, once feature 005 lands)
5. → US4 → the other four answers arrive (ship)
6. → US5 → all of it is proved without an editor, and the declaration stops being able to lie
7. → US7 → the audit that makes it worth something outside one editor

US5 sits late in the order because it needs two servers to cover two servers, but T053, T054, and
T056 should land with US2 so that the source server is already being driven over a portable harness
before anything new hangs off it.

### Parallel Team Strategy

1. Everyone completes Setup and Foundational
2. Then: Developer A takes US1 and US7, Developer B takes US2 and US6, Developer C takes US3 and US4 and picks up the blocked service-facing tasks when feature 005 lands
3. US5 is assembled by whoever finishes first, since its harness tasks are unblocked from the start

---

## Notes

- `[P]` means a different file and no dependency on an incomplete task
- A capability entry flips to `present` in the same change as the handler that answers it, never before
- `model-server/src/positions.ts` is the only file in this repository permitted to compute over model text, and `tools/check_knowledge.py` is what keeps that true
- Commit after each task or logical group, and run `make check` from the root before proposing anything

---

## Progress notes

**Completed**: 2026-09-04. `make check` passes from the repository root: lint, format, Pyright and
`tsc` over both languages, the three declaration checks, 111 source-server unit tests, 175
model-server unit tests, and 25 passing protocol tests with 17 skipped.

**T027, cross-repository.** This repository's consumer-register entry is drafted at
`contracts/consumer-register-entry.toml` and its destination is `governance/consumers.toml` in
`idfkit-conformance`, not this repository. Submitting it is a change to that repository and is
outstanding. This repository's enforceable half, `levels.json` and `tools/check_levels.py`, is done
and passing, and research R6 is explicit that this is the correct division: a check here cannot
enforce anything about a file there.

**T042 and T052, gated externally.** `@idfkit/language` does not exist. It is not in `idfkit-js`,
whose packages are `core`, `idfkit`, `schemas`, `weather` and two type packages, and neither it nor
the `idfkit` facade is published to npm. Everything that does not depend on it is finished: the
model server exists, advertises from the declaration, negotiates incremental synchronisation,
reports its own levels, answers an unserved document as unsupported, and reports the facade's guard
message unchanged when the component is absent. Its five model-text answers are written as pure
translations and unit-tested against fixed service results. The two flips are held back because a
declaration that claims an answer the server cannot give is the one failure this feature exists to
make impossible.

**Two additions beyond the task list, both recorded rather than slipped in.**

1. `pygls` and `lsprotocol` were resolved by range rather than pinned exactly, and
   `vscode-languageclient` by caret range. Principle III says every resolved library is pinned
   exactly, so all three are now exact and all seven libraries appear in `levels.json`.
2. `capabilities.json` gained a `retained_knowledge` array, and both schema copies gained the
   matching property. That is where T070 records the analyzer's retained API-shape knowledge and the
   position arithmetic in `positions.ts`, so a reader finds both in the file they already read
   rather than only in the plan. The declaration's `version` moved to 2 accordingly.

**One thing the audit found that the check cannot catch**, recorded in plan.md Complexity Tracking:
the two deleted tables were four and three entries long, under the five-literal threshold
`tools/check_knowledge.py` uses. They are removed by derivation, not by the check. Lowering the
threshold would reject ordinary tuples of protocol method names, which research R9 names as the
failure mode to avoid.

**One defect found and fixed while running the quickstart**: `uv run` re-locks and re-syncs by
default, so `make check-levels` was repairing `server/uv.lock` to agree with a `pyproject.toml` it
was in the middle of checking. Every `uv run` in the Makefile and in the pre-commit hooks now passes
`--frozen`. A check must not repair what it is checking.
