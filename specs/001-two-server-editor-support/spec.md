# Feature Specification: Two Servers, One Client, One Capability Story

**Feature Branch**: `001-two-server-editor-support`

**Created**: 2026-09-04

**Status**: Draft

**Input**: User description: "specify what the constitution says this repo should be (a language server for both *.py files that use idfkit and for *.idf syntax highlight). Note that the *.idf syntax highlight work will land in ../idfkit-js (that work is being spec'd at ../idfkit-unification/specs/005-idf-language-service)"

## Overview

This repository ships editor support for two different things: source code in the first language, and model text. It owns protocol, not knowledge. Today it ships one of those two things, holds no statement of that fact, and pins a library level nothing describes.

The gap is not that model text is unsupported. It is that nothing anywhere says so. A modeller installs an extension called "idfkit Language Support", opens a model file, which is the file the whole project exists to read, and gets nothing at all: no colour, no completion, no explanation of a field, no underline on a bad value. Nothing in the extension, the marketplace listing, or the repository tells them whether that is a decision, a defect, or a missing install. The same silence covers the level: the server pins an exact library level, that level is three minor versions and a major release candidate behind what the workspace builds, and no file records whether that is deliberate.

The material for the missing half is being built elsewhere and on purpose. Feature 005 of the unification puts every answer about model text into the second language's library as a callable service: classification of the whole text, findings that carry the region they are about, what may go at an offset, what the schema says about the element under an offset, and where a name is declared. That feature records the first language's absence of the same service as permanent, with the reason, and names this extension as what a reader installs instead. So the work here is not to answer any of those five questions. It is to carry them: a second server, written in the second language, that this repository's client launches for model text, next to the first server it already launches for source code.

**Vocabulary**. Following the unification's features 001 through 005, *the first language* is the one that installs with `pip` and *the second language* the one that installs with `npm`. *The language service* is the library feature 005 delivers in the second language, and *the five answers* are what it returns. *The source server* is the server this repository already ships, which serves source files in the first language. *The model server* is the second server this feature adds, which serves model text. *The capability declaration* is the single file this feature adds recording what each server advertises. *The consumer register* is the artifact feature 004 defines, in the repository that belongs to neither language.

**In scope**: the capability declaration and the honest statement of every absence in it; this repository's entry in the consumer register and the pinned levels it points at; the model server and the client wiring that launches it; the protocol-level test suite that covers both servers with no editor in the loop; the removal of any knowledge this repository holds that a library owns; and keeping the client to wiring.

**Out of scope**: the five answers themselves and the syntax layer beneath them, which are feature 005 in the second language's repository and which this feature consumes and never negotiates; a counterpart language service in the first language, which feature 005 records as permanently absent; the source server's existing analysis of first-language source, which changes only where it holds knowledge a library owns; any editor other than the one this repository already targets, except that Principle V exists so that adding one later is cheap; and the visual editor's own text surface, which is a sibling consumer of the same service rather than anything this repository serves.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - The repository says what it serves, and what it does not (Priority: P1)

A modeller installs the extension, opens a model file, and gets nothing. A maintainer is asked whether hover works in model files. A documentation writer needs to say what the extension does. All three are asking the same question and there is nowhere to look. After this story there is exactly one place that answers it: a declaration naming each server, the documents it serves, and every request it advertises, with each absence marked as permanent or temporary and each permanent absence carrying its reason and what a reader should do instead.

**Why this priority**: it delivers before either server changes, applied to the repository exactly as it stands, and it is the only story that turns today's silence into a fact a user can read. It is also what every later story is measured against, because the capability declaration is what the protocol tests assert and what the documentation renders.

**Independent Test**: Read the declaration with no code changed. It names the source server, the documents it serves, and every request it answers today. It names the model server as not yet present, and it states that a reader who installs with `pip` alone gets no answers about model text, that this is permanent rather than an oversight, and what to install instead.

**Acceptance Scenarios**:

1. **Given** the repository as it stands, **When** a reader consults the capability declaration, **Then** every request either server advertises appears with the document kinds it applies to, and nothing advertised is missing from it.
2. **Given** a capability that exists for source files and not for model text, or the reverse, **When** the declaration is read, **Then** the asymmetry is stated explicitly rather than inferred from an absence.
3. **Given** an absence recorded in the declaration, **When** it is read, **Then** it is marked permanent or temporary on the same two kinds the parity record already uses, a permanent one gives its reason and names what a reader installs instead, and a temporary one names a tracked item.
4. **Given** a change that adds, removes, or narrows an advertised capability, **When** it is proposed without a matching change to the declaration, **Then** this repository's own checks reject it.
5. **Given** the extension's own user-facing description, **When** it is read, **Then** it agrees with the declaration about what is served, so a marketplace listing cannot promise what the declaration withholds.

---

### User Story 2 - Every level this repository resolves is pinned and declared (Priority: P1)

A maintainer asks which library level this repository runs on and whether that is the current one. Today the answer is an exact pin in one file and nothing else anywhere, and the pin is behind. After this story the level is pinned, the pin is pointed at from the consumer register, and being behind is a decision with a reason rather than a number nobody has looked at.

**Why this priority**: it delivers immediately, it costs one entry, and it is the story that makes every other one safe, because a second server that resolves a second library doubles the number of levels this repository can be silently wrong about. Applied today it already exposes a pin well behind its siblings with nothing saying why.

**Independent Test**: Read the consumer register with no code changed. This repository appears once for each library it resolves, each entry points at where that level is declared and says how it is resolved, and each level not on the current published level carries a kind and a reason. Then move where a level is declared without touching the register, and this repository's checks fail.

**Acceptance Scenarios**:

1. **Given** the consumer register, **When** it is read, **Then** this repository appears with an entry for every library it resolves, including the second language's library once the model server exists, and including anything a delivery path acquires on the user's behalf.
2. **Given** a declared level behind the current published level, **When** the register is read, **Then** it says whether that is temporary or deliberate, and a temporary one names a tracked item.
3. **Given** a change to this repository's entry point, to how it resolves a library, or to where a level is declared, **When** it is proposed without a register change, **Then** this repository's own checks reject it. A change to the level alone needs no register change.
4. **Given** a level declared in more than one place, **When** those places disagree, **Then** the build refuses to start rather than building against one and reporting the other.
5. **Given** any path by which either server reaches a user, **When** that path is installed twice with a library release published in between, **Then** both installs run the same declared level, and asking either server what it runs returns a version.

---

### User Story 3 - A modeller's model file stops being grey (Priority: P1)

A modeller opens a model file in their editor and sees structure: type names one way, values another, comments a third, separators a fourth. Every region comes from the language service classifying the text, and this repository translates those regions into what the protocol calls for and nothing else. It holds no grammar pattern of its own, so a file that does not parse still colours, because the service classifies it anyway.

**Why this priority**: it is the smallest slice of model support that ships on its own and the one a user notices within a second of opening a file. It is also the slice that proves the model server exists and that the client can run two servers, which every later model-text answer then rides on for free.

**Independent Test**: Open a model file and every character is classified. Send the same text to the model server at the protocol boundary with no editor running and the regions returned cover the text exactly, with no gaps and no overlaps, and match what the language service returned for the same text. Do it for a file missing a terminator and get a complete classification anyway.

**Acceptance Scenarios**:

1. **Given** a model file, **When** it is opened, **Then** the model server starts for it and the source server does not, and opening a source file starts the source server and not the model server.
2. **Given** text sent to the model server, **When** classification is requested, **Then** the regions returned are the ones the language service produced, translated into protocol units and reordered if the protocol requires it, with no region added, dropped, merged, or reclassified.
3. **Given** text that does not parse, **When** it is classified, **Then** a complete classification is still returned, because the file somebody is typing is the normal case.
4. **Given** a document the user has not saved, **When** any request is made about it, **Then** the server passes text to the service and never a path.
5. **Given** no schema can be determined for the text, **When** classification is requested, **Then** it still succeeds, because the grammar needs no schema.
6. **Given** the language service is not present in the environment, **When** a model file is opened, **Then** the client says so plainly, naming what to install, and the source server is unaffected.

---

### User Story 4 - The other four answers reach the editor (Priority: P2)

The modeller now wants the rest: a bad value underlined where the bad value is, a list of what may go after the comma they just typed, an explanation of the field under the cursor in the schema's own words, and a jump from a name to the object that declares it. All four exist in the language service. This repository turns each into its protocol request and back, converting a position from the unit the service states into the unit the protocol demands, and nothing more.

**Why this priority**: it is the substance of model support, and it is below classification only because classification ships alone and these depend on the same server existing. Within this story, findings come before completion, because a finding tells a modeller they have a problem and completion only helps them avoid one.

**Independent Test**: At the protocol boundary with no editor, send a file with one known bad field and receive a diagnostic whose range selects the offending value character for character. Ask for completion at a known field and receive exactly what the schema permits there. Ask for hover on a field and receive the schema's own words. Ask where a name is declared and receive the declaring object's name region.

**Acceptance Scenarios**:

1. **Given** a finding the language service produces, **When** it is delivered as a diagnostic, **Then** its range selects what the service positioned it on, its message is the service's message unchanged, and its severity is the service's severity unchanged.
2. **Given** findings from both reading and validating, **When** they are delivered, **Then** a consumer sees both on the same terms and this repository does not filter, reword, re-severity, or add to them.
3. **Given** an offset where the schema constrains nothing, **When** completion is requested, **Then** the server returns an empty result flagged as complete rather than inventing entries, and does not fall back to any local list.
4. **Given** an offset on whitespace, a separator, or a comment, **When** hover is requested, **Then** nothing is returned rather than the nearest field.
5. **Given** a name declared by more than one object, **When** a declaration is requested, **Then** every declaration is returned rather than one chosen here.
6. **Given** a position measured in the unit the service states, **When** it is delivered over the protocol, **Then** it is converted to the unit the protocol requires, and text outside the basic plane lands on the right characters.
7. **Given** the service reports that an answer cannot be produced because no schema is available, **When** the request is served, **Then** the client is told that plainly and is not sent an empty result that reads as "nothing is permitted here".

---

### User Story 5 - Both servers are proved without an editor (Priority: P2)

A maintainer changes a handler and wants to know whether it still works. Today that means launching an editor and looking. After this story it means running the suite: protocol requests in, responses out, both servers covered the same way, in continuous integration on every change.

**Why this priority**: it is what makes every other story checkable rather than demonstrable, and it is the mechanical half of the review the constitution requires. It sits below the model server because there must be two servers before a suite can cover two servers the same way, and it is not lower because a capability declaration nothing asserts against drifts from the servers it describes within one release.

**Independent Test**: With no editor installed anywhere on the machine, run the suite. Both servers start, answer, and shut down, every advertised request is exercised, and a capability advertised in the declaration but absent from the server fails the run.

**Acceptance Scenarios**:

1. **Given** the suite, **When** it runs, **Then** it exercises every request the capability declaration advertises, for both servers, with no editor process involved.
2. **Given** a capability in the declaration with no corresponding server behaviour, or a server behaviour absent from the declaration, **When** the suite runs, **Then** it fails and names the discrepancy.
3. **Given** a run in continuous integration, **When** it completes, **Then** it has covered both servers, on every supported runtime version this repository claims.
4. **Given** an answer that a server can only demonstrate by opening an editor, **When** it is proposed, **Then** it is treated as untested and rejected in review.
5. **Given** a change to the language service's output, **When** the suite runs against a candidate build of it, **Then** the failures name this repository's handlers rather than surfacing as an editor that quietly stopped answering.

---

### User Story 6 - Knowledge cannot get in (Priority: P2)

A contributor fixes a real gap the fast way: a small dictionary of field names, a regular expression that spots a type name, a helper that counts commas to find which field an offset is in. Every one of those is correct on the day it lands and wrong at the next library release, and nothing in an editor tells a user which. After this story a check refuses them, and the check runs before review rather than depending on a reviewer recognising the shape.

**Why this priority**: it is the constitution's first principle and the failure mode most likely to arrive as a helpful contribution rather than a bad one. It is at P2 because the servers deliver value without it and it protects value they already deliver, and it is not lower because the model server multiplies the temptation: position arithmetic over model text is exactly the code somebody will be tempted to write here rather than ask the service for.

**Independent Test**: Add a dictionary of field names, a grammar pattern, and a function that computes a field index from an offset, each in a separate change, and each is rejected by a check rather than by a reader. Then audit the repository as it stands and find zero of the three already present.

**Acceptance Scenarios**:

1. **Given** a change introducing a literal list of object types, field names, or model-text tokens, **When** checks run, **Then** they fail and name the file.
2. **Given** a change introducing a grammar pattern over model text, or arithmetic that derives a field from an offset, **When** checks run, **Then** they fail.
3. **Given** the repository as it stands, **When** it is audited against the same rule, **Then** it holds no such knowledge, or every instance found is recorded with what will remove it.
4. **Given** an answer this repository cannot get from a library, **When** a handler is written for it, **Then** the handler returns nothing and the absence is recorded in the capability declaration, rather than the handler producing a locally assembled answer.
5. **Given** a check that must be suppressed for a legitimate reason, **When** it is suppressed, **Then** the suppression names the reason at the point of suppression, so an exception is visible rather than silent.

---

### User Story 7 - A second editor costs a wrapper, not a port (Priority: P3)

Someone wants these answers in an editor that is not the one this repository targets. They should need a launch configuration and nothing else, because everything a user sees is produced by a server that speaks a protocol any editor speaks.

**Why this priority**: it delivers to nobody on the day it lands and it determines what the other six stories are worth to everyone outside one editor. It is at P3 because the constitution already forbids the client from growing logic, so this story is the audit and the guard rather than a build.

**Independent Test**: Read the client. It locates and starts each server, declares which documents each serves, surfaces server output, and does nothing else. Then take the two servers alone, drive them from a plain protocol client, and every capability the declaration advertises is available with no part of this repository's client present.

**Acceptance Scenarios**:

1. **Given** the client, **When** it is read, **Then** it contains no schema knowledge, no grammar knowledge, no completion filtering, no hover formatting, and no diagnostic interpretation.
2. **Given** both servers driven without the client, **When** every advertised capability is requested, **Then** each is answered, so nothing a user depends on lives in the client.
3. **Given** editor-specific glue that genuinely cannot move into a server, **When** it is added, **Then** it is recorded in the capability declaration as an editor-specific limitation.
4. **Given** a change that adds logic to the client, **When** it is proposed, **Then** review rejects it and names the server the logic belongs in.

---

### Edge Cases

- A model file is open and the second language's runtime or the language service is absent. Nothing about the source server may degrade, and the modeller must be told what is missing and what to install rather than watching an extension fail quietly.
- A single file is open that is both, meaning a source file that embeds model text in a string. Only the source server serves it, and the declaration says so.
- Both servers are running and both want to report a problem about the same workspace. Each reports only about the documents it serves, so a user never sees two servers disagree about one file.
- A model file is very large, or is being typed into rapidly. Answers ride the service's own budget, and this repository must not add a cost of its own by re-sending whole documents where the protocol offers increments.
- The language service reports that it cannot answer because no schema is available for the declared version, or because the version cannot be determined. That is a different outcome from having nothing to offer, and the two must not arrive at the editor looking the same.
- A position lands on text outside the basic multilingual plane, where the unit the service states and the unit the protocol demands disagree. Every answer that carries a position is affected, not just the ones with obvious text in them.
- A user has the extension from the marketplace and a differently pinned library in their environment, so what the extension declares and what actually resolves disagree. Each server must be able to say what it is running.
- One server crashes. The other keeps serving, and the user is told which one stopped.
- The user's editor has another extension already claiming model files. The capability declaration is what says which requests this one answers, and a conflict must be visible rather than a race.
- A request arrives for a document neither server serves. It is answered as unsupported rather than by the nearer server guessing.

## Requirements *(mandatory)*

### Functional Requirements

**The capability declaration**

- **FR-001**: The repository MUST hold exactly one declaration recording, for each server, the document kinds it serves and every protocol request it advertises.
- **FR-002**: The declaration MUST record every capability that is present for one document kind and absent for the other, as an explicit asymmetry rather than as an omission.
- **FR-003**: Each absence in the declaration MUST be marked permanent or temporary. A permanent absence MUST give its reason and name what a reader should use instead. A temporary absence MUST name a tracked item.
- **FR-004**: The declaration MUST record, as a permanent absence with its reason, that installing with `pip` alone yields no answers about model text, and MUST name what a reader installs instead, consistent with the parity record entry feature 005 creates.
- **FR-005**: A change that adds, removes, or narrows an advertised capability MUST fail this repository's checks unless the declaration changes with it.
- **FR-006**: Every user-facing description this repository publishes, including its extension manifest and its readme, MUST agree with the declaration about what is served.
- **FR-007**: The declaration MUST be the source the protocol test suite asserts against, so that it cannot describe a server that does not behave that way.

**Levels and delivery**

- **FR-008**: Every library this repository resolves MUST be pinned to an exact level, in both languages.
- **FR-009**: This repository MUST appear in the consumer register with an entry for each library it resolves, each naming where that level is declared and how it is resolved.
- **FR-010**: Where a declared level is behind the current published level, the register entry MUST carry a kind and a reason, and a temporary one MUST name a tracked item.
- **FR-011**: A change to this repository's entry point, to how it resolves a library, or to where a level is declared MUST fail this repository's checks unless the register changes with it. A change to a level's value alone MUST NOT require a register change.
- **FR-012**: Where a level is declared in more than one place, the build MUST refuse to start when they disagree.
- **FR-013**: Every delivery path by which either server reaches a user MUST name the level it delivers, and a rebuild or a reinstall alone MUST NOT change it.
- **FR-014**: Each server MUST be able to report, on request, its own version and the level of each library it resolved.

**The model server**

- **FR-015**: A second server, running in the second language's runtime, MUST serve model text, and MUST obtain every answer from the language service feature 005 delivers.
- **FR-016**: The model server MUST advertise classification of the whole text, findings with positions, completion at a position, explanation at a position, and the declaration a name resolves to, subject to what the language service provides and to what the declaration records.
- **FR-017**: The model server MUST NOT analyse source files in the first language, and the source server MUST NOT analyse model text.
- **FR-018**: The model server MUST pass document text to the language service and MUST NOT pass a path, so that unsaved documents are served on the same terms as saved ones.
- **FR-019**: The model server MUST convert positions from the unit the language service states into the unit the protocol requires, and MUST do so correctly for text outside the basic multilingual plane.
- **FR-020**: The model server MUST deliver findings exactly as the language service produces them, adding a position translation and nothing else. It MUST NOT filter, reword, re-severity, merge, or add findings.
- **FR-021**: The model server MUST distinguish "the schema permits nothing here", "the schema constrains nothing here", and "no answer can be produced because no schema is available", and MUST NOT deliver all three as an empty result.
- **FR-022**: The model server MUST answer for text that does not parse, and MUST NOT fail on it, since a file being typed is the normal case.
- **FR-023**: Where the language service or the second language's runtime is absent, the client MUST report that plainly, naming what to install, and the source server MUST continue to serve source files unaffected.

**Knowledge**

- **FR-024**: This repository MUST NOT contain a schema table, a literal list of object types or field names, a grammar pattern over model text, or arithmetic deriving a field or an element from a text offset.
- **FR-025**: A check MUST reject a change introducing anything FR-024 forbids, before review rather than during it, and any suppression of that check MUST state its reason at the point of suppression.
- **FR-026**: Where a library cannot answer, the server MUST return an empty or absent result and MUST NOT synthesise one from a heuristic, a name pattern, a cached fragment, or a previous document state.
- **FR-027**: The existing source server MUST be audited against FR-024, and every instance found MUST either be removed or recorded with what will remove it.

**The client**

- **FR-028**: The client MUST contain only server location, server launch, document-kind declaration, and output surfacing.
- **FR-029**: The client MUST NOT contain completion filtering, hover formatting, diagnostic interpretation, schema knowledge, or grammar knowledge.
- **FR-030**: The client MUST launch each server independently, so that the absence or failure of one leaves the other serving, and MUST tell the user which server stopped.
- **FR-031**: Every advertised capability MUST be reachable by driving the servers alone, with no part of this repository's client present.
- **FR-032**: Editor-specific glue that cannot be moved into a server MUST be recorded in the declaration as an editor-specific limitation.

**Testing**

- **FR-033**: Every advertised capability MUST be exercised by a suite that sends protocol requests and reads protocol responses, with no editor process involved.
- **FR-034**: The suite MUST cover both servers on the same terms and MUST run in continuous integration on every change, across every runtime version this repository claims to support.
- **FR-035**: The suite MUST fail when the capability declaration and the servers disagree in either direction.
- **FR-036**: A behaviour that can only be demonstrated by opening an editor MUST be treated as untested.
- **FR-037**: It MUST be possible to run the suite against a candidate build of either library, without changing the level this repository declares and without that build being published.

### Key Entities

- **Source server**: the server that serves source files in the first language. Exists today.
- **Model server**: the server that serves model text, running in the second language's runtime and wrapping the language service. Added by this feature.
- **Capability declaration**: the single record of which server serves which document kinds and which requests each advertises, including every absence with its kind and reason. The thing the tests assert against and the documentation renders.
- **Consumer register entry**: this repository's row in the artifact feature 004 defines, naming each library it resolves, where each level is declared, how it is resolved, and why it is behind if it is.
- **Advertised capability**: one protocol request, for one document kind, that a server answers. It is either present, permanently absent with a reason, or temporarily absent with a tracked item; there is no fourth state and no unstated one.
- **Position translation**: the conversion between the unit the language service states and the unit the protocol requires. The only arithmetic this repository is permitted to perform over model text, and only because the protocol demands a unit the service does not speak.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: 100% of requests either server answers appear in the capability declaration, and 100% of entries in the declaration are answered by a server, verified mechanically rather than by reading.
- **SC-002**: Every absence in the declaration carries a kind, and 100% of permanent absences name both a reason and what to use instead.
- **SC-003**: A maintainer can answer "which library levels does this repository run on, and is any of them behind on purpose" from one place, in under a minute, with no file search.
- **SC-004**: Installing any delivery path twice, with a library release published in between, yields the same declared level 100% of the time, and both servers answer a version query.
- **SC-005**: A modeller opening a model file sees every character classified, including in a file that does not parse, for 100% of a corpus of model files.
- **SC-006**: For 100% of a sample of field-level findings, the range delivered to the editor selects the offending value character for character, including inside extensible groups and across comments, matching what the language service positioned.
- **SC-007**: The values offered at a position match what the schema permits there exactly, compared against the schema rather than against any list held in this repository, for every sampled position.
- **SC-008**: This repository contains zero schema tables, zero literal object-type or field-name lists, zero grammar patterns over model text, and zero offset-to-field arithmetic beyond the declared position translation, enforced by a check rather than a review.
- **SC-009**: 100% of advertised capabilities are exercised by the protocol suite with no editor installed, and the suite runs on every change.
- **SC-010**: Every advertised capability is reachable driving the servers alone, so a user in a different editor loses 0% of what a user in the targeted editor gets, excluding limitations explicitly recorded as editor-specific.
- **SC-011**: When the language service or the second language's runtime is absent, 100% of users opening a model file get a message naming what to install, and 0% of source-file capabilities are affected.
- **SC-012**: This repository adds no more than a negligible cost on top of the language service's own budget for an answer at a cursor, so that a modeller typing in a model file sees answers within one frame at 60 hertz, measured at the protocol boundary rather than in the editor.

## Assumptions

- Feature 005 of the unification ships the language service in the second language, as a separately installed component, exposing the five answers as synchronous functions over text and schema with no protocol knowledge. This feature consumes that surface and does not shape it. Until it ships, stories 1, 2, 6, and 7 deliver on their own and stories 3, 4, and 5 are partly blocked on it.
- Feature 004 of the unification defines the consumer register and the two kinds an absence may take. This feature writes an entry into it rather than inventing a register here.
- "Syntax highlighting" for model text is delivered as classification served by the model server, not as a grammar file in this repository, because the constitution forbids grammar patterns here. The consequence, which is that model text is uncoloured while the model server is unavailable, is recorded in the declaration rather than worked around.
- The model server ships inside the same extension the client already ships, and runs on the runtime the editor already provides, so a user of the targeted editor needs no separate runtime install. A user driving the servers from another editor supplies that runtime themselves, which is the cost feature 005 records.
- This repository contributes the model-text document kind to the editor, meaning the association between file extension and document kind, since no other component in the workspace does.
- The source server continues to serve source files in the first language from the first language's runtime, resolved from the user's own environment as it is today. Nothing in this feature changes how it is installed.
- The current pin is behind the workspace's own library, and the register entry will record which kind that is. This feature requires the reason to exist; it does not decide whether to move the pin, which is the register's business and the maintainer's call.
- "Both servers covered the same way" means the same suite and the same shape of test, not one runtime. Each server is exercised in the runtime it runs in.
