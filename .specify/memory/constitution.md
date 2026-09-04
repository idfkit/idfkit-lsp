<!--
SYNC IMPACT REPORT
Version change: (unfilled template) -> 1.0.0
Rationale: initial ratification. The previous file was the unmodified scaffold with every
placeholder intact, so this is the first constitution this repository has had rather than an
amendment to one.

Modified principles:
  (none; no prior principles existed)

Added sections:
  - Scope statement (preamble)
  - Core Principles I through VI:
      I. The Extension Translates, It Never Knows
      II. Two Servers, One Client, One Capability Story
      III. Levels Are Pinned and Declared
      IV. An Absent Capability Is Stated, Never Faked
      V. The Client Stays Thin
      VI. Editor-Facing Behaviour Is Tested Without an Editor
  - Repository Shape and Delivery
  - Development Workflow and Quality Gates
  - Governance

Removed sections:
  (none)

Template note: the resolved scaffold provides five principle slots. Six were ratified, so one
slot was added. Heading hierarchy is unchanged.

Deferred items:
  - TODO(CAPABILITY_MANIFEST_PATH): Principle II requires a single declared location for what each
    server advertises. The file does not exist yet and is named by the first feature that adds the
    second server.
  - TODO(CONSUMER_REGISTER_PATH): Principle III points at the consumer register defined by feature
    004 of the unification. The register is not yet published, so this constitution names it by
    role rather than by path.
-->

# idfkit-lsp Constitution

This repository ships editor support for two different things: source code in the first language,
and model text. It owns protocol, not knowledge. That sentence is the whole constitution; the
principles below are its consequences, and any conflict between them and this scope statement is
resolved in favour of the scope statement.

## Core Principles

### I. The Extension Translates, It Never Knows

This repository MUST NOT contain a schema table, a grammar pattern, or position arithmetic over
model text. Every answer returned to an editor MUST come from a library that owns the question:
field names, field descriptions, types, defaults, references, positions, and findings are read from
`idfkit` in the first language or from the language service in the second, never assembled here. A
change that introduces a literal list of field names, object types, or IDF tokens into this
repository MUST be rejected in review even when it is small, correct, and convenient.

Rationale: a rule that can be violated by a helpful contributor adding one dictionary of field
names is exactly the rule worth writing down. A local copy of schema knowledge is correct on the
day it is written and silently wrong on every release after it, and nothing in an editor tells the
user which of the two they are looking at.

### II. Two Servers, One Client, One Capability Story

The Python server serves source files in the first language. A second server, written in the second
language, serves model text. Neither MUST reimplement any part of the other: no analysis of model
text in the Python server, and no analysis of first-language source in the second server. What each
server advertises to the editor MUST be declared in one place in this repository, and that
declaration is the single source of truth for the client, for the documentation, and for the tests.
Adding, removing, or narrowing an advertised capability MUST change that declaration in the same
change.

Rationale: "hover works in Python files but not model files" should be a recorded fact a reader can
look up, not a surprise a user discovers. One declaration also keeps the two servers from growing
toward each other, which is where duplicated position arithmetic would first appear.

### III. Levels Are Pinned and Declared

Every library this repository resolves MUST pin an exact level, and every pinned level MUST be
declared in the consumer register that feature 004 of the unification defines, in the repository
that belongs to neither language. Where a declared level is behind the current published level, the
register MUST carry a kind and a reason, so that being behind is a decision on the record rather
than an oversight. A change to this repository's entry point, to how it resolves a library, or to
where its level is declared MUST fail this repository's own checks unless the register changes with
it. A change to the level alone needs no register change, because the register points at the level
rather than holding it.

Rationale: a consumer running ahead of the level it declares looks exactly like one running behind
it, and this repository is currently the example: the server pins an exact `idfkit` level with
nothing anywhere saying whether that level is current. This is the principle that pays for itself
first, because it costs one file and it answers a question that otherwise takes an afternoon.

### IV. An Absent Capability Is Stated, Never Faked

When the library cannot answer, the server MUST return nothing rather than a guess: an empty
completion list, no hover, no signature. It MUST NOT synthesise a plausible answer from a heuristic,
a cached fragment, a name pattern, or a previous document state. An absence that is permanent MUST
be recorded in the capability declaration required by Principle II, and an absence that is temporary
MUST name the tracked item that closes it.

Rationale: a plausible completion assembled locally is worse than an absent one, because a user
cannot tell it apart from a real one and it cannot be traced back to a schema. An empty result
teaches the user that the answer is not available; a fabricated result teaches them something false
about their model.

### V. The Client Stays Thin

The TypeScript client MUST contain only `vscode-languageclient` wiring and launch configuration:
locating and starting each server, declaring which documents each one serves, and surfacing server
output. Completion filtering, hover formatting, diagnostic interpretation, position translation
beyond what `vscode-languageclient` performs, and any schema or grammar knowledge MUST live in a
server. Where an editor requires client-side glue that cannot be moved into a server, that glue MUST
be recorded in the capability declaration as an editor-specific limitation.

Rationale: any logic that appears in the TypeScript client is logic that will not exist for a user
in a different editor. The client is the one part of this repository that a Neovim or Zed user never
runs, which makes it the one place where behaviour must not accumulate.

### VI. Editor-Facing Behaviour Is Tested Without an Editor

Every editor-facing behaviour MUST be tested at the protocol boundary: a request in, a response out,
with no VS Code and no editor process in the loop. Both servers MUST be covered the same way by the
same suite, and that suite MUST run in CI on every change. A behaviour that can only be demonstrated
by opening an editor is untested, and MUST NOT be relied on in review as evidence that a change
works.

Rationale: a suite that needs an editor is a suite that does not run, and a capability story that is
not exercised is a capability story that drifts from the servers it describes. Testing at the
protocol boundary also keeps the tests honest about Principle V, because anything the client papers
over is visible as a failing response.

## Repository Shape and Delivery

- `server/` holds the first-language server: Python, `pygls`, resolved with `uv`, installed with
  `pip`, and pinned to an exact `idfkit` level per Principle III.
- The second-language server for model text is a separate server launched by the same client, and
  it resolves the language service from the second language's library rather than reimplementing it.
- `client/` holds the VS Code extension and is bound by Principle V.
- Delivery paths that acquire either server by name MUST name the level they deliver, and MUST be
  able to report that level when asked. A rebuild alone MUST NOT change a delivered level.
- Style and typing gates for the first-language server are Ruff at line length 99 and Pyright, both
  configured in `server/pyproject.toml`. Typed objects (dataclasses or Pydantic) are preferred over
  raw dictionaries throughout.

## Development Workflow and Quality Gates

- Before any change is proposed, `make check` and `make test` MUST pass from `server/`, and the
  client MUST compile.
- Review MUST verify each principle that the change touches. In particular, a reviewer MUST reject a
  change that adds schema or grammar literals (I), that moves an advertised capability without
  updating its declaration (II), that changes resolution or entry point without updating the
  consumer register (III), that returns a locally assembled answer (IV), that adds logic to the
  client (V), or that adds an editor-facing behaviour with no protocol-level test (VI).
- A capability declared in one place per Principle II MUST match what the protocol tests observe.
  Where they disagree, the tests are correct and the declaration is the defect.
- Complexity MUST be justified in the change that introduces it. Absent a justification, the simpler
  form is the required one.

## Governance

This constitution supersedes other practices in this repository, including conventions recorded in
`CLAUDE.md`, wherever the two disagree.

**Amendment procedure**: an amendment is a pull request that changes this file, states the version
bump and its rationale, and updates any guidance or template that the amendment makes wrong in the
same change. An amendment that removes or redefines a principle MUST say what now governs the
behaviour that principle covered.

**Versioning policy**: this constitution is versioned as MAJOR.MINOR.PATCH. MAJOR for a backward
incompatible governance change, meaning a principle removed or redefined in a way that permits what
it previously forbade. MINOR for a principle or section added, or guidance materially expanded.
PATCH for clarifications, wording, and non-semantic refinements.

**Compliance review**: every pull request is reviewed against the principles above, and the CI suite
required by Principle VI is the mechanical half of that review. Runtime development guidance lives
in `CLAUDE.md`, which is subordinate to this file and MUST be corrected when it conflicts with it.

**Version**: 1.0.0 | **Ratified**: 2026-09-04 | **Last Amended**: 2026-09-04
