# Phase 0 Research: Two Servers, One Client, One Capability Story

**Feature**: `001-two-server-editor-support` | **Date**: 2026-09-04

Every decision below was checked against the actual repositories rather than recalled. Where a
fact could not be checked, because the thing does not exist yet, that is said in the decision
rather than hidden in it.

## R1. What the source server runs against

**Decision**: pin `idfkit==1.0.0rc1`.

**Rationale**: the workspace builds `idfkit` at `1.0.0rc1`; the server pins `0.15.0`. That is the
gap this feature's second story exists to make visible, and the plan closes it rather than
recording it. Checked against the release candidate's source, every public name the server imports
still exists: `LATEST_VERSION`, `FieldDescription`, `ObjectDescription`, `get_schema`,
`idfkit.introspection.describe_object_type`, `idfkit.schema.EpJSONSchema`, and
`idfkit.docs.io_reference_url`, along with every `EpJSONSchema` method `SchemaCache` calls
(`object_types`, `get_field_names`, `get_field_schema`, `get_required_fields`, `get_group`).

**Two changes do reach the server, and neither raises an error**:

1. `IDFDocument` is now generic over strictness. `load_idf` returns `IDFDocument[bool]`, and an
   annotated binding now reads `doc: IDFDocument[Literal[True]]`. The analyzer matches annotation
   names against a table and does not unwrap a subscript, so an annotated document stops being
   inferred and completion silently stops appearing on it.
2. `load_idf_with_diagnostics` is a new document-producing entry point. The analyzer's factory
   table does not contain it, so a document obtained that way infers as nothing.

Both are the failure mode the constitution names: a rename or an addition in a library that leaves
the extension importing cleanly and answering less. Neither would fail a test today.

**Alternatives considered**: staying on `0.15.0` and recording the gap as deliberate in the
consumer register. Rejected because there is no reason to record: the release candidate is what
the workspace builds and what the second language is being unified against, and the two silent
regressions above are already present at the current pin's boundary.

## R2. Where the model server's answers come from

**Decision**: the model server depends on `idfkit` and the language service component at exact
pinned versions, and reaches the service through the shared name's subpath rather than through the
component's own package name.

**Rationale**: feature 005 ships the language service as a separately installed component reachable
through the shared name, on the terms the weather component already sets. That pattern is built and
readable in `idfkit-js` today: `packages/idfkit` declares `@idfkit/weather` as an optional peer,
exposes it at the `idfkit/weather` subpath, and guards the subpath with a dynamic import that
translates a missing package into a message naming what to install. Importing the component
directly would work and would throw away that message, which is the one thing a user in this
situation needs.

**Checked, and consequential**: that guard is a top-level `await`, so the facade is ESM and
asynchronous in the module graph, and `require()` of the subpath cannot work. The model server is
therefore ESM and needs a runtime with top-level await. This is a fact about the dependency, not a
choice available here.

**Not yet checkable**: the component does not exist. `idfkit-js` today has `core`, `idfkit`,
`schemas`, `weather`, and two type packages, and nothing matching a language service. Its exact
name and the exact shape of its functions are feature 005's to fix and the naming register's to
record. `contracts/language-service-expected.md` states precisely what this plan assumes of it, so
that the assumption is one document to reconcile rather than a shape spread through handlers.

## R3. Which runtime the model server runs in

**Decision**: bundle the model server in the extension and launch it with the editor's own runtime,
via `process.execPath` with `ELECTRON_RUN_AS_NODE=1`, with a configurable override
(`idfkitLsp.nodePath`) that mirrors the existing `idfkitLsp.pythonPath`. Raise `engines.vscode` to
`^1.86.0`.

**Rationale**: the spec assumes a user of the targeted editor needs no separate runtime install,
and this is the only way to keep that true. The editor already ships a runtime; using it costs a
launch argument. The version floor is not decoration: R2 establishes that the service facade needs
top-level await in an ESM graph, and `^1.86.0` is the first line that guarantees a runtime new
enough for that comfortably. The override exists for the same reason `pythonPath` does, which is a
user whose environment is not the one we guessed.

**Alternatives considered**: requiring a system runtime on the user's path, rejected because it
reintroduces the install step the spec assumes away for extension users; shipping a runtime binary
in the extension, rejected on size and per-platform builds; running the service inside the
extension host, rejected outright by Principle V, since that is logic in the client and it would
exist for nobody outside this editor.

## R4. Removing the knowledge the source server already holds

**Decision**: derive the document-producing callables and the recognised type names from the
installed `idfkit` at startup, by resolving the annotations of its public surface, and cache the
result. Delete `_DOCUMENT_FACTORIES` and `_TYPE_NAMES`.

**Rationale**: these two tables are precisely what Principle I describes, and R1 shows they are
already wrong at the level this plan adopts. Derivation makes a rename or an addition in the
library change the extension's behaviour automatically, which is what "every answer comes from a
library that owns it" means when the answer is about the library itself.

**Mechanics, checked**: `idfkit` ships `py.typed` and uses `from __future__ import annotations`, so
annotations arrive as strings and must be resolved against the defining module's globals rather than
read literally. The public factories carry overloads, so the runtime object is the implementation
and its return annotation is the general one (`IDFDocument[bool]`), which is what makes the origin
test work. Unwrapping a subscript to its origin is the same step R1 requires for annotated
bindings, so one piece of code closes both regressions.

**Alternatives considered**: keeping the tables and recording them as a known deviation in the
capability declaration. Rejected because a table of library names is the exact contribution the
constitution says is worth writing a rule against, and because the derivation is available.

**Residual, and honest about it**: the analyzer still knows the *shape* of the library's Python API,
that a subscript on a document yields a collection and that `add` yields an object. No library
publishes that as data. It stays, it is recorded in Complexity Tracking with a tracked item, and it
is distinct from schema knowledge, which the analyzer does not hold and must not acquire.

## R5. The capability declaration's format

**Decision**: one JSON file at the repository root, read by typed loaders on both sides.

**Rationale**: it is read by the Python suite, the model server, the knowledge check, and the
documentation, in two runtimes, and it must parse with no dependency in either. JSON is the only
format that is free on both sides. Both sides load it into typed objects rather than passing
dictionaries around, per the workspace convention.

**Alternatives considered**: TOML, which reads better for a document carrying prose reasons and
costs a parser dependency in each runtime, and a backport dependency on the oldest Python this
repository supports; YAML, same cost plus ambiguity. Both rejected: two dependencies to make a
governance file prettier is the kind of complexity the constitution asks to be justified, and it
cannot be.

## R6. Where levels are declared, and what checks them

**Decision**: a `levels.json` in this repository naming every library it resolves, where each
level is declared, how it is resolved, and the kind and reason when it is behind. A check
cross-reads the real declarations and fails on any disagreement. The consumer register in the
repository that belongs to neither language points at this file.

**Rationale**: FR-011 and FR-012 require this repository's own checks to reject a shape change made
without a register change, and a check cannot enforce anything about a file in another repository.
Keeping the data here and the aggregation there gives each side something it can actually enforce.

**Alternatives considered**: holding the data only in the register. Rejected because it makes this
repository's checks decorative. Holding it only here, rejected because feature 004's whole point is
one place to ask the question across nine consumers.

## R7. One protocol suite across two runtimes

**Decision**: a single harness at `tests/protocol/`, driven by the existing Python test runner,
that spawns each server as a subprocess over stdio and speaks the protocol to it. Both servers run
in their own runtime; one suite drives both.

**Rationale**: the protocol is transport-agnostic and language-agnostic, which is the entire reason
a harness in one language can prove a server in another. Two suites would be two shapes within a
release. Asserting against the capability declaration in both directions is what makes the
declaration true rather than aspirational.

**Checked, and a defect to fix while passing**: the existing integration harness reads the server's
output with `fcntl` and `select`, so it is POSIX-only and cannot run on a contributor's Windows
machine. The new harness reads with a blocking reader on a thread and works everywhere.

**Alternatives considered**: driving a real editor, rejected by Principle VI; a suite per runtime,
rejected above; testing handlers by direct call rather than over the protocol, rejected because it
proves the handler and not the server.

## R8. Rehearsing a candidate library build

**Decision**: an opt-in switch on the suite that resolves either library from a candidate build,
without changing any declared level and without the candidate being published.

**Rationale**: feature 004's second story requires exactly this of every consumer, and this
repository already has half of it in the automated bump workflow. The switch makes the other half,
the second language's library, work the same way.

## R9. The check that keeps knowledge out

**Decision**: a check run by the pre-commit hooks and by continuous integration, scanning both
source trees for the shapes Principle I forbids: collections of string literals that look like
object types or field names, pattern literals applied to model text, and arithmetic deriving an
element from a text offset outside the one module permitted to do it. A suppression must carry its
reason at the point of suppression.

**Rationale**: FR-025 requires the rejection to happen before review, because the contribution this
guards against is a helpful one and a reviewer's attention is the thing least likely to be there.

**Honest about its limits**: a shape-based check has false positives, and it is scoped to the three
shapes named rather than trying to recognise knowledge in general. The suppression path is what
makes a false positive cost a sentence instead of a fight, and the required reason is what keeps
suppressions countable.

## R10. Position translation, the one piece of arithmetic

**Decision**: one module in the model server converts the unit the language service states into the
unit the protocol requires, honouring the client's declared position encoding where one is offered.
No other file in this repository performs arithmetic over model text.

**Rationale**: feature 005 requires the service to state its unit and to make conversion possible
without knowing that a protocol exists, which places the conversion on this side by construction.
Confining it to one module is what keeps Principle I checkable: the knowledge check can name that
module as the single exception rather than reasoning about intent.

**Alternatives considered**: asking the service for protocol units. Rejected because feature 005
forbids the service naming a protocol's types, and rightly: the day a second protocol appears, the
service would carry both.

## R11. Diagnostics: asked for, not pushed

**Decision**: serve diagnostics on request where the client supports requesting them, and publish
on change only for a client that does not.

**Rationale**: the language service is synchronous and stateless per call. Serving on request needs
no scheduler, no debounce, and no cache invalidation policy; publishing on change needs all three,
and every one of them is machinery this repository would own and the service would not. The
fallback exists because clients differ, and it is the smaller path rather than the default one.

## R12. Keeping the model server's own cost near zero

**Decision**: negotiate incremental document synchronisation, hold one service handle per open
document, and feed edits to the service rather than re-sending whole documents.

**Rationale**: feature 005's budget is an answer within one frame after a single-character edit, and
that budget assumes the service is not asked to start over. This repository can lose that budget
without touching the service, simply by handing it a whole document on every keystroke.

**Dependent on a surface that does not exist yet**: whether the service accepts an edit or only
text is feature 005's to decide. `contracts/language-service-expected.md` records the assumption,
and the fallback, which is to hand over text and let the budget be the service's, is stated there
rather than discovered later.

## R13. What stays in the client, and what it costs

**Decision**: the client keeps server resolution, launch, document-kind declaration, and output
surfacing. The existing documentation command stays and is recorded in the declaration as an
editor-specific limitation.

**Rationale**: checked against the client as it stands, it is already close to the rule. Its
documentation command asks the server for the URL and only opens it, which is the correct split: a
server cannot open a browser, so opening one is editor glue by nature rather than by neglect. Its
interpreter resolution is launch configuration, which Principle V permits by name. Nothing in it
formats hover, filters completion, or interprets diagnostics.
