"""Print one version's section of ``CHANGELOG.md``, without its heading: the release notes.

Exits 1 when the changelog has no section for that version, or an empty one. A leading ``v``
(the tag's spelling) is ignored.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

_HEADING_RE = re.compile(r"^## \[(?P<version>[^\]]+)\]")


def section(changelog: str, version: str) -> str | None:
    """The text under ``## [version]`` up to the next ``## `` heading, stripped; None if absent."""
    lines: list[str] | None = None
    for line in changelog.splitlines():
        if line.startswith("## "):
            if lines is not None:
                break
            match = _HEADING_RE.match(line)
            if match is not None and match.group("version") == version:
                lines = []
        elif lines is not None:
            lines.append(line)
    if lines is None:
        return None
    return "\n".join(lines).strip()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.add_argument("version", help="the version, e.g. 1.1.0 or v1.1.0rc1")
    parser.add_argument("--changelog", type=Path, default=REPO_ROOT / "CHANGELOG.md")
    args = parser.parse_args(argv)
    version = args.version.removeprefix("v")

    try:
        text = args.changelog.read_bytes().decode("utf-8")
    except OSError as error:
        print(f"release-notes: {error}", file=sys.stderr)
        return 1
    notes = section(text, version)
    if not notes:
        what = "no section" if notes is None else "an empty section"
        print(f"release-notes: {args.changelog.name} has {what} for {version}", file=sys.stderr)
        return 1
    print(notes)
    return 0


if __name__ == "__main__":
    sys.exit(main())
