"""Helpers for the tests that run the real FFmpeg on a synthetic source and read its log or the
encoder's settings SEI."""

from __future__ import annotations

import os
import re
import subprocess
from collections.abc import Callable, Iterable, Sequence
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from reframe.command import escape_value
from reframe.definitions import VideoEncoderDef
from reframe.definitions.models import OptionMapping
from reframe.models.job import OptionValue
from reframe_testing import media

__all__ = [
    "LAVFI_SMALL",
    "LAVFI_VIDEO",
    "encode_args",
    "mapping_args",
    "parallel",
    "run_ffmpeg_capture",
    "sei_options",
    "sei_text",
    "written_text",
]

LAVFI_VIDEO = ["-f", "lavfi", "-i", "testsrc2=size=320x240:rate=25"]
#: Small enough for every level (H.265 level 1 allows 36 864 luma samples per picture).
LAVFI_SMALL = ["-f", "lavfi", "-i", "testsrc2=size=160x96:rate=15"]


def run_ffmpeg_capture(
    args: Sequence[str], timeout: float = 120
) -> subprocess.CompletedProcess[str]:
    """Run the discovered ffmpeg with ``args`` and keep its output; a failing exit is not raised."""
    ffmpeg = media.find_ffmpeg()
    assert ffmpeg is not None
    return subprocess.run(
        [ffmpeg, "-hide_banner", "-nostdin", "-y", *args],
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )


def parallel[T](jobs: Iterable[T], run: Callable[[T], str | None]) -> list[str]:
    """Run ``run`` for every job in a thread pool; the problems it returns, in order."""
    with ThreadPoolExecutor(max_workers=min(8, os.cpu_count() or 2)) as pool:
        return [p for p in pool.map(run, list(jobs)) if p]


def written_text(value: OptionValue) -> str:
    """The text a value has on the encoder's command line."""
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def mapping_args(mapping: OptionMapping, value: str) -> tuple[list[str], dict[str, str]]:
    """``(arguments, x26x parameters)`` that write ``value`` the way ``mapping`` says."""
    if mapping.kind == "x26x_param":
        return [], {mapping.name: value}
    if mapping.kind == "ffmpeg_arg":
        return [mapping.arg, value], {}
    return [f"-{mapping.name}", value], {}


def encode_args(
    encoder: VideoEncoderDef,
    args: Sequence[str] = (),
    params: dict[str, str] | None = None,
    depth: int = 8,
    frames: int = 3,
    small: bool = False,
) -> list[str]:
    """The arguments that encode ``frames`` frames of a synthetic source with ``encoder``."""
    params_args: list[str] = []
    source = LAVFI_SMALL if small else LAVFI_VIDEO
    if params:
        assert encoder.params_arg is not None
        params_args = [
            encoder.params_arg,
            ":".join(f"{k}={escape_value(v)}" for k, v in params.items()),
        ]
    return [
        *source,
        "-frames:v",
        str(frames),
        "-pix_fmt",
        encoder.pix_fmts[str(depth)],  # type: ignore[index]
        "-c:v",
        encoder.id,
        *encoder.extra_args,
        *args,
        *params_args,
    ]


def sei_text(path: Path) -> str:
    """The settings string that x264 and x265 write into the stream."""
    match = re.search(rb"options: ([ -~]+)", path.read_bytes())
    assert match is not None, "no encoder settings SEI"
    return match.group(1).decode()


def sei_options(path: Path) -> dict[str, str]:
    """The settings SEI as ``name -> value``; a bare name is 1, ``no-name`` is 0."""
    out: dict[str, str] = {}
    for token in sei_text(path).split():
        if "=" in token:
            key, value = token.split("=", 1)
            out[key] = value
        elif token.startswith("no-"):
            out[token[3:]] = "0"
        else:
            out[token] = "1"
    if out.get("rskip") == "1" and "rskip-edge-threshold" in out:
        out["rskip"] = "2"
    return out
