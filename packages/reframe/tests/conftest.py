from __future__ import annotations

import os
import sys
import threading
from collections.abc import Callable
from pathlib import Path

import pytest

type FifoRead = Callable[[str, Callable[[Path], object]], object]


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
def fifo_read(tmp_path: Path) -> FifoRead:
    """``fifo_read(name, reader)``: ``reader`` of a new FIFO with no writer, in a thread; the
    test fails when ``reader`` waits for a writer."""
    if sys.platform == "win32":
        pytest.skip("needs FIFOs")
    else:

        def read(name: str, reader: Callable[[Path], object]) -> object:
            fifo = tmp_path / name
            os.mkfifo(fifo)
            results: list[object] = []
            thread = threading.Thread(target=lambda: results.append(reader(fifo)), daemon=True)
            thread.start()
            thread.join(5)
            if thread.is_alive():
                os.close(os.open(fifo, os.O_WRONLY | os.O_NONBLOCK))  # free the reader
                thread.join(5)
                pytest.fail(f"reading the FIFO {name} waited for a writer")
            return results[0]

        return read
