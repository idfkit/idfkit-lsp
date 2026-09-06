# Quickstart: Validating Two Servers, One Client, One Capability Story

**Feature**: `001-two-server-editor-support` | **Date**: 2026-09-04

Every scenario below runs from the repository root, with no editor installed and none launched. That
is the point of the suite, not an incidental property of it.

## Prerequisites

| Need | Why |
|---|---|
| Python 3.10 or newer, and `uv` | The source server and the protocol suite |
| A runtime for the second language, 18 or newer | The model server. Its facade uses top-level await in an ESM graph |
| `idfkit==1.0.0rc1` | The level this feature adopts. `levels.json` is the authority; the check verifies the pins agree with it |
| The language service component | Scenarios 4 through 6 only. Absent, scenario 7 is what runs instead, and it must pass |

```bash
make install          # both runtimes, both servers, from the declared levels
```

## Scenario 1: The declaration and the servers agree

Delivers user story 1. Runs before either server changes.

```bash
make check-declaration
```

**Expect**: every capability marked present is answered by the server that claims it; every request
either server answers appears in the declaration; every permanent absence carries a reason and what
to use instead; every temporary absence names a tracked item. The run fails and names the
discrepancy when any of those is untrue in either direction.

**Then break it deliberately**: mark one present capability as `absent_permanent` and run again. The
run must fail. A declaration nothing contradicts is a declaration nothing checks.

## Scenario 2: Levels are pinned, declared, and honest

Delivers user story 2.

```bash
make check-levels
```

**Expect**: `levels.json` names every library either server resolves; every path it lists as
declaring a level states the same level; anything not on the current published level carries a
standing and a reason.

**Then break it deliberately**: change the pin in one declared file and not the other. The run must
refuse to start rather than building against one and reporting the other.

## Scenario 3: The source server still answers, at the new level

```bash
make test-protocol ARGS="tests/protocol/test_source_server.py"
```

**Expect**: completion, hover, and signature help answer as before, against `idfkit==1.0.0rc1`.

**The two cases that matter most** are the ones that pass today by accident and would regress
silently: a document bound through an annotation, now that the document type is generic, and a
document obtained from the entry point added in the release candidate. Both must infer. Before the
derived surface lands, both fail; that is the demonstration that the written tables were wrong.

## Scenario 4: A model file is classified

Delivers user story 3.

```bash
make test-protocol ARGS="tests/protocol/test_model_server.py -k classify"
```

**Expect**: the regions returned cover the input exactly, with no gaps and no overlaps, and
concatenating what they select reproduces the input. Run it against a file missing a terminator and
against a file whose version cannot be determined: both classify completely, because the grammar
needs no schema.

## Scenario 5: The other four answers, at the protocol boundary

Delivers user story 4.

```bash
make test-protocol ARGS="tests/protocol/test_model_server.py"
```

**Expect**, in the order they matter:

1. A file with one known bad field yields a diagnostic whose range selects the offending value
   character for character, including when the field is inside an extensible group and when a
   comment sits between the separator and the value.
2. Completion at a choice field offers exactly the schema's list; at a reference field, the names
   declared in the document; at the start of a statement, type names.
3. Completion where the schema constrains nothing returns an empty list marked complete, and never
   a local fallback.
4. Hover on whitespace, a separator, or a comment returns nothing rather than the nearest field.
5. A name declared twice yields both declarations.
6. Text containing characters outside the basic plane still selects the right characters.

## Scenario 6: The budget

```bash
make bench-protocol
```

**Expect**: an answer at a cursor after a single-character edit returns inside one frame at 60 hertz,
measured at the protocol boundary. This measures this repository's share, which is transport and
translation. The answer's own cost is the language service's budget and is measured there.

## Scenario 7: The component is absent, and says so

```bash
make test-protocol ARGS="tests/protocol/test_model_server.py -k missing_component"
```

**Expect**: startup reports what to install, in the guard's own words. The source server continues to
serve source files with nothing degraded. This scenario must pass whether or not the component is
installed, because it is about the path where it is not.

## Scenario 8: Knowledge cannot get in

Delivers user story 6.

```bash
make check-knowledge
```

**Expect**: a clean tree passes. Then add, one at a time, a list of field-name literals, a pattern
literal applied to model text, and a function deriving a field from an offset outside the one module
permitted to do it. Each must be rejected by the check, not by a reader. Suppressing the check
without a reason at the point of suppression must also fail.

## Scenario 9: A second editor costs a wrapper

Delivers user story 7.

```bash
make test-protocol            # the whole suite, no client present anywhere
```

**Expect**: every capability marked present in the declaration is answered while none of this
repository's client code is loaded. What remains reachable only through the client is exactly the
set marked `editor_specific`, and that set is readable in one place.

## Scenario 10: Rehearsing a candidate library

Delivers feature 004's second story for this consumer.

```bash
make test-protocol CANDIDATE_FIRST=/path/to/candidate/wheel
make test-protocol CANDIDATE_SECOND=/path/to/candidate/package
```

**Expect**: both servers build and answer against the candidate without any declared level changing
and without the candidate being published. With no candidate given, the run says so plainly rather
than quietly testing the declared level and reporting a pass.

## The whole gate

```bash
make check && make test
```

Runs lint, format, type checking, unit tests, the protocol suite across both servers, and the three
checks above. This is what a change is held to.
