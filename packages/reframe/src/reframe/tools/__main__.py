"""``python -m reframe.tools``: print which tools discovery picks (a diagnostic for CI).

Options:

- ``--json``: print the ``ToolSet`` as JSON instead of one line per tool.
- ``--require ffmpeg,ffprobe``: exit with 1 unless these tools have the status ``found``.
- ``--expect-origin bundled``: exit with 1 unless every required tool has this origin.

The ``reframe tools status`` CLI command (C-15) will show the same information.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

from reframe.models.tools import ToolOrigin, ToolStatus
from reframe.tools.discovery import TOOL_NAMES, discover_tools_sync


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m reframe.tools", description=__doc__)
    parser.add_argument("--json", action="store_true", help="print the result as JSON")
    parser.add_argument("--require", default="", help="comma-separated tools that must be found")
    parser.add_argument(
        "--expect-origin",
        choices=[o.value for o in ToolOrigin],
        help="the origin every required tool must have",
    )
    args = parser.parse_args(argv)
    requested = {t.strip() for t in args.require.split(",") if t.strip()}
    unknown = sorted(requested - set(TOOL_NAMES))
    if unknown:
        parser.error(f"unknown tool(s): {', '.join(unknown)}")
    required = [name for name in TOOL_NAMES if name in requested]

    tools = discover_tools_sync()
    if args.json:
        print(tools.model_dump_json(indent=2))
    else:
        for name in TOOL_NAMES:
            info = tools.get(name)
            origin = info.origin.value if info.origin else "-"
            line = f"{name:12} {info.status.value:8} {origin:8} {info.path or '-'}"
            if info.version:
                line += f"  {info.version}"
            if info.reason:
                line += f"  ({info.reason})"
            print(line)

    failed = False
    for name in required:
        info = tools.get(name)
        if info.status is not ToolStatus.FOUND:
            print(f"error: {name} is {info.status.value}: {info.reason}", file=sys.stderr)
            failed = True
        elif args.expect_origin and (info.origin or "") != args.expect_origin:
            print(
                f"error: {name} comes from {info.origin}, expected {args.expect_origin}",
                file=sys.stderr,
            )
            failed = True
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
