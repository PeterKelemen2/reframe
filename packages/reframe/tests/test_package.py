from __future__ import annotations

import re

import pytest

import reframe


def test_version_is_pep440() -> None:
    assert re.fullmatch(r"\d+\.\d+\.\d+((a|b|rc)\d+)?(\.dev\d+)?", reframe.__version__)


@pytest.mark.anyio
async def test_anyio_plugin_runs_async_tests() -> None:
    assert reframe.__version__
