<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/idfkit/idfkit-brand/identity-2026.2/marks/mark-on-dark.svg">
    <source media="(prefers-color-scheme: light)" srcset="https://raw.githubusercontent.com/idfkit/idfkit-brand/identity-2026.2/marks/mark-on-light.svg">
    <img alt="idfkit" width="72" src="https://raw.githubusercontent.com/idfkit/idfkit-brand/identity-2026.2/marks/tile.png">
  </picture>
</p>

# idfkit-lsp

A Language Server Protocol implementation for EnergyPlus models, built on idfkit.

[idfkit](https://idfkit.com) · [Developers](https://developers.idfkit.com) · [EnergyPlus docs](https://docs.idfkit.com) · [Envelop](https://app.idfkit.com) · [MCP](https://mcp.idfkit.com) · [Shoebox](https://shoebox.idfkit.com) · [GitHub](https://github.com/idfkit)

This package is the source server of [idfkit-lsp](https://github.com/idfkit/idfkit-lsp). It answers
questions about Python source that uses the `idfkit` library, over stdio, for Python 3.10 through
3.13. The VS Code extension uses it, and any other editor can launch it.

The package pins `idfkit` to one exact level, so installing it into a project's own environment can
conflict with the `idfkit` that project uses. Give it an environment of its own:

```bash
python3 -m venv ~/.idfkit-lsp
~/.idfkit-lsp/bin/python -m pip install idfkit-lsp
~/.idfkit-lsp/bin/python -m idfkit_lsp --version
```

The server for EnergyPlus model text is a separate package on npm,
[`@idfkit/language-server`](https://www.npmjs.com/package/@idfkit/language-server).

## License

MIT.
