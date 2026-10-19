"""The VAAPI render nodes of this machine."""

from __future__ import annotations

import re
from pathlib import Path

__all__ = ["DRI", "render_nodes"]

DRI = Path("/dev/dri")
_NODE = re.compile(r"^renderD(\d+)$")


def render_nodes(dri: Path = DRI) -> list[str]:
    """``/dev/dri/renderD*`` sorted by number, not by name; ``[]`` when the folder cannot be
    read. Blocking: call it in a worker thread."""
    try:
        names = [entry.name for entry in dri.iterdir()]
    except OSError:
        return []
    numbered = [(int(match[1]), name) for name in names if (match := _NODE.match(name))]
    return [str(dri / name) for _number, name in sorted(numbered)]
