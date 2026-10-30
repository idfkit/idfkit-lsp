# Contributing

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

The capabilities block in `README.md` is generated. Regenerate it after a change to the declaration
with `uv run --project server python -m tools.check_declaration --fix`. `make check-declaration`
only checks it, and CI runs that check, which is where a readme that has drifted from the servers
is caught.
