"""Capture real FFmpeg output into ``fake_data/`` for the fake FFmpeg.

The fake FFmpeg (``fake_ffmpeg.py``) prints these texts, so the parsers in the core are tested
against real formats, not against formats that somebody remembered. Run this script again with
the **pinned** build (``tools/ffmpeg.toml``) when the pin changes, check the diff and commit it::

    BIN=$(uv run --no-project python scripts/fetch-tools.py | tail -n 1)
    uv run python testing/reframe_testing/capture_fake_data.py \\
        --ffmpeg "$BIN/ffmpeg" --ffprobe "$BIN/ffprobe"

Each capture writes ``<name>.stdout.txt`` and/or ``<name>.stderr.txt`` (only the streams that
have output) and one entry in ``captures.json`` with the exact command, extra environment
variables, the exit code and the build (first line of ``ffmpeg -version``). Hardware captures
depend on the machine (GPU, drivers); the ``machine`` field says where they were made.

``library_strings.json`` lists, for each hardware error text that ``C-4`` maps to a reason,
the libraries of the build that contain it (a plain byte search in ``lib/libav*`` and the
``ffmpeg`` binary). It confirms the exact texts of errors that cannot be provoked on the
capture machine.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Mapping, Sequence
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent / "fake_data"
#: Files in DATA_DIR that this script does not generate (kept when it cleans the folder).
KEEP = {".gitattributes"}

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

#: Hardware test encodes, in the form that C-4 uses (3 frames of ``color`` to ``-f null -``):
#: name -> (arguments, extra environment variables).
_TEST_INPUT = ("-f", "lavfi", "-i", "color=size=640x360", "-frames:v", "3")
_VAAPI_UPLOAD = ("-vf", "format=nv12,hwupload", "-c:v", "h264_vaapi", "-f", "null", "-")
HW_CAPTURES: dict[str, tuple[tuple[str, ...], dict[str, str]]] = {
    # No NVIDIA driver on the capture machine.
    "hw_hevc_nvenc_no_driver": ((*_TEST_INPUT, "-c:v", "hevc_nvenc", "-f", "null", "-"), {}),
    "hw_h264_nvenc_no_driver": ((*_TEST_INPUT, "-c:v", "h264_nvenc", "-f", "null", "-"), {}),
    # No Intel GPU: the MFX session cannot be created.
    "hw_hevc_qsv_no_device": ((*_TEST_INPUT, "-c:v", "hevc_qsv", "-f", "null", "-"), {}),
    "hw_qsv_init_failed": (
        (
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
        {},
    ),
    # A render node that does not exist.
    "hw_h264_vaapi_bad_device": (
        ("-vaapi_device", "/dev/dri/renderD999", *_TEST_INPUT, *_VAAPI_UPLOAD),
        {},
    ),
    # A file that is not a DRM device.
    "hw_h264_vaapi_not_drm": (("-vaapi_device", "/dev/null", *_TEST_INPUT, *_VAAPI_UPLOAD), {}),
    # A real render node, but libva cannot load a driver: vaInitialize() fails.
    "hw_h264_vaapi_init_failed": (
        ("-vaapi_device", "/dev/dri/renderD128", *_TEST_INPUT, *_VAAPI_UPLOAD),
        {"LIBVA_DRIVER_NAME": "reframe_nonexistent"},
    ),
    # VAAPI encoder without a device and without hwupload (a command-builder mistake).
    "hw_h264_vaapi_no_hwupload": ((*_TEST_INPUT, "-c:v", "h264_vaapi", "-f", "null", "-"), {}),
    # A working VAAPI device (AMD on the capture machine): what success looks like.
    "hw_h264_vaapi_ok": (
        ("-vaapi_device", "/dev/dri/renderD128", *_TEST_INPUT, *_VAAPI_UPLOAD),
        {},
    ),
    # AMF (AMD) on Linux: works on the capture machine.
    "hw_hevc_amf_ok": ((*_TEST_INPUT, "-c:v", "hevc_amf", "-f", "null", "-"), {}),
}

#: Environment variables removed for every capture: they change the log format.
_DROP_ENV = ("AV_LOG_FORCE_COLOR", "AV_LOG_FORCE_NOCOLOR", "AV_LOG_FORCE_256COLOR")

#: Texts that C-4's reason mapping may use (or that the plan names), searched in the build.
LIBRARY_STRINGS = (
    # NVIDIA
    "Cannot load %s",
    "libcuda.so.1",
    "nvcuda.dll",
    "Driver does not support the required nvenc API version",
    "The minimum required Nvidia driver for nvenc is",
    "No capable devices found",
    "No CUDA capable devices found",
    "No NVENC capable devices found",
    "OpenEncodeSessionEx failed",
    # Intel QSV (oneVPL)
    "Error creating a MFX session",
    "Error initializing an MFX session",
    "Error querying a MFX session",
    "MFX_ERR_UNSUPPORTED",
    # VAAPI
    "No VA display found for device",
    "No VA display found for any default device",
    "Failed to initialise VAAPI connection",
    "Failed to create a VAAPI device",
    # AMD AMF
    "Failed to create  hardware device context (AMF)",
    # generic (fftools)
    "Device creation failed",
    "Error while opening encoder",
    "Nothing was written into output file",
    "Conversion failed!",
)


def _child_env(extra: Mapping[str, str]) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if k not in _DROP_ENV}
    env.update(extra)
    return env


def _run(
    argv: Sequence[str], *, env: Mapping[str, str] | None = None, cwd: Path | None = None
) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        list(argv),
        capture_output=True,
        timeout=120,
        check=False,
        env=_child_env(env or {}),
        cwd=cwd,
    )


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


def _version_line(exe: str) -> str:
    out = _run([exe, "-hide_banner", "-version"])
    return out.stdout.decode("utf-8", errors="replace").splitlines()[0].strip()


class Capturer:
    def __init__(self, ffmpeg: str, ffprobe: str) -> None:
        self.ffmpeg = ffmpeg
        self.ffprobe = ffprobe
        self.builds = {"ffmpeg": _version_line(ffmpeg), "ffprobe": _version_line(ffprobe)}
        self.index: dict[str, dict[str, object]] = {}

    def capture(
        self,
        name: str,
        tool: str,
        args: Sequence[str],
        *,
        machine: bool = False,
        env: Mapping[str, str] | None = None,
        cwd: Path | None = None,
    ) -> int:
        exe = self.ffmpeg if tool == "ffmpeg" else self.ffprobe
        result = _run([exe, *args], env=env, cwd=cwd)
        entry: dict[str, object] = {
            "command": [tool, *args],
            "exit_code": result.returncode,
            "build": self.builds[tool],
        }
        if env:
            entry["env"] = dict(env)
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


def _strings(data: bytes) -> set[bytes]:
    return set(re.findall(rb"[\x20-\x7e\t\n]{5,}", data))


def library_strings(ffmpeg: str) -> dict[str, object]:
    """Which files of the build contain each text of :data:`LIBRARY_STRINGS`."""
    exe = Path(ffmpeg).resolve()
    root = exe.parent.parent
    files = sorted(
        {
            exe,
            *(root / "lib").glob("libav*.so.*.*.*"),
            *exe.parent.glob("av*.dll"),
        }
    )
    found: dict[str, list[dict[str, str]]] = {text: [] for text in LIBRARY_STRINGS}
    for path in files:
        strings = _strings(path.read_bytes())
        for text in LIBRARY_STRINGS:
            needle = text.encode()
            for s in sorted(x for x in strings if needle in x and len(x) < 200):
                found[text].append(
                    {
                        "file": path.relative_to(root).as_posix(),
                        "string": s.decode("ascii"),
                    }
                )
    return {
        "build": _version_line(ffmpeg),
        "method": "byte search for printable runs of >= 5 characters (like strings(1)) in "
        "bin/ffmpeg, lib/libav*.so.*.*.* and bin/av*.dll",
        "strings": found,
    }


def _clean() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    for path in DATA_DIR.iterdir():
        if path.name in KEEP:
            continue
        if path.is_dir():
            shutil.rmtree(path)
        else:
            path.unlink()


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0] if __doc__ else None)
    parser.add_argument(
        "--ffmpeg", default=os.environ.get("REFRAME_FFMPEG", shutil.which("ffmpeg"))
    )
    parser.add_argument(
        "--ffprobe", default=os.environ.get("REFRAME_FFPROBE", shutil.which("ffprobe"))
    )
    args = parser.parse_args(argv)
    if not args.ffmpeg or not args.ffprobe:
        print("ffmpeg/ffprobe not found", file=sys.stderr)
        return 2

    _clean()
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

    progress = ["-progress", "pipe:1", "-nostats"]
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
            *progress,
            "-f",
            "null",
            "-",
        ],
    )
    # Many blocks (-stats_period 0.1; -readrate 2 makes the run take about 2 s on any machine):
    # the first blocks have N/A times (the encoder has not returned a packet yet), and -f null
    # gives bitrate=N/A / total_size=N/A.
    cap.capture(
        "progress_null_long",
        "ffmpeg",
        [
            "-hide_banner",
            "-nostdin",
            "-readrate",
            "2",
            "-f",
            "lavfi",
            "-i",
            "testsrc2=size=640x360:rate=25:duration=4",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            *progress,
            "-stats_period",
            "0.1",
            "-f",
            "null",
            "-",
        ],
    )
    # The same into a Matroska file with audio, as a real job writes it: padded bitrate and
    # speed values ("bitrate=  43.8kbits/s", "speed= 4.3x"); total_size moves in steps.
    with tempfile.TemporaryDirectory() as tmp:
        cap.capture(
            "progress_mkv_long",
            "ffmpeg",
            [
                "-hide_banner",
                "-nostdin",
                "-y",
                "-readrate",
                "2",
                "-f",
                "lavfi",
                "-i",
                "testsrc2=size=640x360:rate=25:duration=4",
                "-readrate",
                "2",
                "-f",
                "lavfi",
                "-i",
                "sine=frequency=440:duration=4",
                "-c:v",
                "libx264",
                "-preset",
                "veryfast",
                "-c:a",
                "aac",
                *progress,
                "-stats_period",
                "0.1",
                "progress.mkv",
            ],
            cwd=Path(tmp),
        )
    for name, (hw_args, env) in HW_CAPTURES.items():
        cap.capture(name, "ffmpeg", ["-hide_banner", "-nostdin", *hw_args], machine=True, env=env)
        cap.capture(
            f"{name}.v_error",
            "ffmpeg",
            ["-hide_banner", "-nostdin", "-v", "error", *hw_args],
            machine=True,
            env=env,
        )

    (DATA_DIR / "captures.json").write_text(
        json.dumps(cap.index, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n"
    )
    (DATA_DIR / "library_strings.json").write_text(
        json.dumps(library_strings(args.ffmpeg), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
