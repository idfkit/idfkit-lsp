# Contract: The Source Server

**Serves**: source files in the first language. **Runtime**: the first language. **Never serves**:
model text.

This server exists and works. This feature changes four things about it and leaves the rest alone.

## Advertised

| Request | State | Change in this feature |
|---|---|---|
| `textDocument/completion` | present | Unchanged behaviour; advertised from the declaration |
| `textDocument/hover` | present | Unchanged behaviour; advertised from the declaration |
| `textDocument/signatureHelp` | present | Unchanged behaviour; advertised from the declaration |
| `workspace/executeCommand` (documentation lookup) | present, editor-specific | Recorded as editor-specific: the server resolves the address, opening it is the editor's act |
| every model-text request | absent, permanent | New entry. Reason and what to use instead, consistent with what feature 005 records |

## The four changes

**1. The pin moves to the release candidate.** Checked: every public name this server imports still
exists there.

**2. Two silent regressions are fixed, and they are why the tables go.** At the adopted level the
document type is generic, so an annotated binding reads as a subscripted name and stops being
inferred; and a new document-producing entry point exists that the written table does not contain.
Neither raises an error. Both stop answers appearing, which no user can tell from having nothing to
say.

**3. The tables are derived, not written.** The set of document-producing callables and the
recognised type names come from the installed library's own resolved annotations, cached at startup,
with a generic subscript unwrapped to its origin. A rename in the library changes this server's
behaviour without anyone editing this server. Where derivation yields nothing, the capability is
recorded as temporarily absent rather than backed by a written table: a server that cannot tell a
document from a string says nothing.

**4. What it advertises comes from the declaration.** Not from a list in `server.py`.

## Unchanged, and deliberately

`SchemaCache` keeps wrapping the library's schema object and keeps holding no field data of its own.
Completion, hover, and signature help keep reading it. None of them acquires a table.

## Retained knowledge, recorded rather than hidden

The analyzer still knows the library's API shape: that a subscript on a document yields a collection,
that adding yields an object. No library publishes that as data, and deriving it would mean writing a
type checker. It is recorded in the plan's Complexity Tracking with a tracked item, and it is not
schema: no object type and no field name appears in that file, and the knowledge check enforces that.
