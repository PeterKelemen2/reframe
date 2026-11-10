"""The check of the system's libva for the bundled FFmpeg."""

from __future__ import annotations

import ctypes
from collections.abc import Iterator
from types import SimpleNamespace

import pytest

from reframe.platform import libva


@pytest.fixture(autouse=True)
def _uncached() -> Iterator[None]:
    libva.system_libva_usable.cache_clear()
    yield
    libva.system_libva_usable.cache_clear()


def _libraries(monkeypatch: pytest.MonkeyPatch, available: dict[str, object]) -> None:
    def load(name: str) -> object:
        if name not in available:
            raise OSError(f"{name}: cannot open shared object file")
        return available[name]

    monkeypatch.setattr(ctypes, "CDLL", load)


def test_usable_with_every_needed_function(monkeypatch: pytest.MonkeyPatch) -> None:
    full = SimpleNamespace(**dict.fromkeys(libva.NEEDED_FUNCTIONS, object()))
    _libraries(monkeypatch, {"libva.so.2": full, "libva-drm.so.2": object()})
    assert libva.system_libva_usable() is True


def test_an_old_libva_is_not_usable(monkeypatch: pytest.MonkeyPatch) -> None:
    old = SimpleNamespace(**dict.fromkeys(libva.NEEDED_FUNCTIONS[1:], object()))
    _libraries(monkeypatch, {"libva.so.2": old, "libva-drm.so.2": object()})
    assert libva.system_libva_usable() is False


@pytest.mark.parametrize("missing", libva.SYSTEM_LIBRARIES)
def test_a_missing_library_is_not_usable(monkeypatch: pytest.MonkeyPatch, missing: str) -> None:
    full = SimpleNamespace(**dict.fromkeys(libva.NEEDED_FUNCTIONS, object()))
    present: dict[str, object] = {"libva.so.2": full, "libva-drm.so.2": object()}
    del present[missing]
    _libraries(monkeypatch, present)
    assert libva.system_libva_usable() is False
