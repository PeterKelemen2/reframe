"""Write the server's OpenAPI document as JSON to the file given as the argument, or to stdout.

The app is created but never started: no facade, no tools and no network are needed. The
``REFRAME_*`` variables of the shell are ignored, so the document is the same everywhere.
"""

from __future__ import annotations

import json
import logging
import os
import sys
from pathlib import Path


def main(argv: list[str]) -> int:
    for name in [name for name in os.environ if name.startswith("REFRAME_")]:
        del os.environ[name]
    logging.disable(logging.WARNING)  # create_app warns that auth is off

    from reframe_server.app import create_app
    from reframe_server.config import ServerConfig

    text = json.dumps(create_app(ServerConfig()).openapi(), indent=2, ensure_ascii=False) + "\n"
    if argv:
        Path(argv[0]).write_text(text, encoding="utf-8", newline="\n")
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
