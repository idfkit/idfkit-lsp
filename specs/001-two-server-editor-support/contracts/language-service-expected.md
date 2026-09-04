# Dependency Contract: What the Model Server Needs From the Language Service

**Status**: assumption, recorded so it is one document to reconcile rather than a shape spread
through handlers.

The language service does not exist yet. Feature 005 of the unification specifies it and is Draft.
`idfkit-js` today holds `core`, `idfkit`, `schemas`, `weather`, and two type packages, and nothing
matching a language service. This file states exactly what this plan assumes of it. When feature 005
lands, this file is checked against the naming register and the handlers follow it; nothing else in
this repository should need to change, which is the point of writing it down.

## How it is reached

Through the shared name's subpath, not through the component's own package name. The weather
component sets the pattern and it is built today: the shared-name package declares the component as
an optional peer, exposes it at a subpath, and guards that subpath with a dynamic import that turns
a missing package into a message naming what to install.

**What this repository does**: import the subpath, catch the guard's error at startup, and report it
to the user unchanged. It already names what to install; rewording it would make it worse.

**Consequences that are facts rather than choices**: the facade uses top-level await, so it is ESM
and the model server is ESM. A synchronous require of the subpath cannot work. The runtime floor
follows from this, not from taste.

**Not yet fixed**: the component's exact name. Derived from the weather pattern it will be the
shared name plus a subpath, with a scoped package behind it. The naming register is what settles it.

## What is called

Five answers, each a pure function of text and schema, each synchronous, each performing no input or
output. Feature 005 requires all of that, so this repository never awaits an answer and never holds
a thread waiting for one.

| Answer | Given | Returned | This repository translates it into |
|---|---|---|---|
| Classify | text | regions covering the text exactly, each with a kind | semantic tokens |
| Findings | text, schema | the findings reading and validating already produce, each carrying a region | diagnostics |
| Complete | text, schema, offset | what the schema permits at that offset, each with enough to display | completion items |
| Explain | text, schema, offset | what the schema says about the element under the offset | hover |
| Declaration | text, schema, offset | the regions where the name under the offset is declared, possibly several | definition locations |

## What is assumed about positions

- A region is a start and an end as absolute offsets into the text.
- The service states the unit its offsets are measured in, and does not know what unit a protocol
  wants. Conversion is this repository's job and lives in exactly one module.
- Positions are correct for either line-ending convention and for text mixing them.

## What is assumed about absence

The service distinguishes three outcomes and this repository must carry all three to the editor
without flattening them:

1. The schema permits nothing here.
2. The schema constrains nothing here, so there is nothing to offer.
3. No answer can be produced, because no schema is available for the declared version, or the
   version cannot be determined.

The third is not an empty list. An editor shown an empty list reads it as the first, which is a lie
this repository would be telling on the service's behalf.

## What is assumed about incremental work

**Preferred**: the service accepts an edit against a handle it already holds for a document, so a
single-character change does not re-read the whole text. Feature 005's budget assumes this.

**Fallback, if it accepts only text**: this repository hands over the current text on each request
and the budget is the service's. The fallback is recorded here rather than discovered during
implementation, and the choice between the two changes one module, `documents.ts`, and nothing else.

## What this repository will never ask of it

- To know that a protocol exists, or to return a protocol's types.
- To take a path. It takes text, so an unsaved document is served on the same terms as a saved one.
- To produce, filter, reword, or re-severity a finding. This repository delivers what the service
  produced, with a position translated and nothing else added.
- To supply prose this repository could paraphrase. Where the schema carries no prose, the absence
  is reported, not filled in.
