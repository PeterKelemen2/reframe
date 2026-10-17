from __future__ import annotations

import re

import reframe


def test_version_is_pep440() -> None:
    assert re.fullmatch(r"\d+\.\d+\.\d+((a|b|rc)\d+)?(\.dev\d+)?", reframe.__version__)
