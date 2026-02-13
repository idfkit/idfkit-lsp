"""Entry point for: python -m idfkit_lsp"""

from idfkit_lsp.server import server


def main() -> None:
    server.start_io()


if __name__ == "__main__":
    main()
