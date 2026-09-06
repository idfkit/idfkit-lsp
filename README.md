# idfkit Language Support

Editor support for two different things: Python source that uses the
[idfkit](https://github.com/idfkit/idfkit) library, and EnergyPlus model text.

Two servers do the work and one thin client starts them. The Python server answers questions about
Python source. A second server, on the editor's own Node runtime, answers questions about model
text. Neither reimplements any part of the other, and neither holds knowledge of its own: every
answer comes from a library that owns the question.

## What is served, and what is not

The block below is generated from [`capabilities.json`](./capabilities.json), which is the single
record of what each server advertises. Both servers advertise from that file, the client reads it
for its document selectors, and the test suite asserts it against the servers in both directions. A
capability the declaration does not carry cannot be advertised, and a request a server answers that
the declaration does not list fails the build.

Regenerate this block with `make check-declaration` after a change, or check it in CI, which is
where a readme that has drifted from the servers is caught.

<!-- capabilities:begin -->

### The source server

Runtime: Python 3.10 through 3.13, pygls over stdio. Serves `python` (`.py`, `.pyi`).

| Request | State | Note |
| --- | --- | --- |
| `textDocument/completion` | present |   |
| `textDocument/hover` | present |   |
| `textDocument/signatureHelp` | present |   |
| `workspace/executeCommand` | present, editor-specific |   |
| `idfkit-lsp/versions` | present |   |
| `textDocument/semanticTokens/full` | absent, permanent | This server reads Python source. Classifying model text needs the IDF syntax layer, which lives in the language service and is reached from the second language, not from here. Installing this server with pip alone therefore yields no answers about model text, and no amount of work here would change that. Instead: The model server, which serves model text and is bundled in the editor extension. |
| `textDocument/diagnostic` | absent, permanent | Findings about model text are produced by reading and validating a model, which is the language service's work. This server holds no grammar and no schema table and must not acquire one. Instead: The model server, which serves model text and is bundled in the editor extension. |
| `textDocument/publishDiagnostics` | absent, permanent | This server has no findings to publish about model text, for the same reason it answers no diagnostic request about it. Instead: The model server, which serves model text and is bundled in the editor extension. |
| `textDocument/definition` | absent, permanent | Where a name is declared in model text is a question about the model's reference graph, answered by the language service. This server answers questions about Python source. Instead: The model server, which serves model text and is bundled in the editor extension. |

### The model server

Runtime: Node 18 or newer, ESM, launched on the editor's own runtime. Serves `idf` (`.idf`).

| Request | State | Note |
| --- | --- | --- |
| `idfkit-lsp/versions` | present |   |
| `textDocument/semanticTokens/full` | present |   |
| `textDocument/diagnostic` | present |   |
| `textDocument/publishDiagnostics` | present |   |
| `textDocument/completion` | present |   |
| `textDocument/hover` | present |   |
| `textDocument/definition` | present |   |
| `textDocument/signatureHelp` | absent, permanent | Signature help describes a call in a programming language. Model text has no calls, so there is no signature to help with. Instead: Hover on a field, once the language service ships, reports what the schema says about it. |
| `workspace/executeCommand` | absent, permanent | The one command this repository exposes resolves a documentation address for a Python object type, which is the source server's question. This server has no command of its own and adding one would be logic that exists for one editor. Instead: The source server, which answers workspace/executeCommand for the documentation lookup. |

<!-- capabilities:end -->

### Reading the three states

- **present**: the server answers the request today.
- **absent, permanent**: the server will never answer it, with the reason and what to use instead.
  Installing the source server with `pip` alone yields no answers about model text, and no amount
  of work on that server would change that: the model text answers live in the language service and
  are reached from the second language.
- **absent, temporary**: not yet, with the tracked item that closes it.

An absence is stated rather than faked. Where a library cannot answer, the server returns nothing:
never a plausible completion assembled locally, which a user cannot tell apart from a real one.

## Installing

For the extension, install it from the marketplace. It bundles the model server and needs no
separate Node install, because it launches the editor's own runtime.

The source server needs a Python interpreter with `idfkit-lsp` installed:

```bash
pip install idfkit-lsp
```

Point the extension at it with `idfkitLsp.pythonPath` if it is not the interpreter on your path.
`idfkitLsp.nodePath` does the same for the model server, and exists for the same reason: an
environment that is not the one we guessed.

Answers about model text additionally need the language service component, which the model server
reaches through the `idfkit` facade. When it is absent, the model server reports what to install,
in the component's own words, and the source server is unaffected.

## Using it from an editor that is not the targeted one

Everything a user sees comes from a server, so a second editor costs a launch configuration and
nothing else. Nothing in `client/` is required to get any capability marked `present` above; that
claim is asserted by `tests/protocol/test_no_client.py`, which drives both servers with no part of
this repository's client loaded.

Both servers speak the protocol over stdio.

**Neovim**, with the built-in client:

```lua
vim.lsp.config.idfkit_source = {
  cmd = { 'python3', '-m', 'idfkit_lsp' },
  filetypes = { 'python' },
  root_markers = { 'pyproject.toml', '.git' },
}

vim.lsp.config.idfkit_model = {
  cmd = { 'node', '/path/to/idfkit-lsp/model-server/dist/main.js', '--stdio' },
  filetypes = { 'idf' },
  root_markers = { '.git' },
}

vim.lsp.enable({ 'idfkit_source', 'idfkit_model' })

vim.filetype.add({ extension = { idf = 'idf' } })
```

**Zed**, or any client that takes a command and a language: the same two commands, with `python`
routed to the first and `idf` to the second. Which extensions belong to which server is in
`capabilities.json` rather than in this readme, so a client that reads it does not need updating
when a document kind moves.

Ask either server what it is running:

```
idfkit-lsp/versions
```

It reports its own version and the resolved level of every library it imports, read from the
installed distribution rather than from a literal.

## Development

```bash
make install    # both runtimes
make check      # the one command a change is held to
```

The repository has four trees: `server/` (the source server, Python), `model-server/` (the model
server, TypeScript), `client/` (the editor client), and `tests/protocol/` (one suite, both servers,
no editor). Two declared records sit at the root: `capabilities.json` and `levels.json`.

Three checks hold the rules up before review rather than at review:

| Check | What it rejects |
| --- | --- |
| `make check-declaration` | a capability advertised, documented, or answered that the declaration does not carry |
| `make check-levels` | a library resolved without an exact pin, or a declared level that disagrees with the file stating it |
| `make check-knowledge` | a schema table, a grammar pattern, or arithmetic over model text outside the one module permitted it |

`.specify/memory/constitution.md` says why each of those exists. `CLAUDE.md` covers the layout and
the day-to-day commands.

## Licence

MIT
