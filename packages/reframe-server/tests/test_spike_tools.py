"""The guards of the desktop spike's window and pointer tools (``desktop/spike/scripts``): the
real pointer never goes, or stays pressed, outside the secondary output, and the secondary
output's rectangle is read right. No display is needed."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[3]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from desktop.spike.scripts import kwin, pointer, windows  # noqa: E402

SECONDARY = kwin.Rect(0, 0, 1920, 1080)
SPAN = kwin.Rect(0, 0, 3840, 1080)

# `kscreen-doctor -o` of KDE Plasma 6.8 (trimmed), with its colour codes.
KSCREEN = (
    "\x1b[01;32mOutput: \x1b[0;0m1 HDMI-A-1 b07d9527\n\t\x1b[01;32menabled\x1b[0;0m\n"
    "\t\x1b[01;32mconnected\x1b[0;0m\n\t\x1b[01;32mpriority 2\x1b[0;0m\n"
    "\x1b[01;33m\tGeometry: \x1b[0;0m0,0 1920x1080\n\x1b[01;33m\tScale: \x1b[0;0m1\n"
    "\x1b[01;32mOutput: \x1b[0;0m2 DP-1 6f5109af\n\t\x1b[01;32menabled\x1b[0;0m\n"
    "\t\x1b[01;32mconnected\x1b[0;0m\n\t\x1b[01;32mpriority 1\x1b[0;0m\n"
    "\x1b[01;33m\tGeometry: \x1b[0;0m1920,0 1920x1080\n"
    "\x1b[01;32mOutput: \x1b[0;0m3 DP-2 0d6c11e2\n\t\x1b[01;31mdisabled\x1b[0;0m\n"
    "\t\x1b[01;31mdisconnected\x1b[0;0m\n\x1b[01;33m\tGeometry: \x1b[0;0m0,0 0x0\n"
)


class Device:
    """Records what would have reached ``/dev/uinput``."""

    def __init__(self, span: kwin.Rect) -> None:
        self.events: list[tuple[int, int, int]] = []
        self.closed = False

    def write(self, kind: int, code: int, value: int) -> None:
        self.events.append((kind, code, value))

    def close(self) -> None:
        self.closed = True

    def buttons(self) -> list[int]:
        return [value for kind, code, value in self.events if kind == pointer.EV_KEY]

    def positions(self) -> list[tuple[int, int]]:
        axes = [(code, value) for kind, code, value in self.events if kind == pointer.EV_ABS]
        return [(x, y) for (_, x), (_, y) in zip(axes[::2], axes[1::2], strict=True)]


def make_pointer(answers: dict[tuple[int, int], tuple[float, float] | None]) -> pointer.Pointer:
    """A pointer whose read-back gives ``answers[target]`` (the target itself by default)."""

    def read_back(x: float, y: float, since: int) -> tuple[float, float] | None:
        return answers.get((int(x), int(y)), (x, y))

    return pointer.Pointer(screen=SECONDARY, span=SPAN, read_back=read_back, open_device=Device)


def device_of(moved: pointer.Pointer) -> Device:
    assert isinstance(moved.device, Device)
    return moved.device


def test_a_move_outside_the_secondary_output_sends_nothing() -> None:
    with make_pointer({}) as moved:
        with pytest.raises(pointer.OutsideSecondary):
            moved.move(1920, 500)
        assert device_of(moved).events == []


def test_a_read_back_outside_stops_and_releases_where_the_button_went_down() -> None:
    moved = make_pointer({(1800, 500): (2100, 500)})

    def drag() -> Device:
        with moved:
            device = device_of(moved)
            moved.move(300, 400)
            moved.press()
            try:
                moved.move(1800, 500)
            except pointer.OutsideSecondary:
                return device
        raise AssertionError("the read-back outside did not stop the move")

    device = drag()
    assert device.buttons() == [1, 0]
    assert device.positions()[-1] == (300, 400)
    assert device.closed


def test_no_press_before_a_move_was_read_back() -> None:
    with make_pointer({}) as moved:
        with pytest.raises(pointer.OutsideSecondary):
            moved.press()
        assert device_of(moved).buttons() == []


def test_a_move_that_kwin_did_not_report_reads_back_the_last_report() -> None:
    class Journal:
        def __init__(self) -> None:
            self.seen: list[dict[str, Any]] = [{"event": "cursor", "x": 2400, "y": 300}]

        def wait(self, match: Any, limit: float, since: int = 0) -> None:
            return None

    wait = pointer.journal_read_back(Journal())  # type: ignore[arg-type]
    assert wait(400, 300, 1) == (2400, 300)


def test_outputs_are_read_from_the_coloured_text() -> None:
    assert kwin.parse_outputs(KSCREEN) == {
        "HDMI-A-1": kwin.Rect(0, 0, 1920, 1080),
        "DP-1": kwin.Rect(1920, 0, 1920, 1080),
    }


def test_a_spot_that_does_not_fit_the_secondary_output_is_refused() -> None:
    windows.check_spot(SECONDARY, (40, 40, 1280, 800))
    with pytest.raises(windows.WrongOutput):
        windows.check_spot(SECONDARY, (700, 40, 1280, 800))
    with pytest.raises(windows.WrongOutput):
        windows.check_spot(SECONDARY, (1930, 40, None, None))
