# idfkit Language Server

A Language Server Protocol (LSP) implementation that provides intelligent editing support for Python files using the [idfkit](https://github.com/samuelduchesne/idfkit) EnergyPlus library. Ships as a VS Code extension.

## Features

- **Autocomplete** — Object type names, field attributes, and keyword arguments with documentation, units, and constraints
- **Hover documentation** — Inline docs for object types (group, memo, required fields), field attributes (type, units, defaults, min/max, choices), and inferred variable types
- **Signature help** — Parameter info for `doc.add()` calls showing required and optional fields with their types and descriptions
- **AST-based type inference** — Tracks `IDFDocument`, `IDFCollection`, and `IDFObject` types through assignments, subscripts, method calls, and for-loop iteration

```python
from idfkit import load_idf

doc = load_idf("model.idf")        # inferred: IDFDocument
zones = doc["Zone"]                 # inferred: IDFCollection("Zone")
zone = zones["Office"]              # inferred: IDFObject("Zone")
new_zone = doc.add("Zone", "Hall")  # inferred: IDFObject("Zone")

# Completions, hover, and signature help work throughout
zone.x_origin  # ← field attribute completion + hover docs
```

## Requirements

- Python 3.10+
- VS Code 1.78+
- [idfkit](https://github.com/samuelduchesne/idfkit) installed in the Python environment

## Installation

Install the LSP server into the Python environment you use for idfkit, then install the VS Code extension.

### 1. Install the LSP server

```bash
pip install idfkit-lsp
```

Or install from source:

```bash
git clone https://github.com/samuelduchesne/idfkit-lsp.git
cd idfkit-lsp/server
pip install .
```

Verify the server is installed:

```bash
python -m idfkit_lsp --help
```

### 2. Install the VS Code extension

Build and install the extension locally:

```bash
cd idfkit-lsp
npm install
npm run compile
npx @vscode/vsce package       # creates idfkit-lsp-0.1.0.vsix
code --install-extension idfkit-lsp-0.1.0.vsix
```

### 3. Configure the Python path

If your idfkit Python environment is not the default `python3`, set the interpreter path in VS Code:

1. Open **Settings** (`Ctrl+,` / `Cmd+,`)
2. Search for `idfkitLsp.pythonPath`
3. Set it to the full path of the Python interpreter with idfkit-lsp installed (e.g., `/path/to/venv/bin/python`)

Restart VS Code or run the **idfkit: Restart Language Server** command to apply changes.

## Development

### Running from source in VS Code

Requires [uv](https://docs.astral.sh/uv/) and Node.js.

1. Clone the repository and install dependencies:
   ```bash
   make install        # or: cd server && uv sync --extra dev
   npm install
   npm run compile
   ```
2. Open this repository in VS Code
3. Press **F5** to launch the Extension Development Host
4. Open a Python file that uses idfkit — the language server activates automatically

### Make targets

```bash
make install            # install with uv
make check              # run all checks (lint, format, typecheck, test)
make fix                # auto-fix lint + format issues
make pre-commit-install # install git pre-commit hooks
```

| Command | Description |
|---|---|
| `make lint` | Run ruff linter |
| `make format` | Check formatting |
| `make format-fix` | Auto-format code |
| `make typecheck` | Run pyright |
| `make test` | Run pytest |
| `make check` | All of the above |

### Testing

```bash
make test       # or: cd server && uv run pytest
make test-v     # verbose output
```

The test suite covers the analyzer, completion, hover, signature help, and end-to-end LSP integration.

## Configuration

| Setting | Default | Description |
|---|---|---|
| `idfkitLsp.pythonPath` | `python3` | Path to the Python interpreter with idfkit and idfkit-lsp installed |
| `idfkitLsp.trace.server` | `off` | Traces communication between VS Code and the server (`off`, `messages`, `verbose`) |

Use the **idfkit: Restart Language Server** command to reload after configuration changes.

## Architecture

```
├── client/              # VS Code extension (TypeScript)
│   └── src/extension.ts # Spawns the Python server over stdio
├── server/              # LSP server (Python, pygls)
│   └── src/idfkit_lsp/
│       ├── server.py          # LSP handler registration
│       ├── analyzer.py        # AST visitor for type inference
│       ├── completion.py      # Autocomplete provider
│       ├── hover.py           # Hover documentation provider
│       ├── signature_help.py  # Signature help provider
│       ├── schema_cache.py    # EnergyPlus schema wrapper
│       └── document_state.py  # Per-document state management
```

## License

MIT
