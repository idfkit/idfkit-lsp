# Contract: The Model Server

**Serves**: model text. **Runtime**: the second language, on the editor's own runtime. **Never
serves**: source files in the first language.

## Advertised

Read from `capabilities.json` at startup rather than written inline, so that what the server tells
the editor and what the repository tells a reader cannot diverge. The protocol suite asserts the two
against each other in both directions.

| Request | State at completion of this feature | Notes |
|---|---|---|
| `textDocument/semanticTokens/full` | present | User story 3. Classification, delivered as tokens |
| `textDocument/diagnostic` | present | Served on request. See below |
| `textDocument/publishDiagnostics` | present | Fallback only, for a client that cannot request |
| `textDocument/completion` | present | User story 4 |
| `textDocument/hover` | present | User story 4 |
| `textDocument/definition` | present | User story 4. Returns every declaration when a name is declared more than once |
| everything else | absent, with a kind and a reason | No request is implicitly absent |

## Behaviour the suite pins

1. **Ownership**. Opening a model document starts this server and not the source server. Opening a
   source document does the reverse. A request for a document this server does not serve is answered
   as unsupported, never by guessing.
2. **Text, never a path**. Every call to the service carries the document's current text. An unsaved
   document is served identically to a saved one.
3. **Classification is total**. Regions cover the text with no gaps and no overlaps, for text that
   does not parse and for text with no determinable version, and match what the service returned.
   Nothing is added, dropped, merged, or reclassified here.
4. **Findings pass through**. Message, severity, and code are the service's, unchanged. The range is
   the service's region, translated. No finding is produced here.
5. **Three absences stay three**. "Permits nothing", "constrains nothing", and "cannot answer, no
   schema" reach the client distinguishably. An empty completion list is returned as complete, never
   as a fallback to a local list, of which there is none.
6. **Stale answers are dropped**. An answer computed against a document version the editor has since
   superseded is discarded rather than sent.
7. **Positions round-trip**. For text containing characters outside the basic plane, a range
   delivered to the client selects the same characters the service selected. This is the one
   assertion that would pass by accident on ASCII, so the suite uses text that does not.
8. **The component's absence is a message, not a crash**. When the language service is not installed,
   startup reports what to install, using the guard's own words, and the source server is unaffected.

## Diagnostics: on request

Served in response to a request where the client advertises it can request, and published on change
only for a client that cannot. Serving on request needs no debounce, no scheduler, and no cache
invalidation policy. Every one of those would be machinery this repository owns and the language
service does not, and Principle I is easier to keep when there is less here to keep it in.

## Forbidden here, and checked

No object type, field name, grammar pattern, or token table. No arithmetic over model text outside
`positions.ts`. No answer assembled locally when the service declines to give one.
