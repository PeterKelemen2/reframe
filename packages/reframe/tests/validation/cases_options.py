"""Rule cases of the advanced encoder options (C-6 option
sets, ``reframe.validation.video``), added to ``test_rules.CASES`` (see ``EXTRA_CASE_FILES``
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
