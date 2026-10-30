"""Entry point for: python -m idfkit_lsp

``--version`` reports the level and exits. The import below is what makes it a useful question to
ask: the flag answers only after the server module and every library it needs have loaded, so a
launcher can learn whether an interpreter is able to run this server without starting it.
"""

from __future__ import annotations

import sys

from idfkit_lsp.server import server


def main() -> None:
    if "--version" in sys.argv[1:]:
        print(f"{server.name} {server.version}")
        return
    server.start_io()


if __name__ == "__main__":
    main()
