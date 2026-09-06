# Phase 1 Data Model: Two Servers, One Client, One Capability Story

**Feature**: `001-two-server-editor-support` | **Date**: 2026-09-04

This feature stores nothing and persists nothing. Its entities are two declared records read from
disk at startup and by the checks, plus the in-memory state each server keeps for a session. Every
one is loaded into a typed object on both sides; no handler receives a dictionary.

## Declared records

### CapabilityDeclaration

The whole of `capabilities.json`. Read by both servers, the protocol suite, the knowledge check,
and the readme generator. Schema in [contracts/capabilities.schema.json](./contracts/capabilities.schema.json).

| Field | Type | Rule |
|---|---|---|
| `version` | integer | Format version of this file. Bumped only when the shape changes |
| `servers` | list of `ServerDeclaration` | Exactly two, one per document kind. Never empty |

### ServerDeclaration

| Field | Type | Rule |
|---|---|---|
| `id` | `"source"` or `"model"` | Stable. Names a server, not a runtime |
| `documents` | list of `DocumentKind` | Non-empty, and disjoint from every other server's list. Two servers may not claim one document kind |
| `runtime` | string | Which language runs it. Descriptive; nothing branches on it |
| `capabilities` | list of `Capability` | Every protocol request this server has a position on. A request absent from this list is a defect, not an implicit "no" |

### DocumentKind

| Field | Type | Rule |
|---|---|---|
| `language_id` | string | The editor's identifier for the document kind |
| `extensions` | list of string | Each begins with a dot. Disjoint across servers |

### Capability

The unit the whole feature turns on. Three states and no fourth.

| Field | Type | Rule |
|---|---|---|
| `request` | string | The protocol method, written exactly as the protocol writes it |
| `state` | `"present"`, `"absent_permanent"`, or `"absent_temporary"` | Required |
| `reason` | string | Required when `state` is `absent_permanent`. Forbidden when `present` |
| `instead` | string | Required when `state` is `absent_permanent`. Names what a reader should use to get the answer |
| `tracked` | string | Required when `state` is `absent_temporary`. Names the item that closes it. Forbidden otherwise |
| `editor_specific` | boolean | Default false. True marks glue that cannot move into a server, so a reader knows it is unavailable outside the targeted editor |

**State rules, enforced by the suite in both directions**:

- `present` and the server does not answer the request: fail.
- Either `absent` state and the server answers the request: fail.
- `absent_permanent` without both `reason` and `instead`: fail at load, in both runtimes.
- `absent_temporary` without `tracked`: fail at load.
- A request answered by a server and missing from the list: fail.

**The declaration's own first entry**: the source server carries every model-text request as
`absent_permanent`, with the reason feature 005 records and with `instead` naming the model server.
That entry is what turns today's silence into a fact, and it is written before either server
changes.

### LevelDeclaration

The whole of `levels.json`. Schema in [contracts/levels.schema.json](./contracts/levels.schema.json).

| Field | Type | Rule |
|---|---|---|
| `version` | integer | Format version |
| `register` | string | Where the consumer register that aggregates this lives |
| `libraries` | list of `ResolvedLibrary` | One per library this repository resolves, in either language |

### ResolvedLibrary

| Field | Type | Rule |
|---|---|---|
| `name` | string | The library as it is installed |
| `declared_in` | list of string | Every file that states this level. More than one is allowed; disagreement is not |
| `resolution` | string | How it is acquired: an exact pin, a workspace link, a bundled artifact |
| `level` | string | The exact level. The single value the checks compare against every path in `declared_in` |
| `current` | string | The current published level, as last recorded |
| `standing` | `"current"`, `"behind_deliberate"`, or `"behind_temporary"` | Required |
| `reason` | string | Required unless `standing` is `current` |
| `tracked` | string | Required when `behind_temporary` |

**Rules**:

- `level` disagreeing with any file in `declared_in`: the build refuses to start. This is FR-012,
  and it is a load-time failure rather than a warning.
- `standing` not `current` without a `reason`: fail.
- Changing an entry point, a resolution, or a `declared_in` path without touching this file: fail.
  Changing `level` alone: allowed, and requires nothing here, because this file points at levels
  rather than holding a second copy of them.

## In-memory state

### LibrarySurface (source server)

What replaces the deleted tables. Derived once at startup from the installed library, cached for
the process.

| Field | Type | Meaning |
|---|---|---|
| `document_factories` | frozen set of string | Public callables whose resolved return annotation is the document type |
| `document_carriers` | mapping of string to frozen set of string | Public callables that return a result object holding a document, mapped to the attributes that hold one |
| `type_names` | mapping of string to inferred kind | Public type names, matched after a generic subscript is unwrapped to its origin |
| `source` | `"derived"` or `"fallback"` | Which path produced this |

The two callable sets are separate because they answer different questions, and collapsing them
produces a wrong answer rather than a missing one. A carrier's call yields the result object, not
the document: at `idfkit==1.0.0rc1`, `load_idf_with_diagnostics` returns a `ParseResult` holding a
`document` and its diagnostics. Binding that call to the document kind would offer document members
on an object that has none, which a user cannot tell apart from a real answer. So a carrier's call
infers as `DOCUMENT_CARRIER`, which offers nothing, and reading the attribute the derivation named
is what yields a document.

If derivation yields nothing, the server records the capability as temporarily absent rather than
substituting a written table. A server that cannot tell a document from a string offers nothing,
which is Principle IV applied to itself.

### ModelDocument (model server)

One per open model document, for the life of the document.

| Field | Type | Meaning |
|---|---|---|
| `uri` | string | The editor's identifier |
| `version` | integer | The editor's document version. A stale answer is dropped rather than sent |
| `handle` | service handle | The language service's own state for this text. Edits are applied to it; it is never rebuilt from scratch on a keystroke |
| `encoding` | position encoding | The unit the client negotiated. The only input to translation besides the text |

### PositionTranslation (model server)

Not stored. A pure conversion between the unit the language service states and the unit the client
negotiated, in one module, over one document's text. It is the only arithmetic over model text this
repository performs, it needs no schema and no grammar, and it is recorded in the plan's Complexity
Tracking as the single exception to Principle I.

## What is deliberately not modelled here

- Anything about IDF structure. No object type, no field, no group, no reference list, no token
  kind. Those live in the language service and in the schema, and a type for one of them in this
  repository would be the beginning of the table the constitution forbids.
- Anything about the first language's schema. `SchemaCache` already wraps the library's own schema
  object and adds a lookup index; it holds no field data of its own and gains none here.
