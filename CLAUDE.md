# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

`.specify/memory/constitution.md` governs. Where this file and the constitution disagree, the
constitution is right and this file is the defect.

## Project Overview

idfkit-lsp ships editor support for two different things, and it owns protocol rather than
knowledge. That sentence decides most questions here.

- **Source server** (`server/`): Python, pygls. Serves Python files that use the idfkit library:
  completion, hover, signature help, a documentation command, and a versions request. Everything it
  knows about EnergyPlus comes from the installed `idfkit`.
- **Model server** (`model-server/`): TypeScript, ESM, on the editor's own Node runtime. Serves
  EnergyPlus model text by wrapping the `@idfkit/language` service, translating positions and
  nothing else. Peer of the source server, not a subordinate.
- **Client** (`client/`): the VS Code extension. Locates and starts each server, declares which
  documents each serves, surfaces server output. Nothing else lives here.
- **Protocol suite** (`tests/protocol/`): one suite, both servers, protocol in and protocol out,
  no editor anywhere.
- **Checks** (`tools/`): the three gates that hold the constitution up before review.

## The two declared records

Both sit at the repository root because both are read from both languages.

- **`capabilities.json`** is the single source of truth for what each server advertises. Both
  servers advertise from it, the client reads it for its document selectors, the readme renders it,
  and the protocol suite asserts it against the servers in both directions. A capability entry flips
  to `present` in the same change as the handler that answers it, never before.
- **`levels.json`** records every library this repository resolves, where each level is declared,
  how it is acquired, and the kind and reason when it is behind. The consumer register in
  `idfkit-conformance` points at it and holds no level of its own.

Three states and no fourth: `present`, `absent_permanent` (needs `reason` and `instead`),
`absent_temporary` (needs `tracked`). Both runtimes fail at load on a malformed declaration.

## Commands

All run from the repository root. Package managers are **uv** (Python) and **npm** (TypeScript).

```bash
make install           # Install both runtimes
make check             # The one command a change is held to
make fix               # Auto-fix lint and format

make lint              # Ruff over server/, tools/, tests/
make format            # Ruff format check
make typecheck         # Pyright over the Python trees, tsc over the model server

make check-declaration # capabilities.json agrees with the manifest, the readme, and the servers
make check-levels      # levels.json agrees with every file that declares a level
make check-knowledge   # no schema table, grammar pattern, or model-text offset arithmetic

make test              # Source server unit tests
make test-model        # Model server unit tests
make test-protocol     # Both servers over the protocol, no editor (ARGS=... passes through)
make bench-protocol    # An answer at a cursor, measured at the protocol boundary
make build             # Bundle the client and the model server
```

Single tests:

```bash
cd server && uv run pytest tests/test_analyzer.py::TestImportTracking::test_name -v
uv run --project server python -m pytest tests/protocol/test_declaration.py -v
cd model-server && npx vitest run tests/positions.test.ts
```

Python outside `server/` runs as `uv run --project server <cmd>` from the repository root, which
keeps the working directory at the root so `tools` and `tests.protocol` import.

## Architecture

### Source server (`server/src/idfkit_lsp/`)

Pipeline: **document change → AST analysis → handler response**.

1. `server.py` — pygls wiring. Registers only what `capabilities.json` marks present on the source
   server, and a logging bridge forwarding Python logs to the client
2. `capabilities.py` — typed loader for `capabilities.json`, with the state rules enforced at load
3. `library_surface.py` — derives the document-producing callables and the recognised type names
   from the installed `idfkit` by resolving its annotations. There is no written table
4. `analyzer.py` — single-pass AST visitor tracking imports and inferring variable types
   (`InferredType` with `IdfKitType`: DOCUMENT, COLLECTION, OBJECT, plus an optional `object_type`)
5. `document_state.py` — per-document analysis cache
6. `schema_cache.py` — wraps `idfkit.schema.EpJSONSchema`; holds no field data of its own
7. `completion.py`, `hover.py`, `signature_help.py` — handlers reading the analyzer and the schema

### Model server (`model-server/src/`)

1. `main.ts` — protocol wiring over stdio, advertising from `capabilities.ts`
2. `capabilities.ts` — the TypeScript loader for `capabilities.json`, same rules as the Python one
3. `service.ts` — the single import of `@idfkit/language`, through the `idfkit/language` subpath,
   with the facade's guard message passed through unchanged when the component is absent
4. `documents.ts` — one service handle per open document, fed edits under incremental sync
5. `positions.ts` — **the only arithmetic over model text in this repository**, and the single
   declared exception to Principle I. `tools/check_knowledge.py` exempts it by name
6. `handlers/` — semantic tokens, diagnostics, completion, hover, definition. Each is a pure
   translation of what the service returned

## Style

- Ruff: line length 99, rules E/W/F/I/UP/B/SIM/TC/RUF. Pyright basic, Python 3.10 target
- `from __future__ import annotations` in every Python module
- Typed objects (frozen dataclasses, enums) over dictionaries, in both languages
- TypeScript: strict, ESM, NodeNext, so relative imports carry an explicit `.js` extension
- No em-dashes in prose

## What must not get in

Principle I is the rule most likely to be broken by a helpful change, which is why a check enforces
it rather than a reviewer:

- No list of object types or field names anywhere. Those come from `idfkit` or from the language
  service, and a local copy is correct on the day it is written and silently wrong after
- No grammar pattern applied to model text
- No arithmetic deriving an element from a text offset outside `model-server/src/positions.ts`
- No answer assembled locally when a library declines to give one. An absence is stated, and an
  absence that is permanent or temporary is recorded in `capabilities.json` with its kind

A suppression is available and costs a sentence: `# check-knowledge: allow <reason>` or the `//`
form. The reason is required, which is what keeps suppressions countable.

## The external dependency

`@idfkit/language` (feature 005 of the unification) is not published. The model server is written
against its contracted surface, recorded in
`specs/001-two-server-editor-support/contracts/language-service-expected.md`, and reaches it through
a guard. Until it ships, the model server's five model-text answers are `absent_temporary` in
`capabilities.json`, and the paths that run are the guard path and the pure translations. When it
ships, those entries flip to `present` and the protocol suite's skipped groups start running.

## CI

`.github/workflows/ci.yml`: lint, typecheck (both languages), the three declaration checks, the
source server across Python 3.10 to 3.13, the model server, and the protocol suite on Linux and
Windows. Pre-commit runs ruff, pyright, and the three checks.

## Automated idfkit bumps

When invoked by `.github/workflows/bump-idfkit.yml` on failure after an idfkit version bump:

- Make the smallest possible compatibility change. No unrelated refactors, no broad reformatting
- A bump moves `level` in `levels.json` too. If `make check-levels` fails, the declaration is behind
  the pin: fix the declaration, not the check
- Run `make check` from the repository root before finishing
- Summarise: root cause, files changed, checks run, remaining risks
