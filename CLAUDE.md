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
  nothing else. Peer of the source server, not a subordinate. Bundled in the VS Code extension and
  published to npm as `@idfkit/language-server` for every other editor.
- **Client** (`client/`): the VS Code extension. Locates and starts each server, declares which
  documents each serves, surfaces server output. Nothing else lives here.
- **Protocol suite** (`tests/protocol/`): one suite, both servers, protocol in and protocol out,
  no editor anywhere.
- **Checks** (`tools/`): the three gates that hold the constitution up before review, plus
  `check_package.py`, which checks the packed npm tarball and its command (CI and release only),
  and `check_vsix.py`, which checks the unpacked VS Code extension and its model server (CI only).

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
make install           # Install both runtimes, the client and the packaging tools
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
make package           # Package the VS Code extension (VSIX=<path> names the output)
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
3. `service.ts` — the single import of the language service, through the `@idfkit/idfkit/language`
   subpath and no other name, with the facade's guard message passed through unchanged when the
   component is absent. `inputs.ts` reaches the rest of the library through `@idfkit/idfkit` the same way
4. `documents.ts` — one service handle per open document, fed edits under incremental sync
5. `positions.ts` — **the only arithmetic over model text in this repository**, and the single
   declared exception to Principle I for that arithmetic. `tools/check_knowledge.py` exempts it by
   name
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

`language-configuration.json` is a recorded exception: it holds the line comment marker and nothing
else, because no server can supply it (`retained_knowledge` in `capabilities.json`). A `wordPattern`
or a TextMate grammar is a grammar pattern and is not permitted.

A suppression is available and costs a sentence: `# check-knowledge: allow <reason>` or the `//`
form. The reason is required, which is what keeps suppressions countable.

## The external dependency

`@idfkit/language` (feature 005 of the unification) is published, and so is the facade
`@idfkit/idfkit` that exposes it at `@idfkit/idfkit/language`. Both are exact dependencies of the
model server, which is written against the contracted surface recorded in
`specs/001-two-server-editor-support/contracts/language-service-expected.md` and reaches it only
through the facade. The model server's five model-text answers are `present` in
`capabilities.json`. The guard path still runs, and is still tested, for an install where the
component is missing.

## Publishing the model server

`model-server/package.json` is the npm package `@idfkit/language-server`, with the command
`idfkit-language-server`. `prepack` copies the root `capabilities.json` into `dist/` and the root
`LICENSE` into the package, and `postpack` removes both, so the checkout always reads the root
declaration. The `packed` job in `ci.yml` installs the tarball into an empty directory, runs
`tools/check_package.py`, and runs the protocol suite against that install through
`MODEL_SERVER_PACKAGE`. The `publish-npm` job in `release.yml` publishes from the same tag as PyPI,
by trusted publishing, prereleases under `next`.

## Packaging the extension

The model server bundle leaves `@idfkit/*` external, and `@idfkit/schemas` is read from disk, so a
VSIX must carry those packages beside the bundle. `vscode:prepublish` runs `npm ci` in `client/` and
in `model-server/`, which holds the delivered levels to the lockfiles, and replaces whatever
`node_modules` those directories held. The root `npm ci` remains a prerequisite, because the
prepublish step itself runs the root `esbuild`. `.vscodeignore` keeps
`model-server/node_modules/@idfkit/**` and nothing else from that directory. Every other direct
runtime dependency of the model server is compiled into `dist/main.js`, but a third-party runtime
dependency of an `@idfkit` package is not, because those packages are external. A new package of
either kind that is not bundled needs its own line there.

## CI

`.github/workflows/ci.yml`: lint, typecheck (both languages, and the client in a job of its own,
outside `make check`), the three declaration checks, the source server across Python 3.10 to 3.13,
the model server, the protocol suite on Linux and Windows on Node 20.9.0, and the protocol suite again against the packed npm tarball and against the packaged
VSIX. The `vsix` job runs `make install` and `make package`, unzips the VSIX outside the checkout,
and runs `tools/check_vsix.py`, which fails if the packaged model server does not advertise what
`capabilities.json` marks present or warns on start. Pre-commit runs ruff, pyright, and the three
checks.

## The consumer register

This repository is `idfkit-lsp` in the consumer register, `governance/consumers.toml` in
idfkit-conformance, read at the governance tag pinned in `.github/workflows/ci.yml`. It is the one
consumer with two Resolutions, one per server, and the two say nothing about each other.

- **Where the levels live**: idfkit in `server/pyproject.toml` and again in `levels.json`;
  `@idfkit/idfkit`, `@idfkit/core` and `@idfkit/language` in `model-server/package.json` and again in
  `levels.json`. The register points at the manifest and requires the declarations of one release to
  agree, which `make check-levels` already enforces here. The model server imports only through the
  shared name, and pins the scoped packages beside it for exact levels and their types. The register
  reads the door from those runtime dependencies, so it records `scoped`.
- **Self-check**: the `consumer-register` job in `ci.yml` calls `check-consumer.yml` at that tag. It
  fails when a level moves to a file the register does not point at, when a new dependency on either
  library appears unregistered, or when the entry point changes. Bumping a level needs no register
  change; moving where it is declared does, in idfkit-conformance.
- **Rehearsal**: `.github/workflows/rehearse-candidate.yml` takes a library and a ref in that
  library's repository, and runs that server's type check and tests against the candidate without
  touching a manifest or lockfile. Its rename scan also reads this file and `README.md`, because prose
  that teaches a call is read by every agent in this repository and by no type checker.
- **Version**: the source server answers `idfkit-lsp/versions` with its own version and the levels it
  read, from the installed distributions.

## Automated idfkit bumps

When invoked by `.github/workflows/bump-idfkit.yml` or `.github/workflows/bump-idfkit-js.yml` on
failure after a version bump:

- Make the smallest possible compatibility change. No unrelated refactors, no broad reformatting
- A bump moves `level` in `levels.json` too, through `tools/declare_level.py`, which declares the
  spelling the lockfile or manifest states. If `make check-levels` fails, the declaration is behind
  the pin: fix the declaration, not the check
- Run `make check` from the repository root before finishing
- Summarise: root cause, files changed, checks run, remaining risks

Each bump also does three things that are not repairs: it lists every `idfkit:unavailable` statement
marker resting on a capability the new level closed and keeps the pull request a draft until each is
reviewed; it closes this repository's lag in the register for that library, through a paired pull
request in idfkit-conformance; and, dispatched with `decline_reason`, it bumps nothing and records a
deliberate lag instead. The two bumps are independent: neither language waits on the other.
