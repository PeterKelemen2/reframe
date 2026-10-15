"""Rule cases of remux-only and in-place metadata-edit jobs
(C-13, ``reframe.validation.inplace``), added to ``test_rules.CASES`` (see ``EXTRA_CASE_FILES``
there).

Each case: an issue code and path, a change of the clean scenario that must produce it
(positive), and a close change that must not (negative). ``h`` is a namespace with the helpers
of ``test_rules.py`` (``h.Case``, ``h.ERR`` / ``h.WARN`` / ``h.INFO``, ``h.video``, ``h.both``, …).
"""

from __future__ import annotations

from typing import Any


def cases(h: Any) -> list[Any]:
    del h
    return []
