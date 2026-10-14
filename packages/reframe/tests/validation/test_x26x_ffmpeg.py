"""The x264 / x265 option rules of validation agree with the real encoders
(testdata/README.md "Validation (C-8)").

- ``encoder.lookahead_too_short``: x265 stops ("Lookahead depth must be greater than the
  max consecutive bframe count", exit 183) exactly when validation reports the error; the
  per-preset defaults, the ``animation`` tune (+2 B-frames) and ``zerolatency`` (both 0)
  are taken into account.
- ``encoder.subme_needs_trellis``: x264 writes ``subme=9`` into its settings SEI exactly
  when validation warns (``subme`` 10 or 11 without ``trellis`` 2).
"""

from __future__ import annotations

import importlib.util
import re
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest

from reframe.models import OptionValue, VideoSettings
from reframe.validation.video import video_x26x_rule_issues

pytestmark = pytest.mark.needs_ffmpeg


def _load(name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        f"_reframe_validation_{name}", Path(__file__).with_name(f"{name}.py")
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


sc = _load("scenario")


def ffmpeg() -> str:
    from reframe_testing import media

    found = media.find_ffmpeg()
    assert found is not None
    return found


def encode(
    encoder: str, preset: str, tune: str | None, params: dict[str, OptionValue], out: Path
) -> subprocess.CompletedProcess[str]:
    source = "testsrc2=size=320x180:rate=24:duration=0.3"
    args = [ffmpeg(), "-hide_banner", "-nostdin", "-y", "-f", "lavfi", "-i", source,
            "-c:v", encoder, "-preset", preset]  # fmt: skip
    if tune is not None:
        args += ["-tune", tune]
    if params:
        flag = "-x265-params" if encoder == "libx265" else "-x264-params"
        args += [flag, ":".join(f"{k}={v}" for k, v in params.items())]
    return subprocess.run([*args, str(out)], capture_output=True, text=True, timeout=60)


def codes(encoder: str, preset: str, tune: str | None, params: dict[str, OptionValue]) -> set[str]:
    video = VideoSettings(encoder=encoder, preset=preset, tune=tune, advanced=params)
    return {i.code for i in video_x26x_rule_issues(video, sc.DEFS)}


@pytest.mark.parametrize(
    ("preset", "tune", "params"),
    [
        ("medium", None, {"rc-lookahead": 4, "bframes": 4}),
        ("medium", None, {"rc-lookahead": 5, "bframes": 4}),
        ("medium", None, {"rc-lookahead": 0, "bframes": 0}),
        ("medium", None, {"rc-lookahead": 0, "bframes": 4}),
        ("medium", None, {"rc-lookahead": 4}),
        ("medium", None, {"rc-lookahead": 5}),
        ("ultrafast", None, {"bframes": 4}),
        ("ultrafast", None, {"bframes": 5}),
        ("ultrafast", None, {"rc-lookahead": 3}),
        ("medium", None, {"bframes": 16}),
        ("medium", "zerolatency", {"bframes": 3}),
        ("medium", "zerolatency", {"rc-lookahead": 10}),
        ("medium", "animation", {"rc-lookahead": 5}),
        ("medium", "animation", {"rc-lookahead": 7}),
        ("medium", "animation", {"rc-lookahead": 5, "bframes": 4}),
        ("slower", "animation", {"rc-lookahead": 6}),
        ("slower", "animation", {"rc-lookahead": 11}),
    ],
)  # fmt: skip
def test_x265_lookahead_rule_matches_x265(
    tmp_path: Path, preset: str, tune: str | None, params: dict[str, OptionValue]
) -> None:
    result = encode("libx265", preset, tune, params, tmp_path / "out.hevc")
    stopped = "Lookahead depth must be greater than the max consecutive bframe count"
    assert result.returncode == 0 or stopped in result.stderr, result.stderr[-2000:]
    refused = result.returncode != 0
    assert ("encoder.lookahead_too_short" in codes("libx265", preset, tune, params)) is refused


@pytest.mark.parametrize(
    ("preset", "params"),
    [
        ("medium", {"subme": 10, "trellis": "1"}),
        ("medium", {"subme": 10, "trellis": "2"}),
        ("medium", {"subme": 11, "trellis": "0"}),
        ("medium", {"subme": 10}),
        ("slow", {"subme": 10}),
        ("veryslow", {}),
        ("veryslow", {"trellis": "1"}),
        ("placebo", {"trellis": "0"}),
    ],
)  # fmt: skip
def test_x264_subme_rule_matches_x264(
    tmp_path: Path, preset: str, params: dict[str, OptionValue]
) -> None:
    out = tmp_path / "out.h264"
    result = encode("libx264", preset, None, params, out)
    assert result.returncode == 0, result.stderr[-2000:]
    written = re.search(rb" subme=(\d+)", out.read_bytes())
    assert written is not None
    asked = params.get("subme") or {"medium": 7, "slow": 8, "veryslow": 10, "placebo": 11}[preset]
    lowered = int(written.group(1)) < int(str(asked))
    assert ("encoder.subme_needs_trellis" in codes("libx264", preset, None, params)) is lowered
