"""Fake ``ffmpeg`` / ``ffprobe`` executables for fault-injection tests.

:func:`make_fake_tools` writes launchers that run :mod:`reframe_testing.fake_ffmpeg` with the
base interpreter. The scenario (:class:`Scenario` and the action helpers) is what the fake
reads. Every invocation is logged, so a test can check the calls and every process the fake
started.
"""

from __future__ import annotations

import codecs
import contextlib
import json
import os
import shlex
import sys
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from reframe.fsretry import replace_file
from reframe_testing import fake_ffmpeg

SCENARIO_ENV = fake_ffmpeg.SCENARIO_ENV
LOG_ENV = fake_ffmpeg.LOG_ENV
MAX_LIFETIME_ENV = fake_ffmpeg.MAX_LIFETIME_ENV
LIFETIME_EXIT_CODE = fake_ffmpeg.LIFETIME_EXIT_CODE
WINDOWS_CRASH_CODE = fake_ffmpeg.WINDOWS_CRASH_CODE
PROGRESS_FIELDS = fake_ffmpeg.PROGRESS_FIELDS
SCRIPT = Path(fake_ffmpeg.__file__).resolve()
DATA_DIR = fake_ffmpeg.DATA_DIR
#: The interpreter that runs the fake: ``sys._base_executable`` (not a venv launcher).
PYTHON = fake_ffmpeg.python_executable()

Tool = Literal["ffmpeg", "ffprobe"]
#: One fake action, as JSON. Build it with the helper functions below.
Action = dict[str, Any]

#: Longest interpreter path that we put on a ``#!`` line (Linux allows 255 bytes since 5.1,
#: older kernels and macOS less).
_MAX_SHEBANG = 120


def stdout(text: str) -> Action:
    """Print ``text`` to stdout."""
    return {"stdout": text}


def stderr(text: str) -> Action:
    """Print ``text`` to stderr."""
    return {"stderr": text}


def stdout_data(name: str) -> Action:
    """Print a captured real-FFmpeg file from ``fake_data/`` to stdout."""
    _check_data(name)
    return {"stdout_data": name}


def stderr_data(name: str) -> Action:
    """Print a captured real-FFmpeg file from ``fake_data/`` to stderr."""
    _check_data(name)
    return {"stderr_data": name}


def sleep(seconds: float) -> Action:
    return {"sleep": seconds}


def hang() -> Action:
    """Sleep until killed, or until ``REFRAME_FAKE_FFMPEG_MAX_LIFETIME`` is over (then exit with
    :data:`LIFETIME_EXIT_CODE`)."""
    return {"hang": True}


def crash(*, signal: str = "SIGSEGV", exit_code: int | None = None) -> Action:
    """Die abruptly: by ``signal`` on POSIX (exit code 0xC0000005 on Windows),
    or with ``os._exit(exit_code)`` if ``exit_code`` is given."""
    return {"crash": {"exit_code": exit_code} if exit_code is not None else {"signal": signal}}


def flood(nbytes: int, stream: Literal["stdout", "stderr"] = "stdout") -> Action:
    """Print ``nbytes`` of 64-byte lines (to test output limits)."""
    return {"flood": {"bytes": nbytes, "stream": stream}}


def spawn_grandchild() -> Action:
    """Start a child process that hangs (to test process-tree kill). Logged with its pid. It
    exits by itself after ``REFRAME_FAKE_FFMPEG_MAX_LIFETIME``."""
    return {"spawn_grandchild": {}}


def progress(
    *,
    blocks: int = 5,
    interval: float = 0.01,
    media_seconds: float = 2.0,
    fps: float = 25.0,
    bytes_per_second: int = 50_000,
    end: bool = True,
    na_fields: Sequence[str] = (),
    na_blocks: int = 0,
) -> Action:
    """Emit ``na_blocks + blocks`` ``-progress`` blocks, one every ``interval`` seconds.

    The destination is the value of ``-progress`` in argv (``pipe:1``, ``pipe:2`` or a file),
    default stdout. Field names and order are :data:`PROGRESS_FIELDS`. The first ``na_blocks``
    blocks are start-up blocks, as real ffmpeg prints them before the encoder returns its first
    packet (``fake_data/progress_null_long``). The fields in ``na_fields`` are ``N/A`` in every
    block.
    """
    unknown = set(na_fields) - set(PROGRESS_FIELDS[:-1])
    if unknown:
        raise ValueError(f"unknown -progress fields: {sorted(unknown)}")
    return {
        "progress": {
            "blocks": blocks,
            "interval": interval,
            "media_seconds": media_seconds,
            "fps": fps,
            "bytes_per_second": bytes_per_second,
            "end": end,
            "na_fields": list(na_fields),
            "na_blocks": na_blocks,
        }
    }


def write_output(nbytes: int = 1024) -> Action:
    """Write ``nbytes`` to the output file (the last argv element, if it is not an option, ``-``
    or ``pipe:``, and not with ``-f null``)."""
    return {"write_output": {"bytes": nbytes}}


def version(version: str | None = None, configuration: str | None = None) -> Action:
    """Print the real captured ``-version`` text, with another version and/or
    ``configuration:`` line."""
    spec: dict[str, str] = {}
    if version is not None:
        spec["version"] = version
    if configuration is not None:
        spec["configuration"] = configuration
    return {"version": spec}


def ignore_sigterm() -> Action:
    """Ignore SIGTERM (POSIX), so a runner must escalate to SIGKILL."""
    return {"on_sigterm": "ignore"}


def exit_on_sigterm(
    exit_code: int = 255, message: str = "Exiting normally, received signal 15.\n"
) -> Action:
    """On SIGTERM, print ``message`` to stderr and exit with ``exit_code`` (like real ffmpeg)."""
    return {"on_sigterm": {"exit_code": exit_code, "stderr": message}}


def exit_now(code: int) -> Action:
    return {"exit": code}


def exec_program(program: str | os.PathLike[str]) -> Action:
    """Run ``program`` (a real ffmpeg, for example) with the same arguments, stdin, stdout and
    stderr, and exit with its exit code (128 + N when signal N ended it on POSIX). A rule
    with no conditions and this action, put last, passes every other call to the real tool."""
    return {"exec": os.fspath(program)}


def _check_data(name: str) -> None:
    if not (DATA_DIR / name).is_file():
        raise FileNotFoundError(f"no captured fake data named {name!r} in {DATA_DIR}")


@dataclass(frozen=True)
class Rule:
    """When argv matches (all given conditions), run ``actions`` and exit with ``exit_code``."""

    actions: Sequence[Action] = ()
    exit_code: int = 0
    tool: Tool | None = None
    argv_has: Sequence[str] = ()
    """Every item must be an exact argv element."""
    argv_contains: Sequence[str] = ()
    """Every item must be a substring of some argv element."""
    argv_regex: str | None = None
    """``re.search`` on the argv joined with single spaces."""

    def to_json(self) -> dict[str, Any]:
        data: dict[str, Any] = {"actions": list(self.actions), "exit_code": self.exit_code}
        if self.tool is not None:
            data["tool"] = self.tool
        if self.argv_has:
            data["argv_has"] = list(self.argv_has)
        if self.argv_contains:
            data["argv_contains"] = list(self.argv_contains)
        if self.argv_regex is not None:
            data["argv_regex"] = self.argv_regex
        return data


@dataclass(frozen=True)
class Scenario:
    """Ordered rules (first match wins). ``defaults``: fall back to the built-in behaviour."""

    rules: Sequence[Rule] = ()
    defaults: bool = True

    def to_json(self) -> dict[str, Any]:
        return {"rules": [r.to_json() for r in self.rules], "defaults": self.defaults}


@dataclass(frozen=True)
class Capture:
    """One real-FFmpeg capture from ``fake_data/captures.json``."""

    name: str
    command: tuple[str, ...]
    exit_code: int
    stdout: str | None
    stderr: str | None
    machine: str | None = None
    build: str | None = None
    """First line of ``-version`` of the binary that made the capture."""
    env: Mapping[str, str] | None = None
    """Extra environment variables of the capture command (for example ``LIBVA_DRIVER_NAME``)."""


def captures() -> dict[str, Capture]:
    """All captures, by name (for example ``hw_hevc_nvenc_no_driver``, ``encoders``)."""
    raw: dict[str, dict[str, Any]] = json.loads(
        (DATA_DIR / "captures.json").read_text(encoding="utf-8")
    )
    return {
        name: Capture(
            name=name,
            command=tuple(entry["command"]),
            exit_code=int(entry["exit_code"]),
            stdout=entry.get("stdout"),
            stderr=entry.get("stderr"),
            machine=entry.get("machine"),
            build=entry.get("build"),
            env=entry.get("env"),
        )
        for name, entry in raw.items()
    }


def library_strings() -> dict[str, list[dict[str, str]]]:
    """``fake_data/library_strings.json``: for each hardware error text, the files of the pinned
    build that contain it. An empty list means the text is not in the build."""
    raw: dict[str, Any] = json.loads(
        (DATA_DIR / "library_strings.json").read_text(encoding="utf-8")
    )
    strings: dict[str, list[dict[str, str]]] = raw["strings"]
    return strings


def captured(
    name: str,
    *,
    argv_has: Sequence[str] | None = None,
    argv_contains: Sequence[str] = (),
    argv_regex: str | None = None,
    tool: Tool | None = None,
    delay: float = 0.0,
) -> Rule:
    """A rule that replays a real capture: same stdout, stderr and exit code.

    Unless ``argv_has``, ``argv_contains`` or ``argv_regex`` is given, it matches the ``-c:v``
    value of the captured command, or else its last element.
    """
    cap = captures()[name]
    if argv_has is None and not argv_contains and argv_regex is None:
        cmd = list(cap.command)
        argv_has = [cmd[cmd.index("-c:v") + 1]] if "-c:v" in cmd else [cmd[-1]]
    actions: list[Action] = []
    if delay:
        actions.append(sleep(delay))
    if cap.stderr:
        actions.append(stderr_data(cap.stderr))
    if cap.stdout:
        actions.append(stdout_data(cap.stdout))
    return Rule(
        actions=actions,
        exit_code=cap.exit_code,
        tool=tool,
        argv_has=tuple(argv_has or ()),
        argv_contains=tuple(argv_contains),
        argv_regex=argv_regex,
    )


@dataclass(frozen=True)
class Invocation:
    role: Literal["main", "grandchild"]
    tool: str
    pid: int
    ppid: int
    argv: tuple[str, ...] = ()
    cwd: str | None = None
    monotonic_ns: int = 0
    """``time.monotonic_ns()`` when the entry was written (a system-wide clock): the sort key."""
    time_ns: int = 0
    """``time.time_ns()`` when the entry was written."""


#: A logged process that started more than this many seconds after its log entry was written
#: is not ours: the OS gave its pid to a new process. psutil's ``create_time`` on Linux is
#: computed from the boot time in whole seconds, so it can be up to 1 s off; on Windows it is
#: exact, and Windows hands a pid out again within milliseconds, so a 2 s margin there kills
#: other tests' processes (another xdist worker's ffmpeg, exit code 15).
_PID_REUSE_TOLERANCE = 0.01 if sys.platform == "win32" else 2.0


def _read_entry(path: Path) -> dict[str, Any] | None:
    """A call-log entry, or ``None`` once it is gone. Windows refuses to open a file for a moment
    while it is being deleted or scanned (``PermissionError``)."""
    for _ in range(100):
        try:
            entry: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return None
        except PermissionError:
            if os.name != "nt":
                raise
            time.sleep(0.01)
        else:
            return entry
    return None if not path.exists() else json.loads(path.read_text(encoding="utf-8"))


@dataclass
class FakeTools:
    """Paths of the fake tools in one directory, plus the scenario and the call log."""

    directory: Path
    ffmpeg: Path
    ffprobe: Path
    scenario_path: Path
    log_dir: Path
    """One JSON file per invocation (see ``fake_ffmpeg``); read with :meth:`invocations`."""

    def set_scenario(self, scenario: Scenario | Mapping[str, Any]) -> None:
        data = scenario.to_json() if isinstance(scenario, Scenario) else dict(scenario)
        tmp = self.scenario_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
        replace_file(tmp, self.scenario_path)  # a fake still reading the old one blocks Windows

    def env(self, base: Mapping[str, str] | None = None) -> dict[str, str]:
        """An environment for a child process that selects this scenario and log explicitly."""
        env = dict(os.environ if base is None else base)
        env[SCENARIO_ENV] = str(self.scenario_path)
        env[LOG_ENV] = str(self.log_dir)
        return env

    def argv(self, tool: Tool = "ffmpeg") -> list[str]:
        """The command that runs the fake without a launcher, for example
        ``[*tools.argv("ffmpeg"), "-version"]``.

        On Windows a launcher runs through ``cmd.exe``, which interprets ``& | < > ^ %`` in
        arguments that ``subprocess`` does not quote (it quotes only arguments with spaces).
        Pass such arguments through this command instead. The scenario and the log come only
        from ``env``, so pass ``env=tools.env()``.
        """
        return [PYTHON, "-I", str(SCRIPT), "--fake-tool", tool]

    def invocations(self) -> list[Invocation]:
        """Every logged process, in the order the entries were written (``monotonic_ns``)."""
        if not self.log_dir.is_dir():
            return []
        result: list[Invocation] = []
        for path in self.log_dir.glob("*.json"):
            entry = _read_entry(path)
            if entry is None:  # removed by clear_log() in the meantime
                continue
            result.append(
                Invocation(
                    role=entry["role"],
                    tool=entry["tool"],
                    pid=int(entry["pid"]),
                    ppid=int(entry["ppid"]),
                    argv=tuple(entry.get("argv", ())),
                    cwd=entry.get("cwd"),
                    monotonic_ns=int(entry.get("monotonic_ns", 0)),
                    time_ns=int(entry.get("time_ns", 0)),
                )
            )
        result.sort(key=lambda inv: (inv.monotonic_ns, inv.time_ns, inv.pid))
        return result

    def pids(self) -> list[int]:
        """Pids of every process the fake started (main processes and grandchildren)."""
        return [inv.pid for inv in self.invocations()]

    def calls(self, tool: Tool | None = None) -> list[tuple[str, ...]]:
        """The argv of each main invocation (optionally of one tool), in order."""
        return [
            inv.argv
            for inv in self.invocations()
            if inv.role == "main" and (tool is None or inv.tool == tool)
        ]

    def clear_log(self) -> None:
        if self.log_dir.is_dir():
            for path in self.log_dir.iterdir():
                if path.suffix == ".json":
                    path.unlink(missing_ok=True)

    def kill_leftovers(self, timeout: float = 10.0) -> list[int]:
        """Kill every logged process that is still running and wait for it; return the pids.

        A pid is skipped when its process started after the log entry was written: the OS
        reused the pid for an unrelated process.
        """
        import psutil  # only the tests need it, not the fake itself

        procs: list[psutil.Process] = []
        for inv in self.invocations():
            try:
                proc = psutil.Process(inv.pid)
                if proc.create_time() > inv.time_ns / 1e9 + _PID_REUSE_TOLERANCE:
                    continue
                if proc.status() == psutil.STATUS_ZOMBIE:
                    continue
            except psutil.Error:
                continue
            procs.append(proc)
        for proc in procs:
            with contextlib.suppress(psutil.Error):
                proc.kill()
        psutil.wait_procs(procs, timeout=timeout)
        return [proc.pid for proc in procs]


def posix_launcher(tool: Tool, *, python: str, script: Path, scenario: Path, log: Path) -> str:
    """Text of the POSIX launcher for ``tool``."""
    body = (
        "import os, sys\n"
        f"os.environ.setdefault({SCENARIO_ENV!r}, {str(scenario)!r})\n"
        f"os.environ.setdefault({LOG_ENV!r}, {str(log)!r})\n"
        f"sys.path.append({str(script.parent)!r})\n"
        f"import {script.stem}\n"
        f"sys.exit({script.stem}.main({tool!r}, sys.argv[1:]))\n"
    )
    if len(python) <= _MAX_SHEBANG and not any(c.isspace() for c in python):
        return (
            f"#!{python} -I\n# Reframe fake {tool} (reframe_testing.fake_tools). Generated.\n{body}"
        )
    # Long or spaced interpreter path: a #! line cannot hold it. exec keeps the same pid.
    code = body.replace("sys.argv[1:]", "sys.argv[2:]")
    return (
        "#!/bin/sh\n"
        f"# Reframe fake {tool} (reframe_testing.fake_tools). Generated.\n"
        f'exec {shlex.quote(python)} -I -c {shlex.quote(code)} {tool} "$@"\n'
    )


def _cmd_quote(value: str) -> str:
    """Quote a value for a ``.cmd`` file: double quotes, and ``%`` doubled."""
    if '"' in value:
        raise ValueError(f"cannot put a double quote into a .cmd launcher: {value!r}")
    return '"' + value.replace("%", "%%") + '"'


def _cmd_encoding() -> str:
    """``cmd.exe`` reads batch files in the OEM code page (``oem`` codec: Windows only)."""
    try:
        codecs.lookup("oem")
    except LookupError:
        return "utf-8"
    return "oem"


def windows_launcher(tool: Tool, *, python: str, script: Path, scenario: Path, log: Path) -> str:
    """Text of the Windows ``.cmd`` launcher for ``tool`` (CRLF line ends)."""
    # One line (a .cmd line cannot hold a newline): the same import as the POSIX launcher, so
    # the interpreter loads the cached bytecode of the fake and does not compile it per call.
    code = (
        f"import sys; sys.path.append({str(script.parent)!r}); import {script.stem}; "
        f"sys.exit({script.stem}.main({tool!r}, sys.argv[1:]))"
    )
    lines = [
        "@echo off",
        f"rem Reframe fake {tool} (reframe_testing.fake_tools). Generated.",
        "setlocal",
        f'if not defined {SCENARIO_ENV} set "{SCENARIO_ENV}={str(scenario).replace("%", "%%")}"',
        f'if not defined {LOG_ENV} set "{LOG_ENV}={str(log).replace("%", "%%")}"',
        f"{_cmd_quote(python)} -I -c {_cmd_quote(code)} %*",
        "exit /b %ERRORLEVEL%",
    ]
    return "\r\n".join(lines) + "\r\n"


def make_fake_tools(
    directory: Path,
    scenario: Scenario | Mapping[str, Any] | None = None,
    *,
    platform: str = sys.platform,
    python: str | None = None,
) -> FakeTools:
    """Write ``ffmpeg`` and ``ffprobe`` launchers (``.cmd`` on Windows) into ``directory``.

    ``scenario`` is written to ``directory/scenario.json`` and is the launchers' default; the
    ``REFRAME_FAKE_FFMPEG_SCENARIO`` environment variable overrides it. Calls are logged as one
    file each in ``directory/calls.d/`` (``REFRAME_FAKE_FFMPEG_LOG`` overrides it).

    ``python`` defaults to :data:`PYTHON` (the base interpreter, not a venv launcher).
    ``platform`` and ``python`` exist so that the Windows launcher can be written (and
    unit-tested) on Linux.
    """
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    python = python or PYTHON
    scenario_path = directory / "scenario.json"
    log_dir = directory / "calls.d"
    windows = platform.startswith("win")
    paths: dict[str, Path] = {}
    for tool in ("ffmpeg", "ffprobe"):
        if windows:
            path = directory / f"{tool}.cmd"
            text = windows_launcher(
                tool, python=python, script=SCRIPT, scenario=scenario_path, log=log_dir
            )
            path.write_bytes(text.encode(_cmd_encoding()))
        else:
            path = directory / tool
            text = posix_launcher(
                tool, python=python, script=SCRIPT, scenario=scenario_path, log=log_dir
            )
            path.write_text(text, encoding="utf-8", newline="\n")
            path.chmod(0o755)
        paths[tool] = path
    tools = FakeTools(
        directory=directory,
        ffmpeg=paths["ffmpeg"],
        ffprobe=paths["ffprobe"],
        scenario_path=scenario_path,
        log_dir=log_dir,
    )
    tools.set_scenario(scenario if scenario is not None else Scenario())
    return tools
