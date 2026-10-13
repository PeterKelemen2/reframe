"""The VAAPI render nodes of this machine (decision 0020).

Detection tests the VAAPI encoders on every node, in this order, and each encoder uses the
first node where its test encode works. Settings → Encoders can force one node instead
(``AppSettings.encoders.vaapi_device``).
"""

from __future__ import annotations

import re
from pathlib import Path

__all__ = ["DRI", "render_nodes"]

DRI = Path("/dev/dri")
_NODE = re.compile(r"^renderD(\d+)$")


def render_nodes(dri: Path = DRI) -> list[str]:
    """``/dev/dri/renderD*`` sorted by number (``renderD128`` before ``renderD129``); ``[]`` when
    the folder does not exist or cannot be read. Blocking: call it in a worker thread."""
    try:
        names = [entry.name for entry in dri.iterdir()]
    except OSError:
        return []
    numbered = [(int(match[1]), name) for name in names if (match := _NODE.match(name))]
    return [str(dri / name) for _number, name in sorted(numbered)]
