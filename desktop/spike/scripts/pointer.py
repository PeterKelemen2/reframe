"""The real pointer, through an absolute pointer device made with ``/dev/uinput`` (it needs no
root where the user has an ACL on it). KWin moves its one cursor for this device as for a
mouse, so Wayland clients get real input: drags work.

Every target is refused before it is sent unless it is inside the secondary output; every move
is read back from KWin (the session script reports the cursor); a read-back outside it, or a
mapping that is not the one checked at the first move, stops the run. A pressed button is
released, back where it was pressed, and the device is removed on exit, also after an error or
Ctrl+C. Run it only inside a :class:`~desktop.spike.scripts.windows.Session` with
``cursor=True``."""

from __future__ import annotations

import argparse
import fcntl
import glob
import json
import os
import struct
import sys
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path
from types import TracebackType
from typing import Any, Protocol

from desktop.spike.scripts import kwin

EV_SYN, EV_KEY, EV_ABS = 0x00, 0x01, 0x03
SYN_REPORT = 0
BTN_LEFT, BTN_RIGHT, BTN_MIDDLE = 0x110, 0x111, 0x112
ABS_X, ABS_Y = 0x00, 0x01
BUS_VIRTUAL = 0x06
NAME = "reframe-spike pointer"
READ_BACK = 1.0
"""Seconds to wait for KWin's report of a move."""


def _ioc(direction: int, number: int, size: int) -> int:
    return (direction << 30) | (size << 16) | (ord("U") << 8) | number


UI_DEV_CREATE = _ioc(0, 1, 0)
UI_DEV_DESTROY = _ioc(0, 2, 0)
UI_DEV_SETUP = _ioc(1, 3, struct.calcsize("HHHH80sI"))
UI_ABS_SETUP = _ioc(1, 4, struct.calcsize("H2xiiiiii"))
UI_SET_EVBIT = _ioc(1, 100, 4)
UI_SET_KEYBIT = _ioc(1, 101, 4)
UI_SET_ABSBIT = _ioc(1, 103, 4)
UI_GET_SYSNAME = _ioc(2, 44, 64)
# Linux only; looked up so that the Windows type check passes.
_ioctl: Callable[..., Any] = getattr(fcntl, "ioctl")  # noqa: B009
_O_NONBLOCK: int = getattr(os, "O_NONBLOCK")  # noqa: B009


class OutsideSecondary(RuntimeError):
    """A move that would leave, or did leave, the secondary output."""


class Writer(Protocol):
    def write(self, kind: int, code: int, value: int) -> None: ...

    def close(self) -> None: ...


class Uinput:
    """The device: ABS_X / ABS_Y over ``span`` and three buttons."""

    def __init__(self, span: kwin.Rect) -> None:
        self.fd = os.open("/dev/uinput", os.O_WRONLY | _O_NONBLOCK)
        try:
            _ioctl(self.fd, UI_SET_EVBIT, EV_KEY)
            for button in (BTN_LEFT, BTN_RIGHT, BTN_MIDDLE):
                _ioctl(self.fd, UI_SET_KEYBIT, button)
            _ioctl(self.fd, UI_SET_EVBIT, EV_ABS)
            for axis, size in ((ABS_X, span.width), (ABS_Y, span.height)):
                _ioctl(self.fd, UI_SET_ABSBIT, axis)
                _ioctl(
                    self.fd, UI_ABS_SETUP, struct.pack("H2xiiiiii", axis, 0, 0, size - 1, 0, 0, 0)
                )
            setup = struct.pack("HHHH80sI", BUS_VIRTUAL, 0x1209, 0x5EB1, 1, NAME.encode(), 0)
            _ioctl(self.fd, UI_DEV_SETUP, setup)
            _ioctl(self.fd, UI_DEV_CREATE)
        except BaseException:
            os.close(self.fd)
            raise
        answer = _ioctl(self.fd, UI_GET_SYSNAME, bytes(64))
        self.sys_name = answer.split(b"\0", 1)[0].decode()
        """``inputN`` under ``/sys/devices/virtual/input``."""

    @property
    def event_node(self) -> str | None:
        found = glob.glob(f"/sys/devices/virtual/input/{self.sys_name}/event*")
        return Path(found[0]).name if found else None

    def write(self, kind: int, code: int, value: int) -> None:
        os.write(self.fd, struct.pack("qqHHi", 0, 0, kind, code, value))

    def close(self) -> None:
        try:
            _ioctl(self.fd, UI_DEV_DESTROY)
        finally:
            os.close(self.fd)


@dataclass
class Pointer:
    """Absolute moves in desktop coordinates, inside ``screen`` only.

    ``span`` is the bounding box of every output: KWin maps an absolute pointer device onto
    it, which the first move checks."""

    screen: kwin.Rect
    span: kwin.Rect
    read_back: Callable[[float, float, int], tuple[float, float] | None]
    """Waits for KWin's cursor report after a move: ``(x, y, since)`` → the position, or
    ``None`` when no report matches in time."""
    open_device: Callable[[kwin.Rect], Writer] = Uinput
    log: list[dict[str, Any]] = field(default_factory=list)
    mark: Callable[[], int] = lambda: 0
    device: Writer | None = field(default=None, init=False)
    pressed_at: tuple[int, int] | None = field(default=None, init=False)
    _checked: bool = field(default=False, init=False)

    def __enter__(self) -> Pointer:
        self.device = self.open_device(self.span)
        return self

    def __exit__(
        self,
        kind: type[BaseException] | None,
        error: BaseException | None,
        trace: TracebackType | None,
    ) -> None:
        try:
            if self.pressed_at is not None:
                self._release_where_pressed()
        finally:
            if self.device is not None:
                self.device.close()
                self.device = None

    def _release_where_pressed(self) -> None:
        assert self.device is not None
        assert self.pressed_at is not None
        x, y = self.pressed_at
        try:
            if self._checked:
                self._send(x, y)
        finally:
            self.device.write(EV_KEY, BTN_LEFT, 0)
            self.device.write(EV_SYN, SYN_REPORT, 0)
            self.pressed_at = None
            self.log.append({"release": [x, y], "aborted": True})

    def _send(self, x: int, y: int) -> None:
        assert self.device is not None
        self.device.write(EV_ABS, ABS_X, x - self.span.x)
        self.device.write(EV_ABS, ABS_Y, y - self.span.y)
        self.device.write(EV_SYN, SYN_REPORT, 0)

    def move(self, x: int, y: int) -> tuple[float, float]:
        """Moves to ``(x, y)`` and returns where KWin put the cursor."""
        if not self.screen.contains(x, y):
            raise OutsideSecondary(
                f"refused: ({x}, {y}) is not inside {kwin.SECONDARY} {self.screen}"
            )
        since = self.mark()
        started = time.monotonic()
        self._send(x, y)
        seen = self.read_back(x, y, since)
        entry: dict[str, Any] = {
            "to": [x, y],
            "read_back": list(seen) if seen else None,
            "ms": round((time.monotonic() - started) * 1000, 1),
        }
        self.log.append(entry)
        # The target is inside, so a cursor anywhere else (another output too) stops the run.
        if seen is None or (round(seen[0]), round(seen[1])) != (x, y):
            raise OutsideSecondary(f"the move to ({x}, {y}) read back as {seen}: the run stops")
        self._checked = True
        return seen

    def glide(self, points: Iterable[tuple[int, int]], pause: float = 0.016) -> None:
        for x, y in points:
            self.move(x, y)
            time.sleep(pause)

    def press(self) -> None:
        if not self._checked:
            raise OutsideSecondary("no move read back yet: no press")
        assert self.device is not None
        last = self.log[-1]["to"]
        self.device.write(EV_KEY, BTN_LEFT, 1)
        self.device.write(EV_SYN, SYN_REPORT, 0)
        self.pressed_at = (last[0], last[1])
        self.log.append({"press": last})

    def release(self) -> None:
        assert self.device is not None
        self.device.write(EV_KEY, BTN_LEFT, 0)
        self.device.write(EV_SYN, SYN_REPORT, 0)
        last = next((entry["to"] for entry in reversed(self.log) if "to" in entry), None)
        self.log.append({"release": last})
        self.pressed_at = None

    def right_click(self) -> None:
        """A right click where the last move went (it cancels KWin's interactive window pick)."""
        if not self._checked:
            raise OutsideSecondary("no move read back yet: no click")
        assert self.device is not None
        for value in (1, 0):
            self.device.write(EV_KEY, BTN_RIGHT, value)
            self.device.write(EV_SYN, SYN_REPORT, 0)
        self.log.append({"right_click": self.log[-1]["to"]})


def line(start: tuple[int, int], end: tuple[int, int], steps: int) -> list[tuple[int, int]]:
    """``steps`` points from ``start`` (left out) to ``end`` (included)."""
    (x0, y0), (x1, y1) = start, end
    return [
        (round(x0 + (x1 - x0) * i / steps), round(y0 + (y1 - y0) * i / steps))
        for i in range(1, steps + 1)
    ]


def journal_read_back(
    journal: kwin.Journal,
) -> Callable[[float, float, int], tuple[float, float] | None]:
    def wait(x: float, y: float, since: int) -> tuple[float, float] | None:
        # KWin reports changes only: a move to where the cursor is gets no report.
        before = [record for record in journal.seen[:since] if record["event"] == "cursor"]
        if before and (before[-1]["x"], before[-1]["y"]) == (x, y):
            return (x, y)
        found = journal.wait(
            lambda record: (
                record["event"] == "cursor"
                and abs(record["x"] - x) < 1
                and abs(record["y"] - y) < 1
            ),
            READ_BACK,
            since,
        )
        if found is not None:
            return (found["x"], found["y"])
        last = [record for record in journal.seen if record["event"] == "cursor"]
        return (last[-1]["x"], last[-1]["y"]) if last else None

    return wait


def span_of(outputs: dict[str, kwin.Rect]) -> kwin.Rect:
    left = min(rect.x for rect in outputs.values())
    top = min(rect.y for rect in outputs.values())
    right = max(rect.x + rect.width for rect in outputs.values())
    bottom = max(rect.y + rect.height for rect in outputs.values())
    return kwin.Rect(left, top, right - left, bottom - top)


def for_session(
    journal: kwin.Journal, screen: kwin.Rect, log: list[dict[str, Any]] | None = None
) -> Pointer:
    return Pointer(
        screen=screen,
        span=span_of(kwin.outputs()),
        read_back=journal_read_back(journal),
        log=[] if log is None else log,
        mark=journal.mark,
    )


def check_device(device: Writer, limit: float = 3.0) -> dict[str, str]:
    """Waits until KWin lists the device and returns its properties; refuses one that KWin
    maps to an output, since then the first move would not be where the span says."""
    if not isinstance(device, Uinput):
        return {}
    node = device.event_node
    if node is None or not kwin.poll(lambda: node in kwin.input_devices(), limit):
        raise RuntimeError(f"KWin did not list {device.sys_name} ({node}) as a pointer")
    properties = kwin.input_device(node)
    if properties.get("outputName") not in ("", None) or properties.get("pointer") != "true":
        raise OutsideSecondary(f"KWin maps the device unexpectedly: {properties}")
    return properties | {"sys_name": device.sys_name, "node": node}


def demo(seconds: float) -> int:
    """Moves the pointer round a small square in the middle of the secondary output."""
    from desktop.spike.scripts import windows

    windows.stop_on_signals()
    with windows.Session(cursor=True) as session:
        pointer = for_session(session.journal, session.screen)
        try:
            with pointer:
                assert pointer.device is not None
                print(json.dumps({"device": check_device(pointer.device)}))
                cx = session.screen.x + session.screen.width // 2
                cy = session.screen.y + session.screen.height // 2
                corners = [
                    (cx - 100, cy - 100),
                    (cx + 100, cy - 100),
                    (cx + 100, cy + 100),
                    (cx - 100, cy + 100),
                ]
                pointer.move(*corners[0])
                deadline = time.monotonic() + seconds
                while time.monotonic() < deadline:
                    for start, end in zip(corners, corners[1:] + corners[:1], strict=True):
                        pointer.glide(line(start, end, 10))
        finally:
            for entry in pointer.log:
                print(json.dumps(entry))
    print(json.dumps({"scripts_loaded_after": session.unloaded()}))
    print(json.dumps({"device_left": NAME in Path("/proc/bus/input/devices").read_text()}))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["demo"])
    parser.add_argument("--seconds", type=float, default=1.0)
    args = parser.parse_args(argv)
    return demo(args.seconds)


if __name__ == "__main__":
    sys.exit(main())
