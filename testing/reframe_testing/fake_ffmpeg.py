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
``stdout_file`` / ``stderr_file``: any file path. ``sleep``: seconds. ``hang``: sleep forever.
``crash``: ``{"signal": "SIGSEGV"}`` (POSIX; on Windows exit 0xC0000005) or
``{"exit_code": N}`` (abrupt ``os._exit``, no flush). ``flood``: ``{"bytes": N, "stream":
"stdout"}``. ``spawn_grandchild``: ``{}``, starts a child process that hangs forever.
``progress``: ``{"blocks": N, "interval": s, "media_seconds": s, "fps": f, "bytes_per_second":
n}``. ``write_output``: ``{"bytes": N}``, writes the last argv element. ``version``:
``{"version": "7.1", "configuration": "--enable-gpl ..."}``. ``on_sigterm``: ``"ignore"`` or
``{"exit_code": 255}``. ``exit``: exit code now.

Every invocation appends one JSON line to the log named by ``REFRAME_FAKE_FFMPEG_LOG`` (if
set): ``{"role": "main" | "grandchild", "tool", "pid", "ppid", "argv", "cwd"}``. Tests use it as
the pid file and as a record of the commands that were run.
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
DATA_DIR = Path(__file__).resolve().parent / "fake_data"
TOOLS = ("ffmpeg", "ffprobe")

#: Exit code that Windows reports for an access violation (what a segfault looks like there).
WINDOWS_CRASH_CODE = 0xC0000005

_GRANDCHILD_CODE = "import time\nwhile True:\n    time.sleep(60)\n"


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
    path = os.environ.get(LOG_ENV)
    if not path:
        return
    line = json.dumps(entry, separators=(",", ":")) + "\n"
    # One write() per line with O_APPEND: lines from parallel processes do not interleave.
    fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)
    try:
        os.write(fd, line.encode("utf-8"))
    finally:
        os.close(fd)


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


# --------------------------------------------------------------------------- actions


def _emit_progress(argv: Sequence[str], spec: dict[str, Any]) -> None:
    blocks = max(1, int(spec.get("blocks", 5)))
    interval = float(spec.get("interval", 0.01))
    media_seconds = float(spec.get("media_seconds", 2.0))
    fps = float(spec.get("fps", 25.0))
    bytes_per_second = int(spec.get("bytes_per_second", 50_000))
    end = bool(spec.get("end", True))
    target = _progress_target(argv) or "pipe:1"
    started = time.monotonic()
    for i in range(1, blocks + 1):
        time.sleep(interval)
        out_us = round(media_seconds * 1_000_000 * i / blocks)
        elapsed = max(time.monotonic() - started, 1e-6)
        frame = int(out_us / 1_000_000 * fps)
        secs, us = divmod(out_us, 1_000_000)
        mins, secs = divmod(secs, 60)
        hours, mins = divmod(mins, 60)
        last = i == blocks
        # Field set and order copied from real ffmpeg n9.0.2 (fake_data/progress_encode).
        block = (
            f"frame={frame}\n"
            f"fps={frame / elapsed:.2f}\n"
            "stream_0_0_q=28.0\n"
            f"bitrate={bytes_per_second * 8 / 1000:.1f}kbits/s\n"
            f"total_size={int(bytes_per_second * out_us / 1_000_000)}\n"
            f"out_time_us={out_us}\n"
            f"out_time_ms={out_us}\n"
            f"out_time={hours:02d}:{mins:02d}:{secs:02d}.{us:06d}\n"
            "dup_frames=0\n"
            "drop_frames=0\n"
            f"speed={out_us / 1_000_000 / elapsed:4.3g}x\n"
            f"progress={'end' if last and end else 'continue'}\n"
        )
        if target == "pipe:1":
            _write("stdout", block.encode())
        elif target == "pipe:2":
            _write("stderr", block.encode())
        else:
            with open(target, "a", encoding="utf-8") as f:
                f.write(block)


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


def _crash(spec: dict[str, Any]) -> NoReturn:
    if "exit_code" in spec:
        os._exit(int(spec["exit_code"]))
    sys.stdout.flush()
    sys.stderr.flush()
    if os.name == "nt":
        os._exit(WINDOWS_CRASH_CODE)
    signum = getattr(signal, str(spec.get("signal", "SIGSEGV")))
    signal.signal(signum, signal.SIG_DFL)
    os.kill(os.getpid(), signum)
    time.sleep(10)  # the signal is delivered at once; this is only a safety net
    os._exit(1)


def _spawn_grandchild(tool: str) -> None:
    child = subprocess.Popen(
        [sys.executable, "-I", "-c", _GRANDCHILD_CODE],
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
        while True:
            time.sleep(60)
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
    elif kind == "exit":
        sys.stdout.flush()
        sys.stderr.flush()
        raise SystemExit(int(value))
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
            return int(rule.get("exit_code", 0))
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
