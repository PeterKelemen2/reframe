"""KWin over D-Bus (``qdbus6``) and the outputs of ``kscreen-doctor``: the read side of the
window and pointer tools. A KWin script reports by calling a D-Bus method of a name that nobody
owns; :class:`Journal` watches those calls with ``busctl monitor`` (``print`` reaches the user
journal too, but about 0.5 s late)."""

from __future__ import annotations

import json
import re
import secrets
import subprocess
import tempfile
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

SECONDARY = "HDMI-A-1"
"""The output every window and pointer move of the spike goes to."""
BUS_NAME = "org.reframe.SpikeLog"
"""Owned by nobody: the bus answers each call with an error, the monitor still sees it."""


class OutputMissing(RuntimeError):
    """The secondary output is not connected or not enabled."""


@dataclass(frozen=True)
class Rect:
    x: int
    y: int
    width: int
    height: int

    def contains(self, x: float, y: float) -> bool:
        return self.x <= x < self.x + self.width and self.y <= y < self.y + self.height

    def holds(self, other: Rect) -> bool:
        return (
            self.x <= other.x
            and self.y <= other.y
            and other.x + other.width <= self.x + self.width
            and other.y + other.height <= self.y + self.height
        )

    def as_list(self) -> list[int]:
        return [self.x, self.y, self.width, self.height]


_ANSI = re.compile(r"\x1b\[[0-9;]*m")
_GEOMETRY = re.compile(r"Geometry:\s*(-?\d+),(-?\d+)\s+(\d+)x(\d+)")


def parse_outputs(text: str) -> dict[str, Rect]:
    """The enabled, connected outputs of ``kscreen-doctor -o`` (which colours its text)."""
    outputs: dict[str, Rect] = {}
    for block in re.split(r"(?m)^Output: ", _ANSI.sub("", text))[1:]:
        lines = [line.strip() for line in block.splitlines()]
        name = lines[0].split()[1]
        geometry = next((m for line in lines if (m := _GEOMETRY.match(line))), None)
        if "enabled" in lines and "connected" in lines and geometry:
            x, y, width, height = (int(value) for value in geometry.groups())
            outputs[name] = Rect(x, y, width, height)
    return outputs


def outputs() -> dict[str, Rect]:
    text = subprocess.run(
        ["kscreen-doctor", "-o"], capture_output=True, text=True, check=True, timeout=10
    ).stdout
    return parse_outputs(text)


def secondary() -> Rect:
    """The secondary output's rectangle; raises :class:`OutputMissing` when it is not there."""
    found = outputs().get(SECONDARY)
    if found is None:
        raise OutputMissing(f"{SECONDARY} is not connected and enabled: no window is opened")
    return found


def _qdbus(path: str, method: str, *args: str) -> str:
    return subprocess.run(
        ["qdbus6", "org.kde.KWin", path, method, *args],
        capture_output=True,
        text=True,
        check=True,
        timeout=10,
    ).stdout.strip()


def parse_window_info(text: str) -> dict[str, str]:
    """``getWindowInfo``'s answer, one ``key: value`` line each."""
    info: dict[str, str] = {}
    for line in text.splitlines():
        key, sep, value = line.partition(": ")
        if sep:
            info[key] = value
    return info


def window_info(uuid: str) -> dict[str, str]:
    """KWin's own record of a window (``/KWin getWindowInfo``); empty when it is gone."""
    return parse_window_info(_qdbus("/KWin", "org.kde.KWin.getWindowInfo", uuid))


def window_rect(info: dict[str, str]) -> Rect:
    return Rect(*(round(float(info[key])) for key in ("x", "y", "width", "height")))


def input_device(sys_name: str) -> dict[str, str]:
    """The properties of one of KWin's input devices (``eventN``), read only."""
    path = f"/org/kde/KWin/InputDevice/{sys_name}"
    names = [
        "name",
        "pointer",
        "touch",
        "tabletTool",
        "isVirtual",
        "outputName",
        "mapToWorkspace",
        "enabled",
    ]
    return {
        name: _qdbus(path, "org.freedesktop.DBus.Properties.Get", "org.kde.KWin.InputDevice", name)
        for name in names
    }


def input_devices() -> list[str]:
    return _qdbus(
        "/org/kde/KWin/InputDevice", "org.kde.KWin.InputDeviceManager.ListPointers"
    ).split()


def script_loaded(name: str) -> bool:
    return _qdbus("/Scripting", "org.kde.kwin.Scripting.isScriptLoaded", name) == "true"


class Journal:
    """The reports of one session's KWin scripts (method ``r<token>`` of :data:`BUS_NAME`),
    kept in :attr:`seen` in the order they came."""

    def __init__(self) -> None:
        self.token = secrets.token_hex(6)
        self.member = f"r{self.token}"
        self.seen: list[dict[str, Any]] = []
        self._changed = threading.Condition()
        rule = f"type='method_call',interface='{BUS_NAME}',member='{self.member}'"
        self._process = subprocess.Popen(
            ["stdbuf", "-oL", "busctl", "--user", "monitor", "--json=short", f"--match={rule}"],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
        )
        self._reader = threading.Thread(target=self._read, daemon=True)
        self._reader.start()
        if not poll(self._ready, 5.0, step=0.1):
            self.close()
            raise RuntimeError("busctl monitor did not see a test call")

    def send(self, record: dict[str, Any]) -> None:
        """A report of our own, the way the scripts send theirs."""
        subprocess.run(
            [
                "busctl",
                "--user",
                "call",
                BUS_NAME,
                "/",
                BUS_NAME,
                self.member,
                "s",
                json.dumps(record),
            ],
            capture_output=True,
            timeout=5,
        )

    def _ready(self) -> bool:
        self.send({"event": "ping"})
        return self.wait(lambda record: record["event"] == "ping", 0.2) is not None

    def _read(self) -> None:
        assert self._process.stdout is not None
        for line in self._process.stdout:
            message = json.loads(line)
            record = json.loads(message["payload"]["data"][0])
            record["seen"] = time.monotonic()
            with self._changed:
                self.seen.append(record)
                self._changed.notify_all()

    def mark(self) -> int:
        """The position to pass to :meth:`wait` for records that come after this call."""
        with self._changed:
            return len(self.seen)

    def wait(
        self, match: Callable[[dict[str, Any]], bool], limit: float, since: int = 0
    ) -> dict[str, Any] | None:
        """The first record at or after ``since`` that ``match`` accepts, or ``None`` when none
        comes within ``limit`` seconds."""
        deadline = time.monotonic() + limit
        with self._changed:
            while True:
                for record in self.seen[since:]:
                    if match(record):
                        return record
                since = len(self.seen)
                left = deadline - time.monotonic()
                if left <= 0:
                    return None
                self._changed.wait(left)

    def close(self) -> None:
        self._process.terminate()
        try:
            self._process.wait(5)
        except subprocess.TimeoutExpired:
            self._process.kill()
            self._process.wait()


class Script:
    """One KWin script, loaded under a unique plugin name and unloaded by :meth:`unload`."""

    def __init__(self, source: str, name: str) -> None:
        self.name = name
        self._folder = tempfile.TemporaryDirectory(prefix="reframe-spike-kwin-")
        self.path = Path(self._folder.name) / f"{name}.js"
        self.path.write_text(source, encoding="utf-8")
        number = _qdbus("/Scripting", "org.kde.kwin.Scripting.loadScript", str(self.path), name)
        if int(number) < 0:
            self._folder.cleanup()
            raise RuntimeError(f"KWin did not load the script {name} ({number})")
        _qdbus("/Scripting", "org.kde.kwin.Scripting.start")

    def unload(self) -> bool:
        """Unloads the script; returns ``isScriptLoaded`` afterwards (``False`` when gone)."""
        _qdbus("/Scripting", "org.kde.kwin.Scripting.unloadScript", self.name)
        self._folder.cleanup()
        return script_loaded(self.name)


def poll(check: Callable[[], bool], limit: float, step: float = 0.05) -> bool:
    deadline = time.monotonic() + limit
    while time.monotonic() < deadline:
        if check():
            return True
        time.sleep(step)
    return check()
