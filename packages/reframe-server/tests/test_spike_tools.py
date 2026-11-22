"""The guards of the desktop spike's window and pointer tools (``desktop/spike/scripts``): the
real pointer never goes, or stays pressed, outside the secondary output; no program starts
while its window would open on another output or take the keyboard there; a window there is
never shown; a session ends cleanly on SIGTERM; the app and its sidecars stay in their
temporary folders. No display is needed: KWin is faked."""

from __future__ import annotations

import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("fcntl", reason="the desktop spike's scripts run on Linux only")

REPO = Path(__file__).resolve().parents[3]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from desktop.spike.scripts import app as spike_app  # noqa: E402
from desktop.spike.scripts import (  # noqa: E402
    browser,
    cleanup,
    cold_start,
    kwin,
    page_cache,
    pointer,
    sidecar,
    windows,
)

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


def test_a_window_that_kwin_added_on_another_output_stops_the_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # KWin added it on DP-1 (and gave it the keyboard there); shown on HDMI-A-1 later or not,
    # the session stops.
    session = make_session(monkeypatch, INSIDE)
    session._check([record("added", output="DP-1", opacity=0), record("shown")], 100.1)
    with pytest.raises(windows.WrongOutput):
        session.window(7, limit=0.2)


# The session's gate, against a fake KWin layer (no compositor, no D-Bus).

linux_only = pytest.mark.skipif(
    sys.platform != "linux", reason="the spike's window tools run on Linux only"
)
SIGKILL = int(getattr(signal, "SIGKILL", 9))
SPOT: windows.Spot = (40, 40, 1280, 800)
VSCODE = {"id": "{v}", "cls": "com.microsoft.VSCode", "output": "HDMI-A-1"}
HARUNA = {"id": "{h}", "cls": "org.kde.haruna", "output": "DP-1"}


def kwin_state(
    cursor: tuple[int, int] = (300, 400),
    screen: str = "HDMI-A-1",
    active: dict[str, str] | None = VSCODE,
) -> dict[str, Any]:
    """What a loaded script reports: the cursor, KWin's active output and the active window."""
    return {"cursor": list(cursor), "screen": screen, "active": active}


class FakeJournal:
    def __init__(self) -> None:
        self.token = "t0"
        self.member = "rt0"
        self.seen: list[dict[str, Any]] = []

    def mark(self) -> int:
        return len(self.seen)

    def wait(self, match: Any, limit: float, since: int = 0) -> dict[str, Any] | None:
        return next((entry for entry in self.seen[since:] if match(entry)), None)

    def close(self) -> None:
        pass


class FakeKWin:
    """The n-th script a session loads reports ``states[n]`` (the last one again after that);
    a state of ``None`` reports nothing."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch, *states: dict[str, Any] | None) -> None:
        self.journal = FakeJournal()
        self.states = list(states)
        self.loaded: list[str] = []
        self.unloaded: list[str] = []
        monkeypatch.setattr(kwin, "secondary", lambda: SECONDARY)
        monkeypatch.setattr(kwin, "Journal", lambda: self.journal)
        monkeypatch.setattr(kwin, "Script", self.script)
        monkeypatch.setattr(kwin, "script_loaded", lambda name: name not in self.unloaded)
        monkeypatch.setattr(windows, "LOAD_LIMIT", 0.2)
        monkeypatch.setattr(windows, "ADMIT_WAIT", 0.3)
        monkeypatch.setattr(windows, "ADMIT_STEP", 0.05)

    def script(self, source: str, name: str) -> Any:
        state = self.states[min(len(self.loaded), len(self.states) - 1)]
        self.loaded.append(name)
        if state is not None:
            number = int(name.rsplit("-", 1)[1])
            loaded = {"event": "loaded", "script": number, "keep": None, "seen": 0.0}
            self.journal.seen.append(loaded | state)
        unloaded = self.unloaded

        class Loaded:
            def unload(self) -> bool:
                unloaded.append(name)
                return False

        return Loaded()


@pytest.fixture
def started(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> Iterator[list[subprocess.Popen[Any]]]:
    """Every process started through ``subprocess.Popen``; temporary folders go to
    ``tmp_path/tmp``."""
    folder = tmp_path / "tmp"
    folder.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(folder))
    processes: list[subprocess.Popen[Any]] = []
    real = subprocess.Popen

    def recording(*args: Any, **kwargs: Any) -> subprocess.Popen[Any]:
        process = real(*args, **kwargs)
        processes.append(process)
        return process

    monkeypatch.setattr(subprocess, "Popen", recording)
    yield processes
    for process in processes:
        if process.poll() is None:
            process.kill()
            process.wait()


def leftovers(tmp_path: Path) -> list[str]:
    return sorted(path.name for path in (tmp_path / "tmp").glob("reframe-spike-*"))


REFUSED = {
    "the cursor on DP-1": kwin_state(cursor=(2500, 400)),
    "KWin's active output DP-1": kwin_state(screen="DP-1", active=None),
    "the active window on DP-1": kwin_state(active=HARUNA),
}


@linux_only
@pytest.mark.parametrize("refused", REFUSED.values(), ids=REFUSED)
def test_no_program_starts_while_its_window_would_open_or_take_the_keyboard_elsewhere(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    started: list[subprocess.Popen[Any]],
    refused: dict[str, Any],
) -> None:
    FakeKWin(monkeypatch, kwin_state(), refused)
    marker = tmp_path / "ran"
    with windows.Session() as session, pytest.raises(windows.Refused):
        session.spawn(["sh", "-c", f"touch {marker}"], SPOT)
    time.sleep(0.2)
    assert not marker.exists()
    assert [process.returncode is not None for process in started] == [True]
    assert leftovers(tmp_path) == []


@linux_only
def test_a_program_starts_once_the_keyboard_has_left_the_other_output(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, started: list[subprocess.Popen[Any]]
) -> None:
    FakeKWin(monkeypatch, kwin_state(), kwin_state(active=HARUNA), kwin_state())
    marker = tmp_path / "ran"
    with windows.Session() as session:
        assert session.spawn(["sh", "-c", f"touch {marker}"], SPOT).wait(5) == 0
    assert marker.exists()


@linux_only
def test_a_script_that_does_not_report_opens_no_gate_and_leaves_nothing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, started: list[subprocess.Popen[Any]]
) -> None:
    FakeKWin(monkeypatch, kwin_state(), None)
    marker = tmp_path / "ran"
    with windows.Session() as session, pytest.raises(RuntimeError, match="did not report"):
        session.spawn(["sh", "-c", f"touch {marker}"], SPOT)
    time.sleep(0.2)
    assert not marker.exists()
    assert [process.returncode is not None for process in started] == [True]
    assert leftovers(tmp_path) == []


@linux_only
@pytest.mark.parametrize(
    ("state", "runs"),
    [(kwin_state(), True), (REFUSED["the cursor on DP-1"], False)],
    ids=["admitted", "refused"],
)
def test_a_launcher_gate_opens_only_when_the_window_would_open_on_hdmi(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    started: list[subprocess.Popen[Any]],
    state: dict[str, Any],
    runs: bool,
) -> None:
    FakeKWin(monkeypatch, kwin_state(), state)
    marker = tmp_path / "ran"
    with windows.Session() as session:
        launch = session.wrapper("/bin/sh", SPOT)
        result = subprocess.run([launch, "-c", f"touch {marker}"], timeout=10)
        assert (session.failure is None) is runs
    assert result.returncode == (0 if runs else 97)
    assert marker.exists() is runs
    assert leftovers(tmp_path) == []


@linux_only
def test_a_launcher_that_never_ran_leaves_no_gate_folder(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, started: list[subprocess.Popen[Any]]
) -> None:
    FakeKWin(monkeypatch, kwin_state())
    with windows.Session() as session:
        session.wrapper("/bin/sh", SPOT)
    assert leftovers(tmp_path) == []


@linux_only
@pytest.mark.parametrize(
    ("state", "starts"),
    [(kwin_state(), True), (REFUSED["the cursor on DP-1"], False)],
    ids=["admitted", "refused"],
)
def test_an_app_started_under_windows_run_asks_the_session_first(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    started: list[subprocess.Popen[Any]],
    state: dict[str, Any],
    starts: bool,
) -> None:
    FakeKWin(monkeypatch, kwin_state(), state)
    monkeypatch.setattr(spike_app, "APP", Path("/bin/true"))
    with windows.Session() as session, session.gate_service() as asks:
        monkeypatch.setenv(windows.GATE_ENV, str(asks))
        if starts:
            spike_app.start(tmp_path / "home").process.communicate(timeout=5)
        else:
            with pytest.raises(windows.Refused, match="cursor"):
                spike_app.start(tmp_path / "home")
    assert len(started) == (1 if starts else 0)


# session.js against a fake KWin (node, no compositor).

FAKE_KWIN = REPO / "desktop" / "spike" / "scripts" / "session_fake_kwin.mjs"
SCREENS = [
    {"name": "HDMI-A-1", "geo": [0, 0, 1920, 1080]},
    {"name": "DP-1", "geo": [1920, 0, 1920, 1080]},
]
APP_PID = 4242
needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")


def run_script(tmp_path: Path, scenario: dict[str, Any], **config: Any) -> dict[str, Any]:
    """Runs session.js on a fake KWin; the window of :data:`APP_PID` goes to :data:`SPOT`."""
    source = windows.script_source(
        {
            "bus": kwin.BUS_NAME,
            "member": "rtest",
            "script": 1,
            "secondary": kwin.SECONDARY,
            "pids": {str(APP_PID): list(SPOT)},
            "classes": {},
            "cursor": False,
            "guard": True,
            "above": True,
            "keep": None,
        }
        | config
    )
    script, plan = tmp_path / "session.js", tmp_path / "scenario.json"
    script.write_text(source, encoding="utf-8")
    plan.write_text(json.dumps({"screens": SCREENS} | scenario), encoding="utf-8")
    answer = subprocess.run(
        ["node", str(FAKE_KWIN), str(script), str(plan)],
        capture_output=True,
        text=True,
        timeout=30,
        check=True,
    )
    result: dict[str, Any] = json.loads(answer.stdout)
    return result


def owner_window(spec: dict[str, str], geo: list[int]) -> dict[str, Any]:
    return {"id": spec["id"], "pid": 1000, "cls": spec["cls"], "geo": geo}


@needs_node
def test_the_script_keeps_a_window_transparent_and_not_above_until_it_is_shown_on_hdmi(
    tmp_path: Path,
) -> None:
    scenario = {
        "cursor": [700, 500],
        "windows": [owner_window(VSCODE, [0, 0, 1920, 1080])],
        "active": VSCODE["id"],
        "add": [
            {"id": "{app}", "pid": APP_PID, "cls": "reframe-spike", "geo": [510, 186, 900, 708]}
        ],
    }
    result = run_script(tmp_path, scenario)
    window = result["windows"]["{app}"]
    above = [step for step in window["history"] if step["set"] == "keepAbove" and step["value"]]
    assert above
    assert all(step["opacity"] == 1 and step["output"] == "HDMI-A-1" for step in above)
    assert (window["geo"], window["opacity"]) == ([40, 40, 1280, 800], 1)
    assert result["active"] == VSCODE["id"]
    loaded = next(entry for entry in result["records"] if entry["event"] == "loaded")
    assert (loaded["cursor"], loaded["screen"], loaded["active"]) == (
        [700, 500],
        "HDMI-A-1",
        VSCODE,
    )


@needs_node
def test_the_script_never_shows_a_window_that_kwin_added_on_another_output(
    tmp_path: Path,
) -> None:
    # As in the incident: the movie player on DP-1 has the keyboard, the guard is off (as in
    # the drag check), and KWin adds our window on DP-1 and activates it.
    scenario = {
        "cursor": [2500, 500],
        "windows": [owner_window(HARUNA, [1920, 0, 1920, 1080])],
        "active": HARUNA["id"],
        "add": [
            {"id": "{app}", "pid": APP_PID, "cls": "reframe-spike", "geo": [2430, 163, 900, 708]}
        ],
    }
    result = run_script(tmp_path, scenario, guard=False)
    window = result["windows"]["{app}"]
    assert all(step["opacity"] == 0 for step in window["history"] if step["set"] == "opacity")
    assert not any(step["value"] for step in window["history"] if step["set"] == "keepAbove")
    assert window["minimized"]
    assert result["active"] == HARUNA["id"]
    events = [entry["event"] for entry in result["records"]]
    # The keyboard goes back in KWin's activation, before the window is even added.
    assert events.index("kept_active") < events.index("added")
    assert [event for event in events if event in ("stray", "shown")] == ["stray"]


# SIGTERM ends a window session cleanly.

DRIVER = r"""
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, sys.argv[1])
from desktop.spike.scripts import kwin, windows

log = Path(sys.argv[2])


def note(*words):
    with log.open("a") as file:
        file.write(" ".join(map(str, words)) + "\n")


class Journal:
    def __init__(self):
        global journal
        journal = self
        self.token, self.member, self.seen = "t", "rt", []
        self.monitor = subprocess.Popen(["sleep", "600"])  # in place of busctl monitor
        note("monitor", self.monitor.pid)

    def mark(self):
        return len(self.seen)

    def wait(self, match, limit, since=0):
        return next((r for r in self.seen[since:] if match(r)), None)

    def close(self):
        self.monitor.terminate()
        self.monitor.wait()


class Script:
    def __init__(self, source, name):
        self.name = name
        note("load", name)
        state = {"cursor": [300, 300], "screen": "HDMI-A-1", "active": None, "keep": None}
        number = int(name.rsplit("-", 1)[1])
        journal.seen.append({"event": "loaded", "script": number, "seen": 0.0, **state})

    def unload(self):
        note("unload", self.name)
        return False


kwin.secondary = lambda: kwin.Rect(0, 0, 1920, 1080)
kwin.Journal, kwin.Script = Journal, Script
kwin.script_loaded = lambda name: False
sys.exit(windows.main(sys.argv[3:]))
"""
"""``windows.main`` with KWin replaced: each script load and unload is noted in a log, and
``sleep`` stands in for the ``busctl monitor`` of the journal."""


def running(pid: int) -> bool:
    try:
        state = Path(f"/proc/{pid}/stat").read_text().rsplit(") ", 1)[1].split()[0]
    except FileNotFoundError:
        return False
    return state != "Z"


@linux_only
def test_sigterm_to_windows_run_unloads_the_script_and_stops_the_monitor_and_the_command(
    tmp_path: Path,
) -> None:
    driver, log, pid_file = tmp_path / "driver.py", tmp_path / "log", tmp_path / "command.pid"
    driver.write_text(DRIVER, encoding="utf-8")
    temporary = tmp_path / "tmp"
    temporary.mkdir()
    command = ["sh", "-c", f"echo $$ > {pid_file}.new && mv {pid_file}.new {pid_file}; sleep 60"]
    runner = subprocess.Popen(
        [sys.executable, str(driver), str(REPO), str(log), "run", "--", *command],
        env=os.environ | {"TMPDIR": str(temporary)},
    )
    pids: list[int] = []
    try:
        deadline = time.monotonic() + 20
        while not pid_file.exists():
            assert runner.poll() is None
            assert time.monotonic() < deadline, "the command did not start"
            time.sleep(0.05)
        notes = [line.split() for line in log.read_text().splitlines()]
        pids = [int(pid_file.read_text()), *(int(n[1]) for n in notes if n[0] == "monitor")]
        runner.send_signal(signal.SIGTERM)
        runner.wait(30)
        notes = [line.split() for line in log.read_text().splitlines()]
        loaded = [n[1] for n in notes if n[0] == "load"]
        assert loaded
        assert [n[1] for n in notes if n[0] == "unload"] == loaded
        assert [pid for pid in pids if running(pid)] == []
        assert sorted(path.name for path in temporary.iterdir()) == []
    finally:
        if runner.poll() is None:
            runner.kill()
            runner.wait()
        for pid in pids:
            if running(pid):
                os.kill(pid, SIGKILL)


# The app and its sidecars stay in their temporary folders.


@pytest.mark.parametrize("start", ["sidecar", "app"])
def test_every_spike_sidecar_has_the_hardware_tests_off(tmp_path: Path, start: str) -> None:
    home = tmp_path / "home"
    if start == "sidecar":
        sidecar.isolated_env(home, "token")
    else:
        spike_app.environment(home, unfrozen=False, extra=None)
    settings = json.loads((home / "config" / "settings.json").read_text(encoding="utf-8"))
    assert settings["encoders"]["hardware_tests"] is False


def test_the_app_keeps_its_webkit_profile_and_caches_in_its_home_with_the_owners_gtk_look(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    owner = tmp_path / "owner-config"
    (owner / "gtk-3.0").mkdir(parents=True)
    (owner / "gtk-3.0" / "settings.ini").write_text("[Settings]\ngtk-theme-name=Breeze\n")
    (owner / "dconf").mkdir()
    (owner / "dconf" / "user").write_bytes(b"GVariant")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(owner))
    home = tmp_path / "home"
    env = spike_app.environment(home, unfrozen=False, extra=None)
    for name in ("XDG_DATA_HOME", "XDG_CACHE_HOME", "XDG_CONFIG_HOME", "XDG_STATE_HOME"):
        assert Path(env[name]).is_relative_to(home), name
    config = Path(env["XDG_CONFIG_HOME"])
    assert (
        config / "gtk-3.0" / "settings.ini"
    ).read_text() == "[Settings]\ngtk-theme-name=Breeze\n"
    assert (config / "dconf" / "user").read_bytes() == b"GVariant"


# Processes are stopped, and only the ones that were started.


@linux_only
def test_cleanup_does_not_kill_a_process_that_has_a_tracked_pid_but_started_later() -> None:
    process = subprocess.Popen(["sleep", "30"])
    try:
        itself = cleanup.Tracked.of(process.pid)
        cleanup.kill([cleanup.Tracked(process.pid, itself.start - 100)])
        with pytest.raises(subprocess.TimeoutExpired):
            process.wait(0.5)
        cleanup.kill([itself])
        assert process.wait(5) == -SIGKILL
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()


@linux_only
@needs_node
def test_a_node_script_that_ignores_sigterm_is_killed_when_the_check_stops_it(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, started: list[subprocess.Popen[Any]]
) -> None:
    script = tmp_path / "stubborn.mjs"
    script.write_text('process.on("SIGTERM", () => {});\nsetInterval(() => {}, 1000);\n')
    monkeypatch.setattr(browser, "STOP_LIMIT", 0.5)
    began = time.monotonic()

    def stop() -> str | None:
        return "a window left HDMI-A-1" if time.monotonic() - began > 1 else None

    with pytest.raises(RuntimeError, match="stopped"):
        browser.node(script, [], stop=stop)
    assert [process.returncode for process in started] == [-SIGKILL]


FAKE_SIDECAR = r"""
import json
import signal
from http.server import BaseHTTPRequestHandler, HTTPServer

signal.signal(signal.SIGTERM, signal.SIG_IGN)


class Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        self.send_response(204)
        self.end_headers()

    def log_message(self, *args):
        pass


server = HTTPServer(("127.0.0.1", 0), Handler)
print(json.dumps({"event": "ready", "port": server.server_address[1]}), flush=True)
server.serve_forever()
"""
"""A sidecar that answers the shutdown request with 204 and goes on running."""


@linux_only
def test_cold_start_kills_a_sidecar_that_does_not_stop_after_the_shutdown_request(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, started: list[subprocess.Popen[Any]]
) -> None:
    fake = tmp_path / "sidecar.py"
    fake.write_text(FAKE_SIDECAR, encoding="utf-8")
    monkeypatch.setattr(sidecar, "frozen_command", lambda: [sys.executable, str(fake)])
    monkeypatch.setattr(cold_start, "STOP_LIMIT", 0.5)
    cold_start.run_sidecar(cold_start.Case("sidecar"), tmp_path / "xdg")
    assert [process.returncode for process in started] == [-SIGKILL]


@pytest.mark.parametrize(("target", "starts"), [("app", 2), ("sidecar", 1)])
def test_an_evicted_app_case_fills_its_new_caches_with_a_start_that_is_not_counted(
    monkeypatch: pytest.MonkeyPatch, target: str, starts: int
) -> None:
    folders: list[Path] = []

    def start(case: cold_start.Case, xdg: Path) -> dict[str, Any]:
        folders.append(xdg)
        return {"total": 1.0}

    monkeypatch.setattr(cold_start, f"run_{target}", start)
    monkeypatch.setattr(page_cache, "resident", lambda paths: page_cache.Resident(0, 0))
    monkeypatch.setattr(page_cache, "evict", lambda paths: 0)
    result = cold_start.measure(cold_start.Case(target, cache="evicted"), runs=1)
    assert result["runs"] == 1
    assert len(folders) == starts
    assert len(set(folders)) == 1
