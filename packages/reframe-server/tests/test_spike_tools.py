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


@pytest.mark.parametrize("seen", [(2100, 500), (1800, 800)], ids=["x elsewhere", "y elsewhere"])
def test_a_read_back_elsewhere_stops_and_releases_where_the_button_went_down(
    seen: tuple[int, int],
) -> None:
    moved = make_pointer({(1800, 500): seen})

    def drag() -> Device:
        with moved:
            device = device_of(moved)
            moved.move(300, 400)
            moved.press()
            try:
                moved.move(1800, 500)
            except pointer.OutsideSecondary:
                return device
        raise AssertionError("the read-back elsewhere did not stop the move")

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


def test_a_spot_that_fits_the_secondary_output_is_taken() -> None:
    windows.check_spot(SECONDARY, (40, 40, 1280, 800))


@pytest.mark.parametrize(
    "spot",
    [(-10, 40, 1280, 800), (40, -10, 1280, 800), (700, 40, 1280, 800), (40, 400, 1280, 800)],
    ids=["past the left", "past the top", "past the right", "past the bottom"],
)
def test_a_spot_that_does_not_fit_the_secondary_output_is_refused(spot: windows.Spot) -> None:
    with pytest.raises(windows.WrongOutput):
        windows.check_spot(SECONDARY, spot)


def test_a_spot_without_a_size_must_start_on_the_secondary_output() -> None:
    with pytest.raises(windows.WrongOutput):
        windows.check_spot(SECONDARY, (1930, 40, None, None))


class QuietJournal:
    """A journal whose records the test hands to the session itself."""

    def __init__(self) -> None:
        self.seen: list[dict[str, Any]] = []

    def wait(self, match: Any, limit: float, since: int = 0) -> None:
        return None


def make_session(monkeypatch: pytest.MonkeyPatch, *answers: kwin.Rect) -> windows.Session:
    """A session on ``SECONDARY`` with no KWin: ``getWindowInfo`` answers ``answers`` in turn
    (the last one again after that)."""
    session = windows.Session()
    session.screen = SECONDARY
    session.journal = QuietJournal()  # type: ignore[assignment]
    replies = list(answers)

    def window_info(uuid: str) -> dict[str, str]:
        rect = replies.pop(0) if len(replies) > 1 else replies[0]
        return {
            "x": str(rect.x),
            "y": str(rect.y),
            "width": str(rect.width),
            "height": str(rect.height),
            "pid": "7",
        }

    monkeypatch.setattr(kwin, "window_info", window_info)
    return session


def record(event: str, **fields: Any) -> dict[str, Any]:
    base = {
        "event": event,
        "id": "{w}",
        "pid": 7,
        "normal": True,
        "dialog": False,
        "output": "HDMI-A-1",
        "geo": [40, 40, 1280, 800],
        "opacity": 1,
        "seen": 100.0,
    }
    return base | fields


INSIDE = kwin.Rect(40, 40, 1280, 800)
ON_DP1 = kwin.Rect(2260, 123, 1240, 788)


def test_a_window_shown_on_the_secondary_output_is_returned(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = make_session(monkeypatch, INSIDE)
    session._check([record("added", opacity=0), record("shown")], 100.1)
    assert session.failure is None
    assert session.window(7, limit=1).rect == INSIDE


def test_a_shown_window_read_back_past_the_bottom_stops_the_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = make_session(monkeypatch, kwin.Rect(40, 400, 1280, 800))
    session._check([record("added", opacity=0), record("shown")], 100.1)
    assert session.failure is not None
    with pytest.raises(windows.WrongOutput):
        session.window(7, limit=1)


def test_a_window_read_back_elsewhere_after_it_settles_is_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The move was asked for and not applied: the second read-back finds the window on DP-1.
    session = make_session(monkeypatch, INSIDE, ON_DP1)
    session._check([record("added", opacity=0), record("shown")], 100.1)
    with pytest.raises(windows.WrongOutput):
        session.window(7, limit=1)


@pytest.mark.parametrize(("opacity", "stops"), [(1, True), (0, False)], ids=["opaque", "hidden"])
def test_a_window_seen_on_another_output_stops_the_session_when_it_is_opaque(
    monkeypatch: pytest.MonkeyPatch, opacity: int, stops: bool
) -> None:
    session = make_session(monkeypatch, INSIDE)
    session._check([record("moved", output="DP-1", opacity=opacity)], 100.1)
    assert (session.failure is not None) is stops
    if stops:
        with pytest.raises(windows.WrongOutput):
            session.window(7, limit=0.2)


def test_a_window_not_shown_in_time_stops_the_session(monkeypatch: pytest.MonkeyPatch) -> None:
    session = make_session(monkeypatch, INSIDE)
    session._check([record("added", opacity=0)], 100.0 + windows.SHOW_LIMIT / 2)
    assert session.failure is None
    session._check([], 100.0 + windows.SHOW_LIMIT + 0.1)
    assert session.failure is not None


def test_a_window_closed_before_it_was_shown_does_not_stop_the_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = make_session(monkeypatch, INSIDE)
    session._check([record("added", opacity=0), record("removed")], 100.1)
    session._check([], 100.0 + windows.SHOW_LIMIT + 0.1)
    assert session.failure is None
