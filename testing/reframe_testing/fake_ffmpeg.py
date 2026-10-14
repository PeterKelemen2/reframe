"""Fake ``ffmpeg`` / ``ffprobe`` for fault-injection tests (plan Q-2, "Fault injection").

This file is a standalone script (standard library only). Do not run it directly in tests: use
:func:`reframe_testing.fake_tools.make_fake_tools`, which writes launchers named ``ffmpeg`` and
``ffprobe`` that run this script with the right tool name.

Behaviour comes from a JSON *scenario* file. Its path is read from the environment variable
``REFRAME_FAKE_FFMPEG_SCENARIO`` (the launcher sets a default). Without a scenario, or when no
rule matches, the built-in defaults apply (see :func:`run_defaults`): ``-version``,
``-encoders``, ``-filters``, ``-hwaccels`` and ``-h encoder=<name>`` print text captured from a
real FFmpeg (``fake_data/``); an encode (``-i`` present) emits ``-progress`` blocks if asked and
writes the output file.

Scenario format::

    {
      "rules": [
        {
          "tool": "ffmpeg",                     # optional: "ffmpeg" | "ffprobe"
          "argv_has": ["-c:v", "hevc_nvenc"],   # optional: every item is an exact argv element
          "argv_contains": ["nvenc"],           # optional: every item is a substring of an element
          "argv_regex": "-h encoder=\\\\S+",    # optional: re.search on the argv joined with spaces
          "actions": [{"stderr": "Cannot load libcuda.so.1\\n"}, {"sleep": 0.5}],
          "exit_code": 1
        }
      ],
      "defaults": true                          # use the built-in defaults if no rule matches
    }

The first matching rule wins. Actions run in order; each is an object with one key:

``stdout`` / ``stderr``: text. ``stdout_data`` / ``stderr_data``: a file name in ``fake_data/``.
``stdout_file`` / ``stderr_file``: any file path. ``sleep``: seconds. ``hang``: sleep until the
maximum lifetime (below) is over. ``crash``: ``{"signal": "SIGSEGV"}`` (POSIX; on Windows exit
0xC0000005) or ``{"exit_code": N}`` (abrupt ``os._exit``, no flush). ``flood``: ``{"bytes": N,
"stream": "stdout"}``. ``spawn_grandchild``: ``{}``, starts a child process that hangs (with the
same maximum lifetime). ``progress``: ``{"blocks": N, "interval": s, "media_seconds": s, "fps":
f, "bytes_per_second": n, "end": true, "na_fields": ["bitrate", ...], "na_blocks": N}``.
``write_output``: ``{"bytes": N}``, writes the last argv element. ``version``: ``{"version":
"7.1", "configuration": "--enable-gpl ..."}``. ``on_sigterm``: ``"ignore"`` or ``{"exit_code":
255}``. ``exit``: exit code now. ``exec``: a program path; run it with the same arguments
(stdin, stdout and stderr shared) and exit with its exit code (128 + N when signal N ended
it), so a scenario can fail one command and pass every other one to a real FFmpeg.

``hang`` and the grandchild do not run forever: they exit when
``REFRAME_FAKE_FFMPEG_MAX_LIFETIME`` seconds (default 120) have passed since the process
started, so a failed test cannot leave processes behind for long. ``hang`` then exits with
:data:`LIFETIME_EXIT_CODE`.

Exit codes above ``2**31 - 1`` (such as ``0xC0000005``) are given to the OS as the signed C
``int`` with the same 32 bits, because ``os._exit`` and ``sys.exit`` take a C ``int``.

Every invocation writes one JSON file into the folder named by ``REFRAME_FAKE_FFMPEG_LOG`` (if
set): ``<pid>-<random hex>.json`` with ``{"role": "main" | "grandchild", "tool", "pid", "ppid",
"argv", "cwd", "monotonic_ns", "time_ns"}``. The file is written under a ``.tmp`` name and then
renamed, so a reader never sees a partial file, and parallel processes never share a file (an
``O_APPEND`` log is not atomic between processes on Windows). Tests use the folder as the pid
file and as a record of the commands that were run, sorted by ``monotonic_ns`` (a system-wide
clock on Linux, macOS and Windows).
"""

from __future__ import annotations

import json
import os
import re
import signal
import subprocess
import sys
import time
from collections.abc import Sequence
from pathlib import Path
from typing import Any, NoReturn

SCENARIO_ENV = "REFRAME_FAKE_FFMPEG_SCENARIO"
LOG_ENV = "REFRAME_FAKE_FFMPEG_LOG"
MAX_LIFETIME_ENV = "REFRAME_FAKE_FFMPEG_MAX_LIFETIME"
DEFAULT_MAX_LIFETIME = 120.0
#: Exit code of ``hang`` when the maximum lifetime is over (the code of ``timeout(1)``).
LIFETIME_EXIT_CODE = 124
DATA_DIR = Path(__file__).resolve().parent / "fake_data"
TOOLS = ("ffmpeg", "ffprobe")

#: Exit code that Windows reports for an access violation (what a segfault looks like there).
WINDOWS_CRASH_CODE = 0xC0000005

#: The grandchild sleeps until its maximum lifetime (``sys.argv[1]`` seconds) is over.
_GRANDCHILD_CODE = (
    "import sys, time\n"
    "end = time.monotonic() + float(sys.argv[1])\n"
    "while (left := end - time.monotonic()) > 0:\n"
    "    time.sleep(left)\n"
)

_STARTED = time.monotonic()


def python_executable() -> str:
    """The real interpreter, never a venv launcher.

    On Windows, ``.venv\\Scripts\\python.exe`` is a launcher that starts the base interpreter as
    a child process, so it would add one more process to every tree. The fake needs only the
    standard library (it runs with ``-I``), so it runs with ``sys._base_executable``.
    """
    base: str | None = getattr(sys, "_base_executable", None)
    return base or sys.executable


def max_lifetime() -> float:
    """``REFRAME_FAKE_FFMPEG_MAX_LIFETIME`` in seconds (default 120)."""
    try:
        value = float(os.environ.get(MAX_LIFETIME_ENV, ""))
    except ValueError:
        return DEFAULT_MAX_LIFETIME
    return value if value >= 0 else DEFAULT_MAX_LIFETIME


def exit_code_for_os(code: int) -> int:
    """``code`` as the C ``int`` that ``os._exit`` / ``sys.exit`` take (same low 32 bits).

    ``os._exit(0xC0000005)`` raises ``OverflowError``; ``os._exit(-1073741819)`` makes Windows
    report the exit code ``0xC0000005``.
    """
    code &= 0xFFFFFFFF
    return code - 2**32 if code >= 2**31 else code


# --------------------------------------------------------------------------- output helpers


def _write(stream: str, data: bytes) -> None:
    target = sys.stdout if stream == "stdout" else sys.stderr
    try:
        target.buffer.write(data)
        target.buffer.flush()
    except OSError:
        # The reader went away (for example an output limit was hit): BrokenPipeError on
        # POSIX, BrokenPipeError or EINVAL on Windows. Exit quietly.
        _silence_and_exit(141 if os.name != "nt" else 1)


def _silence_and_exit(code: int) -> NoReturn:
    try:
        devnull = os.open(os.devnull, os.O_WRONLY)
        os.dup2(devnull, sys.stdout.fileno())
        os.dup2(devnull, sys.stderr.fileno())
    except OSError:
        pass
    os._exit(code)


def _data(name: str) -> bytes:
    return (DATA_DIR / name).read_bytes()


def _flood(stream: str, nbytes: int) -> None:
    line = b"x" * 63 + b"\n"
    chunk = line * (2**20 // len(line))
    remaining = nbytes
    while remaining > 0:
        part = chunk[: min(len(chunk), remaining)]
        _write(stream, part)
        remaining -= len(part)


def _log(entry: dict[str, Any]) -> None:
    """Write ``entry`` as a new file in the log folder (a temporary name, then a rename)."""
    folder = os.environ.get(LOG_ENV)
    if not folder:
        return
    entry = {**entry, "monotonic_ns": time.monotonic_ns(), "time_ns": time.time_ns()}
    os.makedirs(folder, exist_ok=True)
    name = f"{os.getpid()}-{os.urandom(16).hex()}"
    tmp = os.path.join(folder, name + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(entry, f, separators=(",", ":"))
    os.replace(tmp, os.path.join(folder, name + ".json"))


# --------------------------------------------------------------------------- argv helpers


def _option_value(argv: Sequence[str], option: str) -> str | None:
    for i, arg in enumerate(argv[:-1]):
        if arg == option:
            return argv[i + 1]
    return None


def _output_path(argv: Sequence[str]) -> str | None:
    """The output file: the last argv element, unless it is an option, stdout or a pipe."""
    if not argv or "-i" not in argv:
        return None
    last = argv[-1]
    if last.startswith(("-", "pipe:")) or last == os.devnull:
        return None
    if _option_value(argv, "-f") == "null":
        return None
    return last


def _progress_target(argv: Sequence[str]) -> str | None:
    return _option_value(argv, "-progress")


# --------------------------------------------------------------------------- progress

#: Fields of a ``-progress`` block, in the order that real ffmpeg n9.0.2 prints them.
PROGRESS_FIELDS = (
    "frame",
    "fps",
    "stream_0_0_q",
    "bitrate",
    "total_size",
    "out_time_us",
    "out_time_ms",
    "out_time",
    "dup_frames",
    "drop_frames",
    "speed",
    "progress",
)

#: A block that real ffmpeg prints before the encoder has returned its first packet (copied
#: from ``fake_data/progress_null_long.stdout.txt``: libx264 to ``-f null``, ``-stats_period``).
STARTUP_BLOCK = {
    "frame": "0",
    "fps": "0.00",
    "stream_0_0_q": "0.0",
    "bitrate": "N/A",
    "total_size": "0",
    "out_time_us": "N/A",
    "out_time_ms": "N/A",
    "out_time": "N/A",
    "dup_frames": "0",
    "drop_frames": "0",
    "speed": "N/A",
}


def progress_block(spec: dict[str, Any], n: int, elapsed: float) -> str:
    """Text of block ``n`` (from 0) of a ``progress`` action; ``elapsed``: wall seconds so far.

    The first ``na_blocks`` blocks are :data:`STARTUP_BLOCK`. Then ``blocks`` blocks follow, with
    ``out_time_us`` going linearly up to ``media_seconds``. The fields in ``na_fields`` are
    ``N/A`` in every block (real ffmpeg prints ``bitrate=N/A`` and ``total_size=N/A`` with
    ``-f null``). The last block has ``progress=end`` unless ``end`` is false.
    """
    blocks = max(1, int(spec.get("blocks", 5)))
    media_seconds = float(spec.get("media_seconds", 2.0))
    fps = float(spec.get("fps", 25.0))
    bytes_per_second = int(spec.get("bytes_per_second", 50_000))
    end = bool(spec.get("end", True))
    na_fields = [str(f) for f in spec.get("na_fields", ())]
    unknown = set(na_fields) - set(PROGRESS_FIELDS[:-1])
    if unknown:
        raise ValueError(f"unknown -progress fields for N/A: {sorted(unknown)}")
    na_blocks = max(0, int(spec.get("na_blocks", 0)))
    values: dict[str, str]
    if n < na_blocks:
        values = dict(STARTUP_BLOCK)
    else:
        out_us = round(media_seconds * 1_000_000 * (n - na_blocks + 1) / blocks)
        wall = max(elapsed, 1e-6)
        frame = int(out_us / 1_000_000 * fps)
        secs, us = divmod(out_us, 1_000_000)
        mins, secs = divmod(secs, 60)
        hours, mins = divmod(mins, 60)
        # The formats of fftools/ffmpeg.c print_report(): "%6.1fkbits/s" and "%4.3gx" pad with
        # spaces ("bitrate=  43.8kbits/s", "speed= 4.3x"), as in fake_data/progress_mkv_long.
        values = {
            "frame": str(frame),
            "fps": f"{frame / wall:.2f}",
            "stream_0_0_q": "28.0",
            "bitrate": f"{bytes_per_second * 8 / 1000:6.1f}kbits/s",
            "total_size": str(int(bytes_per_second * out_us / 1_000_000)),
            "out_time_us": str(out_us),
            "out_time_ms": str(out_us),
            "out_time": f"{hours:02d}:{mins:02d}:{secs:02d}.{us:06d}",
            "dup_frames": "0",
            "drop_frames": "0",
            "speed": f"{out_us / 1_000_000 / wall:4.3g}x",
        }
    for field in na_fields:
        values[field] = "N/A"
    last = n == na_blocks + blocks - 1
    values["progress"] = "end" if last and end else "continue"
    return "".join(f"{key}={values[key]}\n" for key in PROGRESS_FIELDS)


def _emit_progress(argv: Sequence[str], spec: dict[str, Any]) -> None:
    interval = float(spec.get("interval", 0.01))
    total = max(1, int(spec.get("blocks", 5))) + max(0, int(spec.get("na_blocks", 0)))
    target = _progress_target(argv) or "pipe:1"
    started = time.monotonic()
    for n in range(total):
        time.sleep(interval)
        block = progress_block(spec, n, time.monotonic() - started)
        if target == "pipe:1":
            _write("stdout", block.encode())
        elif target == "pipe:2":
            _write("stderr", block.encode())
        else:
            with open(target, "a", encoding="utf-8") as f:
                f.write(block)


# --------------------------------------------------------------------------- actions


def _write_output(argv: Sequence[str], spec: dict[str, Any]) -> None:
    out = _output_path(argv)
    if out is None:
        return
    nbytes = int(spec.get("bytes", 1024))
    path = Path(out)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "wb") as f:
        f.write(b"\0" * nbytes)


def _version_text(tool: str, spec: dict[str, Any]) -> bytes:
    text = _data(f"{tool}_version.stdout.txt").decode("utf-8")
    lines = text.splitlines(keepends=True)
    version = spec.get("version")
    if version is not None:
        lines[0] = re.sub(r"^(\S+ version )\S+", lambda m: m.group(1) + str(version), lines[0])
    configuration = spec.get("configuration")
    if configuration is not None:
        lines = [
            f"configuration: {configuration}\n" if line.startswith("configuration:") else line
            for line in lines
        ]
    return "".join(lines).encode("utf-8")


def _crash(spec: dict[str, Any], *, windows: bool | None = None) -> NoReturn:
    if windows is None:
        windows = os.name == "nt"
    if "exit_code" in spec:
        os._exit(exit_code_for_os(int(spec["exit_code"])))
    sys.stdout.flush()
    sys.stderr.flush()
    if windows:
        os._exit(exit_code_for_os(WINDOWS_CRASH_CODE))
    signum = getattr(signal, str(spec.get("signal", "SIGSEGV")))
    signal.signal(signum, signal.SIG_DFL)
    os.kill(os.getpid(), signum)
    time.sleep(10)  # the signal is delivered at once; this is only a safety net
    os._exit(1)


def _hang() -> NoReturn:
    """Sleep until the maximum lifetime is over, then exit with :data:`LIFETIME_EXIT_CODE`."""
    end = _STARTED + max_lifetime()
    while (left := end - time.monotonic()) > 0:
        time.sleep(left)
    _write("stderr", f"fake ffmpeg: {MAX_LIFETIME_ENV} is over, exiting\n".encode())
    sys.stdout.flush()
    os._exit(LIFETIME_EXIT_CODE)


def _spawn_grandchild(tool: str) -> None:
    child = subprocess.Popen(
        [python_executable(), "-I", "-c", _GRANDCHILD_CODE, repr(max_lifetime())],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    _log({"role": "grandchild", "tool": tool, "pid": child.pid, "ppid": os.getpid()})


def _on_sigterm(spec: Any) -> None:
    if not hasattr(signal, "SIGTERM") or os.name == "nt":
        return  # Windows: terminate() is TerminateProcess, it cannot be caught
    if spec == "ignore":
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        return
    code = int(spec.get("exit_code", 255)) if isinstance(spec, dict) else 255
    message = (
        str(spec.get("stderr", "Exiting normally, received signal 15.\n"))
        if isinstance(spec, dict)
        else ""
    )

    def handler(signum: int, frame: object) -> None:
        if message:
            _write("stderr", message.encode())
        os._exit(code)

    signal.signal(signal.SIGTERM, handler)


def _exec(program: str, argv: Sequence[str]) -> NoReturn:
    """Run ``program`` with ``argv`` as a child (stdio shared) and exit with its exit code."""
    sys.stdout.flush()
    sys.stderr.flush()
    try:
        code = subprocess.call([program, *argv])
    except OSError as exc:
        _write("stderr", f"fake ffmpeg: cannot run {program}: {exc}\n".encode())
        os._exit(127)
    os._exit(exit_code_for_os(128 - code if code < 0 else code))


def run_action(tool: str, argv: Sequence[str], action: dict[str, Any]) -> None:
    if len(action) != 1:
        raise ValueError(f"an action has exactly one key, got {sorted(action)}")
    ((kind, value),) = action.items()
    if kind in ("stdout", "stderr"):
        _write(kind, str(value).encode("utf-8"))
    elif kind in ("stdout_data", "stderr_data"):
        _write(kind.removesuffix("_data"), _data(str(value)))
    elif kind in ("stdout_file", "stderr_file"):
        _write(kind.removesuffix("_file"), Path(str(value)).read_bytes())
    elif kind == "sleep":
        time.sleep(float(value))
    elif kind == "hang":
        _hang()
    elif kind == "crash":
        _crash(dict(value) if isinstance(value, dict) else {})
    elif kind == "flood":
        _flood(str(value.get("stream", "stdout")), int(value["bytes"]))
    elif kind == "spawn_grandchild":
        _spawn_grandchild(tool)
    elif kind == "progress":
        _emit_progress(argv, dict(value))
    elif kind == "write_output":
        _write_output(argv, dict(value) if isinstance(value, dict) else {})
    elif kind == "version":
        _write("stdout", _version_text(tool, dict(value)))
    elif kind == "on_sigterm":
        _on_sigterm(value)
    elif kind == "exec":
        _exec(str(value), argv)
    elif kind == "exit":
        sys.stdout.flush()
        sys.stderr.flush()
        raise SystemExit(exit_code_for_os(int(value)))
    else:
        raise ValueError(f"unknown fake ffmpeg action: {kind!r}")


# --------------------------------------------------------------------------- rules


def rule_matches(rule: dict[str, Any], tool: str, argv: Sequence[str]) -> bool:
    if rule.get("tool") not in (None, tool):
        return False
    if any(item not in argv for item in rule.get("argv_has", ())):
        return False
    for needle in rule.get("argv_contains", ()):
        if not any(needle in arg for arg in argv):
            return False
    pattern = rule.get("argv_regex")
    return not (pattern is not None and re.search(pattern, " ".join(argv)) is None)


def _banner(argv: Sequence[str]) -> None:
    if "-hide_banner" not in argv:
        _write("stderr", _data("ffmpeg_banner.stderr.txt"))


def run_defaults(tool: str, argv: Sequence[str]) -> int:
    """Built-in behaviour: answer the discovery commands with real captured output."""
    if "-version" in argv:
        _write("stdout", _data(f"{tool}_version.stdout.txt"))
        return 0
    if tool == "ffprobe":
        _write("stdout", b"{\n\n}\n")
        return 0
    for option, name in (
        ("-encoders", "encoders"),
        ("-filters", "filters"),
        ("-hwaccels", "hwaccels"),
    ):
        if option in argv:
            _banner(argv)
            _write("stdout", _data(f"{name}.stdout.txt"))
            return 0
    help_topic = _option_value(argv, "-h")
    if help_topic is not None and help_topic.startswith("encoder="):
        _banner(argv)
        encoder = help_topic.removeprefix("encoder=")
        path = DATA_DIR / "help_encoder" / f"{encoder}.stdout.txt"
        if path.is_file():
            _write("stdout", path.read_bytes())
        else:
            text = _data("help_encoder_unknown.stdout.txt").decode("utf-8")
            _write("stdout", text.replace("reframe_nonexistent", encoder).encode("utf-8"))
        return 0
    if "-i" in argv:
        _banner(argv)
        if _progress_target(argv) is not None:
            _emit_progress(argv, {})
        _write_output(argv, {})
        return 0
    return 0


def load_scenario() -> dict[str, Any]:
    path = os.environ.get(SCENARIO_ENV)
    if not path:
        return {"rules": [], "defaults": True}
    with open(path, encoding="utf-8") as f:
        data: dict[str, Any] = json.load(f)
    return data


def main(tool: str, argv: Sequence[str]) -> int:
    if tool not in TOOLS:
        raise ValueError(f"unknown tool {tool!r}, expected one of {TOOLS}")
    argv = list(argv)
    _log(
        {
            "role": "main",
            "tool": tool,
            "pid": os.getpid(),
            "ppid": os.getppid(),
            "argv": argv,
            "cwd": os.getcwd(),
        }
    )
    scenario = load_scenario()
    for rule in scenario.get("rules", ()):
        if rule_matches(rule, tool, argv):
            for action in rule.get("actions", ()):
                run_action(tool, argv, action)
            return exit_code_for_os(int(rule.get("exit_code", 0)))
    if scenario.get("defaults", True):
        return run_defaults(tool, argv)
    return 0


def _cli(args: list[str]) -> int:
    """``python fake_ffmpeg.py --fake-tool ffmpeg <ffmpeg args>`` (used by the Windows launcher)."""
    if len(args) < 2 or args[0] != "--fake-tool":
        print("usage: fake_ffmpeg.py --fake-tool ffmpeg|ffprobe [args...]", file=sys.stderr)
        return 2
    return main(args[1], args[2:])


if __name__ == "__main__":
    sys.exit(_cli(sys.argv[1:]))
