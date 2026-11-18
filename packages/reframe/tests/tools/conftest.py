"""Fixtures of the ``reframe.tools`` tests."""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from .fetch_server import LocalServer, local_server


@pytest.fixture
def server() -> Iterator[LocalServer]:
    yield from local_server()
