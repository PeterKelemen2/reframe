"""Capture real FFmpeg output into ``fake_data/`` for the fake FFmpeg.

The fake FFmpeg (``fake_ffmpeg.py``) prints these texts, so the parsers in the core are tested
against real formats, not against formats that somebody remembered. Run this script again when
the pinned FFmpeg version changes, check the diff and commit it::

    uv run python testing/reframe_testing/capture_fake_data.py [--ffmpeg PATH] [--ffprobe PATH]

Each capture writes ``<name>.stdout.txt`` and/or ``<name>.stderr.txt`` (only the streams that
have output) and one entry in ``captures.json`` with the exact command and the exit code.
Hardware captures depend on the machine (GPU, drivers); the ``machine`` field says where they
were made.
"""

from __future__ import annotations

import argparse
import json
import platform
import shutil
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent / "fake_data"

#: Encoders whose ``-h encoder=<name>`` text is captured (if the build has them).
HELP_ENCODERS = (
    "libx264",
    "libx265",
    "libsvtav1",
    "libaom-av1",
    "libvpx-vp9",
    "h264_nvenc",
    "hevc_nvenc",
    "av1_nvenc",
    "h264_qsv",
    "hevc_qsv",
    "av1_qsv",
    "h264_vaapi",
    "hevc_vaapi",
    "av1_vaapi",
    "h264_amf",
    "hevc_amf",
    "av1_amf",
    "aac",
    "ac3",
    "eac3",
    "libopus",
    "flac",
    "libmp3lame",
    "dvdsub",
    "srt",
    "ass",
    "mov_text",
)

#: Hardware test encodes, in the form that C-4 uses (3 frames of ``color`` to ``-f null -``).
_TEST_INPUT = ("-f", "lavfi", "-i", "color=size=640x360", "-frames:v", "3")
HW_CAPTURES: dict[str, tuple[str, ...]] = {
    # No NVIDIA driver on the capture machine.
    "hw_hevc_nvenc_no_driver": (*_TEST_INPUT, "-c:v", "hevc_nvenc", "-f", "null", "-"),
    "hw_h264_nvenc_no_driver": (*_TEST_INPUT, "-c:v", "h264_nvenc", "-f", "null", "-"),
    # No Intel GPU: the MFX session cannot be created.
    "hw_hevc_qsv_no_device": (*_TEST_INPUT, "-c:v", "hevc_qsv", "-f", "null", "-"),
    "hw_qsv_init_failed": (
        "-init_hw_device",
        "qsv=hw",
        "-filter_hw_device",
        "hw",
        *_TEST_INPUT,
        "-vf",
        "format=nv12,hwupload=extra_hw_frames=64",
        "-c:v",
        "hevc_qsv",
        "-f",
        "null",
        "-",
    ),
    # A render node that does not exist.
    "hw_h264_vaapi_bad_device": (
        "-vaapi_device",
        "/dev/dri/renderD999",
        *_TEST_INPUT,
        "-vf",
        "format=nv12,hwupload",
        "-c:v",
        "h264_vaapi",
        "-f",
        "null",
        "-",
    ),
    # VAAPI encoder without a device and without hwupload (a command-builder mistake).
    "hw_h264_vaapi_no_hwupload": (*_TEST_INPUT, "-c:v", "h264_vaapi", "-f", "null", "-"),
    # A working VAAPI device (AMD on the capture machine): what success looks like.
    "hw_h264_vaapi_ok": (
        "-vaapi_device",
        "/dev/dri/renderD128",
        *_TEST_INPUT,
        "-vf",
        "format=nv12,hwupload",
        "-c:v",
        "h264_vaapi",
        "-f",
        "null",
        "-",
    ),
}


def _run(argv: Sequence[str]) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(list(argv), capture_output=True, timeout=60, check=False)


def _machine() -> str:
    gpu = "unknown GPU"
    try:
        out = subprocess.run(["lspci"], capture_output=True, text=True, timeout=10).stdout
        vga = [line for line in out.splitlines() if " VGA " in line or "Display" in line]
        if vga:
            gpu = "; ".join(line.split(": ", 1)[-1] for line in vga)
    except (OSError, subprocess.SubprocessError):
        pass
    return f"{platform.system()} {platform.release()} ({gpu})"


class Capturer:
    def __init__(self, ffmpeg: str, ffprobe: str) -> None:
        self.ffmpeg = ffmpeg
        self.ffprobe = ffprobe
        self.index: dict[str, dict[str, object]] = {}

    def capture(self, name: str, tool: str, args: Sequence[str], *, machine: bool = False) -> int:
        exe = self.ffmpeg if tool == "ffmpeg" else self.ffprobe
        result = _run([exe, *args])
        entry: dict[str, object] = {
            "command": [tool, *args],
            "exit_code": result.returncode,
        }
        for stream, data in (("stdout", result.stdout), ("stderr", result.stderr)):
            path = DATA_DIR / f"{name}.{stream}.txt"
            if data:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(data.replace(b"\r\n", b"\n"))
                entry[stream] = path.relative_to(DATA_DIR).as_posix()
            elif path.exists():
                path.unlink()
        if machine:
            entry["machine"] = _machine()
        self.index[name] = entry
        print(f"{name:40} exit {result.returncode}")
        return result.returncode


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0] if __doc__ else None)
    parser.add_argument("--ffmpeg", default=shutil.which("ffmpeg"))
    parser.add_argument("--ffprobe", default=shutil.which("ffprobe"))
    args = parser.parse_args(argv)
    if not args.ffmpeg or not args.ffprobe:
        print("ffmpeg/ffprobe not found", file=sys.stderr)
        return 2

    if DATA_DIR.exists():
        shutil.rmtree(DATA_DIR)
    DATA_DIR.mkdir(parents=True)
    cap = Capturer(args.ffmpeg, args.ffprobe)

    cap.capture("ffmpeg_version", "ffmpeg", ["-version"])
    cap.capture("ffprobe_version", "ffprobe", ["-version"])
    # The banner that ffmpeg prints to stderr when -hide_banner is missing.
    cap.capture("ffmpeg_banner", "ffmpeg", ["-h", "encoder=reframe_nonexistent"])
    cap.capture("encoders", "ffmpeg", ["-hide_banner", "-encoders"])
    cap.capture("hwaccels", "ffmpeg", ["-hide_banner", "-hwaccels"])
    cap.capture("filters", "ffmpeg", ["-hide_banner", "-filters"])
    cap.capture(
        "help_encoder_unknown", "ffmpeg", ["-hide_banner", "-h", "encoder=reframe_nonexistent"]
    )

    encoders = (DATA_DIR / "encoders.stdout.txt").read_text(encoding="utf-8")
    available = {
        line.split()[1]
        for line in encoders.splitlines()
        if line.startswith(" ") and len(line.split()) > 1
    }
    for enc in HELP_ENCODERS:
        if enc in available:
            cap.capture(f"help_encoder/{enc}", "ffmpeg", ["-hide_banner", "-h", f"encoder={enc}"])

    cap.capture(
        "progress_encode",
        "ffmpeg",
        [
            "-hide_banner",
            "-nostdin",
            "-f",
            "lavfi",
            "-i",
            "testsrc2=size=320x180:rate=25:duration=2",
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-progress",
            "pipe:1",
            "-nostats",
            "-f",
            "null",
            "-",
        ],
    )
    for name, hw_args in HW_CAPTURES.items():
        cap.capture(name, "ffmpeg", ["-hide_banner", "-nostdin", *hw_args], machine=True)
        cap.capture(
            f"{name}.v_error",
            "ffmpeg",
            ["-hide_banner", "-nostdin", "-v", "error", *hw_args],
            machine=True,
        )

    (DATA_DIR / "captures.json").write_text(
        json.dumps(cap.index, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
