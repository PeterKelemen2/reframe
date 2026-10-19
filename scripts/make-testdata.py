"""Generate the test media fixtures into testdata/media/ (git-ignored).

ffmpeg comes from $REFRAME_FFMPEG, else PATH. Re-running is fast: fixtures whose recipe did not
change are skipped.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "testing"))

from reframe_testing.media import main

if __name__ == "__main__":
    raise SystemExit(main())
