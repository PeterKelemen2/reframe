"""Command-line entry point (``reframe``). Needs the ``[cli]`` extra (typer).

The commands are added in C-15.
"""

from __future__ import annotations

import sys

from reframe import __version__


def main() -> None:
    try:
        import typer
    except ImportError:  # pragma: no cover - depends on the installed extras
        print("The reframe CLI needs the [cli] extra: pip install 'reframe[cli]'", file=sys.stderr)
        raise SystemExit(2) from None

    app = typer.Typer(add_completion=False, no_args_is_help=True, help="Reframe video transcoder")

    @app.command()
    def version() -> None:
        """Print the Reframe version."""
        typer.echo(__version__)

    @app.callback()
    def _root() -> None:
        """Reframe video transcoder."""

    app()
