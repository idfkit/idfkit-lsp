# @idfkit/language-server

A language server for EnergyPlus model text (`.idf`). It serves semantic tokens, diagnostics,
completion, hover and go-to-definition over the Language Server Protocol, translating what the
[idfkit](https://github.com/idfkit) language service answers. It holds no EnergyPlus knowledge of
its own.

This is the model server from [idfkit-lsp](https://github.com/idfkit/idfkit-lsp), published for
editors other than VS Code. The VS Code extension already bundles it.

## Install and run

Needs Node 20 or newer.

```bash
npm install -g @idfkit/language-server
idfkit-language-server --stdio
```

Or without installing: `npx @idfkit/language-server --stdio`.

## Editors

The server speaks the protocol over stdio, so any client that takes a command and a language can
start it. Neovim, with the built-in client:

```lua
vim.lsp.config.idfkit_model = {
  cmd = { 'idfkit-language-server', '--stdio' },
  filetypes = { 'idf' },
  root_markers = { '.git' },
}
vim.lsp.enable({ 'idfkit_model' })
vim.filetype.add({ extension = { idf = 'idf' } })
```

An editor extension (Zed, for example) can install this package and run its `dist/main.js` with
`--stdio` on the editor's own Node runtime.

The protocol has no request for toggling a comment, so this server cannot configure it. Set the
editor's own comment setting for `idf` to the `comments.lineComment` value in
[`language-configuration.json`](https://github.com/idfkit/idfkit-lsp/blob/main/language-configuration.json).
In Neovim that setting is the `commentstring` option, written as the marker followed by ` %s`.

## What it answers

What this server answers, and what it never will, is declared in
[`capabilities.json`](https://github.com/idfkit/idfkit-lsp/blob/main/capabilities.json) and
rendered in the [idfkit-lsp readme](https://github.com/idfkit/idfkit-lsp#readme). Python code that
uses idfkit is served by a separate server, `pip install idfkit-lsp`.

## License

MIT
