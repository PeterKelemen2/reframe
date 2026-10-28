"""Windows of the spike (the app, Dolphin, a headed browser) on the secondary output only.

A KWin script, loaded over D-Bus while a session runs, moves each window of the session's
processes to a fixed spot on ``HDMI-A-1`` as KWin adds them (transparent until it is there), and
gives the keyboard back to the window that had it. A process is started behind a gate, so the
script knows its pid before it can map a window. The gate opens only when the script reports
the cursor, KWin's active output and the active window on the secondary output: KWin opens a new
window on its active output and gives it the keyboard. Every window is read back (KWin's
``getWindowInfo``); one that is not inside the secondary output stops the session.

``run -- CMD`` runs a command with placement on for every window of a resource class (for
``cold_start`` and ``cleanup``; each app they start asks the session first); ``open -- CMD``
opens one program, reads its window back and closes it."""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import secrets
import shlex
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from types import FrameType, TracebackType
from typing import Any

from desktop.spike.scripts import kwin

APP_CLASS = "reframe-spike"
"""The spike app's Wayland app id; under XWayland KWin reports the class ``Reframe-spike``."""
SCRIPT = Path(__file__).with_name("session.js")
GATE_WAIT = 30.0
SHOW_LIMIT = 3.0
"""Seconds a new window may stay hidden (not yet on the secondary output)."""
LOAD_LIMIT = 5.0
"""Seconds for a loaded script to report."""
ADMIT_WAIT = 5.0
"""Seconds to wait for the active window or output to come back to the secondary output."""
ADMIT_STEP = 0.5
GATE_ENV = "REFRAME_SPIKE_WINDOW_GATE"
"""Set by ``run``: the folder where :func:`ask` asks the session before an app starts."""
STOP_LIMIT = 15.0
"""Seconds a command of ``run`` gets after SIGINT before its process group is killed."""
# The gate also ends (97) when its folder is removed: that is how a refusal stops it.
_GATE = (
    'i=0; while [ ! -e "$1/go" ]; do [ -d "$1" ] || exit 97; i=$((i+1)); '
    '[ "$i" -gt {limit} ] && exit 97; sleep 0.02; done; rm -rf -- "$1"; shift; exec "$@"'
).replace("{limit}", str(int(GATE_WAIT / 0.02)))
# Linux only; looked up so that the Windows type check passes.
_KILLPG: Any = getattr(os, "killpg", None)

Spot = tuple[int, int, int | None, int | None]
"""x and y inside the secondary output, then the width and height (``None``: the window's)."""
OBSERVE = (None, None, None, None)


class WrongOutput(RuntimeError):
    """A window of the session is not inside the secondary output."""


class Refused(WrongOutput):
    """Nothing was started: a new window would open on another output, or take the keyboard
    from a window there."""


def parse_spot(text: str) -> Spot:
    parts = [int(part) for part in text.split(",")]
    if len(parts) == 2:
        return (parts[0], parts[1], None, None)
    if len(parts) == 4:
        return (parts[0], parts[1], parts[2], parts[3])
    raise argparse.ArgumentTypeError("x,y or x,y,width,height")


def spot_rect(screen: kwin.Rect, spot: Spot, width: int, height: int) -> kwin.Rect:
    return kwin.Rect(screen.x + spot[0], screen.y + spot[1], spot[2] or width, spot[3] or height)


def check_spot(screen: kwin.Rect, spot: Spot) -> None:
    """Refuses a spot whose window would not fit inside the secondary output."""
    if spot[2] is None or spot[3] is None:
        inside = screen.contains(screen.x + spot[0], screen.y + spot[1])
    else:
        inside = screen.holds(spot_rect(screen, spot, 0, 0))
    if not inside:
        raise WrongOutput(f"the spot {spot} is not inside {kwin.SECONDARY} {screen}")


def cursor_refusal(screen: kwin.Rect, loaded: dict[str, Any]) -> str | None:
    x, y = loaded["cursor"]
    if screen.contains(x, y):
        return None
    return f"the cursor is at ({x}, {y}), not on {kwin.SECONDARY}: nothing is started"


def focus_refusal(loaded: dict[str, Any]) -> str | None:
    """Why a new window would open on another output or take the keyboard from a window
    there, by the state in a ``loaded`` record; ``None`` when it would not."""
    if loaded["screen"] != kwin.SECONDARY:
        return f"KWin's active output is {loaded['screen']}: a new window would open there"
    active = loaded["active"]
    if active is not None and active["output"] != kwin.SECONDARY:
        return (
            f"the active window ({active['cls']}) is on {active['output']}: a new window would "
            "take its keyboard"
        )
    return None


@dataclass
class Placed:
    pid: int
    id: str
    added: dict[str, Any]
    """KWin's record when it added the window: its output and frame geometry then."""
    placed: dict[str, Any]
    """The same right after the move was asked for (KWin may apply it later)."""
    shown: dict[str, Any]
    """The same when KWin had it on the secondary output and made it opaque."""
    info: dict[str, str]
    """``getWindowInfo`` read back after the move."""

    @property
    def rect(self) -> kwin.Rect:
        return kwin.window_rect(self.info)

    def summary(self) -> dict[str, Any]:
        return {
            "pid": self.pid,
            "class": self.placed.get("cls"),
            "added": {"output": self.added["output"], "geometry": self.added["geo"]},
            "placed": {"output": self.placed["output"], "geometry": self.placed["geo"]},
            "shown": {"output": self.shown["output"], "geometry": self.shown["geo"]},
            "read_back": self.rect.as_list(),
        }


@dataclass
class Session:
    """Placement on while the ``with`` block runs; the script is unloaded at its end."""

    classes: Mapping[str, Spot] = field(default_factory=dict)
    cursor: bool = False
    """Also report every pointer move (the pointer tool reads them back)."""
    guard: bool = True
    """Give the keyboard back at once when one of our windows on the secondary output takes
    it; off: :meth:`give_back` does it when the caller asks. A window anywhere else gives it
    back at once either way."""
    above: bool = True
    """Keep our windows above the others (``keepAbove``) once they are on the secondary
    output."""
    screen: kwin.Rect = field(init=False)
    journal: kwin.Journal = field(init=False)
    placed: list[Placed] = field(init=False, default_factory=list)
    loaded: dict[str, Any] = field(init=False, default_factory=dict)
    """The last ``loaded`` record: the cursor, the active output and window when it loaded."""
    admitted: list[dict[str, Any]] = field(init=False, default_factory=list)
    """Each admission: the wall-clock time (ms) and the ``loaded`` record it was taken from."""
    _pids: dict[int, Spot | None] = field(init=False, default_factory=dict)
    _script: kwin.Script | None = field(init=False, default=None)
    _loads: int = field(init=False, default=0)
    _lock: threading.Lock = field(init=False, default_factory=threading.Lock)
    _failure: str | None = field(init=False, default=None)
    _watcher: threading.Thread | None = field(init=False, default=None)
    _stop: threading.Event = field(init=False, default_factory=threading.Event)
    _gates: list[Path] = field(init=False, default_factory=list)
    _added: dict[str, dict[str, Any]] = field(init=False, default_factory=dict)
    _moves: dict[str, dict[str, Any]] = field(init=False, default_factory=dict)
    _waiting: dict[str, float] = field(init=False, default_factory=dict)
    """Windows added and not yet shown, with the time KWin's record came."""
    names: list[str] = field(init=False, default_factory=list)
    """Every plugin name this session loaded (each must be unloaded at the end)."""

    def __enter__(self) -> Session:
        self.screen = kwin.secondary()
        for spot in self.classes.values():
            check_spot(self.screen, spot)
        self.journal = kwin.Journal()
        try:
            self._load()
        except BaseException:
            self._close()
            raise
        self._watcher = threading.Thread(target=self._watch, daemon=True)
        self._watcher.start()
        return self

    def __exit__(
        self,
        kind: type[BaseException] | None,
        error: BaseException | None,
        trace: TracebackType | None,
    ) -> None:
        self._stop.set()
        if self._watcher is not None:
            self._watcher.join(5)
        self._close()

    def _close(self) -> None:
        try:
            with self._lock:
                self._stop.set()
                if self._script is not None:
                    script, self._script = self._script, None
                    script.unload()
        finally:
            self.journal.close()
            for gate in self._gates:
                shutil.rmtree(gate, ignore_errors=True)

    def unloaded(self) -> dict[str, bool]:
        """``isScriptLoaded`` of every plugin name of the session (all ``False`` at the end)."""
        return {name: kwin.script_loaded(name) for name in self.names}

    def give_back(self) -> None:
        """Activates the window that had the keyboard before ours, if one of ours has it now
        (the script does that when it loads)."""
        self._load()

    @property
    def keep(self) -> str | None:
        """The window that has the keyboard and is not one of ours, as the script last saw it."""
        for record in reversed(self.journal.seen):
            if record["event"] == "loaded" and record["keep"]:
                return str(record["keep"]["id"])
            if record["event"] == "active":
                return str(record["window"]["id"])
        return None

    def _load(self) -> dict[str, Any]:
        """Loads the script again with the current pids; its ``loaded`` record."""
        with self._lock:
            if self._stop.is_set():
                raise RuntimeError("the session has ended: no script is loaded")
            if self._script is not None:
                script, self._script = self._script, None
                script.unload()
            self._loads += 1
            config = {
                "bus": kwin.BUS_NAME,
                "member": self.journal.member,
                "script": self._loads,
                "secondary": kwin.SECONDARY,
                "pids": {str(pid): list(spot or OBSERVE) for pid, spot in self._pids.items()},
                "classes": {name: list(spot) for name, spot in self.classes.items()},
                "cursor": self.cursor,
                "guard": self.guard,
                "above": self.above,
                "keep": self.keep,
            }
            name = f"reframe-spike-{self.journal.token}-{self._loads}"
            self.names.append(name)
            since = self.journal.mark()
            self._script = kwin.Script(script_source(config), name)
            number = self._loads
        loaded = self.journal.wait(
            lambda record: record["event"] == "loaded" and record["script"] == number,
            LOAD_LIMIT,
            since,
        )
        if loaded is None:
            raise RuntimeError("the KWin script did not report that it is loaded")
        self.loaded = loaded
        return loaded

    def admit(self) -> None:
        """Returns when a new window would open on the secondary output and take the keyboard
        from a window there; raises :class:`Refused` when not, at once for the cursor, after
        :data:`ADMIT_WAIT` for the active window or output (the script is loaded again to see
        them)."""
        loaded = self.loaded
        deadline = time.monotonic() + ADMIT_WAIT
        while True:
            reason = cursor_refusal(self.screen, loaded)
            if reason is not None:
                raise Refused(reason)
            reason = focus_refusal(loaded)
            if reason is None:
                self.admitted.append({"ms": round(time.time() * 1000), "loaded": loaded})
                return
            if time.monotonic() >= deadline:
                raise Refused(f"{reason}; nothing is started")
            time.sleep(ADMIT_STEP)
            loaded = self._load()

    def spawn(
        self, argv: Sequence[str | bytes], spot: Spot | None, **popen: Any
    ) -> subprocess.Popen[bytes]:
        """Starts ``argv`` behind the gate; it runs once the script knows its pid and
        :meth:`admit` passes. Otherwise it never runs, the gate is gone and the call raises.
        With ``spot`` ``None`` the script does not move the window: it only shows it when the
        program or KWin put it on the secondary output."""
        if spot is not None:
            check_spot(self.screen, spot)
        gate = Path(tempfile.mkdtemp(prefix="reframe-spike-gate-"))
        try:
            process: subprocess.Popen[bytes] = subprocess.Popen(
                ["sh", "-c", _GATE, "gate", str(gate), *argv], **popen
            )
        except BaseException:
            shutil.rmtree(gate, ignore_errors=True)
            raise
        self._pids[process.pid] = spot
        try:
            self._load()
            self.admit()
            (gate / "go").touch()
        except BaseException:
            self._pids.pop(process.pid, None)
            shutil.rmtree(gate, ignore_errors=True)
            discard(process)
            raise
        return process

    def wrapper(self, binary: str | os.PathLike[str], spot: Spot) -> Path:
        """An executable that runs ``binary`` behind the gate, for a launcher that starts the
        program itself (Playwright's ``executablePath``). When the gate is not opened, the
        executable ends with 97 and :attr:`failure` says why."""
        check_spot(self.screen, spot)
        gate = Path(tempfile.mkdtemp(prefix="reframe-spike-gate-"))
        self._gates.append(gate)
        script = gate / "launch"
        limit = int(GATE_WAIT / 0.02)
        script.write_text(
            "#!/bin/sh\n"
            f'gate={shlex.quote(str(gate))}\necho $$ > "$gate/pid.new" && mv "$gate/pid.new" '
            '"$gate/pid"\n'
            f'i=0; while [ ! -e "$gate/go" ]; do [ -d "$gate" ] || exit 97; i=$((i+1)); '
            f'[ "$i" -gt {limit} ] && exit 97; sleep 0.02; done\nrm -rf -- "$gate"\n'
            f'exec {shlex.quote(os.fspath(binary))} "$@"\n',
            encoding="utf-8",
        )
        script.chmod(0o700)
        threading.Thread(target=self._open_gate, args=(gate, spot), daemon=True).start()
        return script

    def _open_gate(self, gate: Path, spot: Spot) -> None:
        pid_file = gate / "pid"
        pid = None
        try:
            if not kwin.poll(lambda: pid_file.exists() or self._stop.is_set(), GATE_WAIT):
                return
            if self._stop.is_set():
                return
            pid = int(pid_file.read_text())
            self._pids[pid] = spot
            self._load()
            self.admit()
            (gate / "go").touch()
            pid = None
        except Exception as error:
            self._failure = f"the gate {gate.name} was not opened: {error}"
        finally:
            if pid is not None:
                self._pids.pop(pid, None)
                shutil.rmtree(gate, ignore_errors=True)
            elif not (gate / "go").exists():
                shutil.rmtree(gate, ignore_errors=True)

    @contextlib.contextmanager
    def gate_service(self) -> Iterator[Path]:
        """A folder where :func:`ask` (another process) asks before it starts a program: each
        question loads the script again and answers with :meth:`admit`'s verdict."""
        folder = Path(tempfile.mkdtemp(prefix="reframe-spike-asks-"))
        done = threading.Event()

        def answer(question: Path) -> None:
            try:
                self._load()
                self.admit()
                verdict = "go"
            except Exception as error:
                verdict = f"no {error}"
            reply = question.with_suffix(".tmp")
            reply.write_text(verdict, encoding="utf-8")
            reply.replace(question.with_suffix(".answer"))
            question.unlink()

        def serve() -> None:
            while not done.is_set():
                for question in sorted(folder.glob("*.ask")):
                    answer(question)
                done.wait(0.02)

        thread = threading.Thread(target=serve, daemon=True)
        thread.start()
        try:
            yield folder
        finally:
            done.set()
            thread.join(10)
            shutil.rmtree(folder, ignore_errors=True)

    def window(self, pid: int, limit: float = 20.0) -> Placed:
        """The first normal window of ``pid`` once KWin showed it on the secondary output and
        ``getWindowInfo`` read it back inside it. Raises :class:`WrongOutput` as soon as any
        window of the session is elsewhere (it stays transparent there)."""
        deadline = time.monotonic() + limit
        while time.monotonic() < deadline:
            self._raise_failure()
            for placed in self.placed:
                if placed.pid == pid and (placed.added["normal"] or placed.added["dialog"]):
                    return self._settle(placed)
            time.sleep(0.02)
        raise TimeoutError(f"no window of pid {pid} within {limit} s")

    def _settle(self, placed: Placed) -> Placed:
        """Waits until KWin has the window at its spot (the resize waits for the client), then
        reads it back again."""
        self.journal.wait(
            lambda record: record["event"] == "settled" and record["id"] == placed.id,
            SHOW_LIMIT,
        )
        placed.info = kwin.window_info(placed.id)
        if not placed.info or not self.screen.holds(placed.rect):
            raise WrongOutput(f"window {placed.id} read back as {placed.info}")
        return placed

    def _raise_failure(self) -> None:
        if self._failure is not None:
            raise WrongOutput(self._failure)

    @property
    def failure(self) -> str | None:
        return self._failure

    def _watch(self) -> None:
        done = 0
        while not self._stop.is_set():
            new = self.journal.seen[done:]
            done += len(new)
            self._check(new, time.monotonic())
            time.sleep(0.01)

    def _check(self, records: list[dict[str, Any]], now: float) -> None:
        """Takes the script's new records: a window that is shown is read back, and the
        failure is set for a window added, read back or seen (opaque) off the secondary
        output, or not shown there within :data:`SHOW_LIMIT` of being added."""
        for record in records:
            event, key = record["event"], str(record.get("id"))
            if event == "added":
                self._added[key] = record
                self._waiting[key] = record["seen"]
                if record["output"] != kwin.SECONDARY:
                    self._failure = f"window {key} was added on {record['output']}: {record}"
            elif event == "placed":
                self._moves[key] = record
            elif event == "shown":
                self._waiting.pop(key, None)
                info = kwin.window_info(key)
                added = self._added[key]
                entry = Placed(
                    record["pid"], key, added, self._moves.get(key, record), record, info
                )
                if not info or not self.screen.holds(entry.rect):
                    self._failure = f"window {key} read back as {info or 'gone'}"
                self.placed.append(entry)
            elif event in ("moved", "output") and record["opacity"] > 0:
                if record["output"] != kwin.SECONDARY:
                    self._failure = f"window {key} moved to {record['output']}"
            elif event == "removed":
                self._waiting.pop(key, None)
        for key, since in self._waiting.items():
            if now - since > SHOW_LIMIT:
                self._failure = (
                    f"window {key} was not shown on {kwin.SECONDARY}: {self._added[key]}"
                )


def script_source(config: Mapping[str, Any]) -> str:
    """``session.js`` with ``config`` in place of ``CONFIG``."""
    return SCRIPT.read_text(encoding="utf-8").replace(
        "const C = CONFIG;", f"const C = {json.dumps(config)};"
    )


def ask(folder: Path, limit: float = 60.0) -> None:
    """Asks the session of ``windows run`` (its :meth:`Session.gate_service` folder) whether a
    program may open a window now; raises :class:`Refused` when not."""
    token = secrets.token_hex(6)
    draft = folder / f"{token}.new"
    draft.write_text("", encoding="utf-8")
    draft.replace(folder / f"{token}.ask")
    answer = folder / f"{token}.answer"
    if not kwin.poll(answer.exists, limit, step=0.01):
        raise Refused(f"the window session did not answer within {limit} s")
    verdict = answer.read_text(encoding="utf-8")
    answer.unlink()
    if verdict != "go":
        raise Refused(verdict.removeprefix("no "))


def discard(process: subprocess.Popen[Any], limit: float = 2.0) -> None:
    """Waits for a gated process whose gate was removed (it ends with 97), kills it if it does
    not, and closes its pipes."""
    try:
        process.wait(limit)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()
    for stream in (process.stdin, process.stdout, process.stderr):
        if stream is not None:
            stream.close()


def reap(process: subprocess.Popen[Any], limit: float) -> int:
    """Waits ``limit`` for a process that was asked to stop, then kills it; the exit code."""
    try:
        return process.wait(limit)
    except subprocess.TimeoutExpired:
        process.kill()
        return process.wait()


def terminate(process: subprocess.Popen[Any], limit: float = 10.0) -> int:
    """SIGTERM, then SIGKILL after ``limit``; the exit code."""
    if process.poll() is None:
        process.terminate()
        try:
            return process.wait(limit)
        except subprocess.TimeoutExpired:
            process.kill()
    return process.wait()


def stop_group(process: subprocess.Popen[Any], limit: float = STOP_LIMIT) -> int:
    """SIGINT to the process group of ``process`` (its own, see ``run``), SIGKILL to the group
    after ``limit``; the exit code."""
    if process.poll() is None:
        with contextlib.suppress(ProcessLookupError):
            _KILLPG(process.pid, signal.SIGINT)
        try:
            return process.wait(limit)
        except subprocess.TimeoutExpired:
            pass
    with contextlib.suppress(ProcessLookupError):
        _KILLPG(process.pid, getattr(signal, "SIGKILL"))  # noqa: B009
    return process.wait()


def _interrupt(number: int, frame: FrameType | None) -> None:
    raise KeyboardInterrupt(f"signal {number}")


def stop_on_signals() -> None:
    """SIGTERM and SIGHUP end the run as Ctrl+C does, so every ``with`` block closes: the
    KWin script is unloaded, the monitor and the programs stop, the temporary folders go."""
    for name in ("SIGTERM", "SIGHUP"):
        number = getattr(signal, name, None)
        if number is not None:
            signal.signal(number, _interrupt)


def print_session(session: Session) -> None:
    for placed in session.placed:
        print(json.dumps({"window": placed.summary()}))
    for admission in session.admitted:
        loaded = admission["loaded"]
        state = {key: loaded[key] for key in ("cursor", "screen", "active")}
        print(json.dumps({"admitted": {"ms": admission["ms"], **state}}))
    shown = ("loaded", "kept_active", "active", "stray")
    for record in session.journal.seen:
        if record["event"] in shown:
            record = {key: value for key, value in record.items() if key not in ("seen", "t")}
            print(json.dumps({"focus": record}))
    for record in session.journal.seen:
        if record["event"] == "added":
            # The time from the last admission to KWin adding the window: the cursor or the
            # keyboard can still move to another output in that time.
            before = [a["ms"] for a in session.admitted if a["ms"] <= record["t"]]
            after = record["t"] - before[-1] if before else None
            print(json.dumps({"added_after_admission_ms": after, "output": record["output"]}))
    print(json.dumps({"scripts_loaded_after": session.unloaded()}))


def run(command: Sequence[str], class_name: str, spot: Spot) -> int:
    with Session(classes={class_name: spot}) as session:
        session.admit()
        with session.gate_service() as asks:
            env = os.environ | {GATE_ENV: str(asks)}
            process = subprocess.Popen(command, env=env, process_group=0)
            try:
                while process.poll() is None:
                    if session.failure is not None:
                        print(f"windows: {session.failure}; stopping the command", file=sys.stderr)
                        break
                    time.sleep(0.05)
            finally:
                code = stop_group(process)
    print_session(session)
    return code if session.failure is None else 1


def open_window(command: Sequence[str], spot: Spot, seconds: float) -> int:
    with Session() as session:
        process = session.spawn(command, spot)
        try:
            placed = session.window(process.pid)
            print(json.dumps({"window": placed.summary()}))
            time.sleep(seconds)
            print(json.dumps({"read_back_before_close": kwin.window_info(placed.id) != {}}))
        finally:
            print(json.dumps({"exit": terminate(process)}))
    print_session(session)
    return 0 if session.failure is None else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    run_parser = commands.add_parser("run", help="run a command with placement on")
    run_parser.add_argument("--class", dest="class_name", default=APP_CLASS)
    run_parser.add_argument("--spot", type=parse_spot, default=(40, 40, None, None))
    run_parser.add_argument("argv", nargs=argparse.REMAINDER)
    open_parser = commands.add_parser("open", help="open one program's window, then close it")
    open_parser.add_argument("--spot", type=parse_spot, default=(40, 40, 1280, 800))
    open_parser.add_argument("--seconds", type=float, default=2.0)
    open_parser.add_argument("argv", nargs=argparse.REMAINDER)
    commands.add_parser("outputs", help="the outputs and the secondary one")
    args = parser.parse_args(argv)
    if args.command == "outputs":
        print(json.dumps({name: rect.as_list() for name, rect in kwin.outputs().items()}))
        print(json.dumps({"secondary": kwin.secondary().as_list()}))
        return 0
    command = args.argv[1:] if args.argv[:1] == ["--"] else args.argv
    if not command:
        parser.error("give the command after --")
    stop_on_signals()
    try:
        if args.command == "run":
            return run(command, args.class_name, args.spot)
        return open_window(command, args.spot, args.seconds)
    except Refused as refused:
        print(f"windows: {refused}", file=sys.stderr)
        return 1
    except KeyboardInterrupt as interrupt:
        print(f"windows: stopped ({interrupt})", file=sys.stderr)
        return 130


if __name__ == "__main__":
    sys.exit(main())
