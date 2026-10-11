from __future__ import annotations

import reframe
import reframe_server


def test_server_version_matches_core() -> None:
    assert reframe_server.__version__ == reframe.__version__
