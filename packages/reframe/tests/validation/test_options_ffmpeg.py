"""The advanced-option rules of validation (C-6, M9, ``video_option_rule_issues``) agree with
the real encoders (testdata/README.md "Advanced encoder options (C-6, complete option sets)").

Each row encodes the combination with the encoder itself (the parameters written directly,
not through the command builder, which leaves an inactive option out) and checks what the
encoder does: refuses to start (``encoder.option_conflict``), changes the value with or without
a message (``encoder.option_ignored``), or ignores the option (``encoder.option_inactive``).
Then validation must report exactly that code at that path.
"""

from __future__ import annotations

import hashlib
import re
import subprocess
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from reframe.definitions import load_definitions
from reframe.models import (
    AverageBitrate,
    CapabilitySnapshot,
    ConstantQuality,
    OptionValue,
    VideoSettings,
)
from reframe.validation.video import video_option_rule_issues

pytestmark = pytest.mark.needs_ffmpeg

DEFS = load_definitions()
#: Raw or IVF output: Matroska writes a random segment UID, so its files never compare equal.
_EXT = {"libx264": "h264", "libx265": "hevc", "libsvtav1": "ivf", "libvpx-vp9": "ivf"}


def _ffmpeg() -> str:
    from reframe_testing import media

    found = media.find_ffmpeg()
    assert found is not None
    return found


def _sei(path: Path) -> dict[str, str]:
    match = re.search(rb"options: ([ -~]+)", path.read_bytes())
    out: dict[str, str] = {}
    if match is None:
        return out
    for token in match.group(1).decode().split():
        key, sep, value = token.partition("=")
        if sep:
            out[key] = value
        elif key.startswith("no-"):
            out[key[3:]] = "0"
        else:
            out[key] = "1"
    return out


@dataclass(frozen=True)
class Encoded:
    returncode: int
    stderr: str
    sei: dict[str, str]
    digest: str


def _encode(
    encoder_id: str,
    values: dict[str, OptionValue],
    rate: Sequence[str],
    tmp: Path,
    name: str,
    frames: int = 3,
) -> Encoded:
    """Encode ``frames`` frames with ``values`` written by their mappings (inactive options
    too, unlike the command builder)."""
    encoder = DEFS.video_encoders[encoder_id]
    params: list[str] = []
    args: list[str] = []
    for key, value in values.items():
        option = encoder.option(key)
        assert option is not None, key
        text = ("1" if value else "0") if isinstance(value, bool) else str(value)
        mapping = option.mapping
        if mapping.kind == "x26x_param":
            params.append(f"{mapping.name}={text}")
        elif mapping.kind == "private_opt":
            args += [f"-{mapping.name}", text]
        else:
            args += [mapping.arg, text]
    if params:
        assert encoder.params_arg is not None
        args += [encoder.params_arg, ":".join(params)]
    preset = ["-preset", "10"] if encoder_id == "libsvtav1" else []
    out = tmp / f"{name}.{_EXT[encoder_id]}"
    result = subprocess.run(
        [
            _ffmpeg(), "-hide_banner", "-nostdin", "-y",
            "-f", "lavfi", "-i", "testsrc2=size=320x240:rate=25", "-frames:v", str(frames),
            "-pix_fmt", "yuv420p", "-c:v", encoder_id, *encoder.extra_args, *preset, *rate,
            *args, str(out),
        ],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )  # fmt: skip
    written = out.exists() and out.stat().st_size > 0 and result.returncode == 0
    sei = _sei(out) if written and encoder_id in ("libx264", "libx265") else {}
    digest = hashlib.sha256(out.read_bytes()).hexdigest() if written else ""
    return Encoded(result.returncode, result.stderr, sei, digest)


@dataclass(frozen=True)
class Row:
    id: str
    encoder: str
    values: dict[str, OptionValue]
    code: str
    path: str
    check: Callable[[Encoded], bool]
    rate_control: ConstantQuality | AverageBitrate = field(default_factory=ConstantQuality)
    rate: tuple[str, ...] = ()


def _fails(pattern: str) -> Callable[[Encoded], bool]:
    return lambda e: e.returncode != 0 and re.search(pattern, e.stderr) is not None


def _warns(pattern: str, **sei: str) -> Callable[[Encoded], bool]:
    def check(e: Encoded) -> bool:
        return (
            e.returncode == 0
            and re.search(pattern, e.stderr) is not None
            and all(e.sei.get(k) == v for k, v in sei.items())
        )

    return check


def _silent(**sei: str) -> Callable[[Encoded], bool]:
    def check(e: Encoded) -> bool:
        return e.returncode == 0 and all(e.sei.get(k) == v for k, v in sei.items())

    return check


INACTIVE, IGNORED, CONFLICT = (
    "encoder.option_inactive",
    "encoder.option_ignored",
    "encoder.option_conflict",
)
_VP9_CQ = ("-crf", "30", "-b:v", "0")
_VP9_ABR = ("-b:v", "500k")

ROWS = [
    # ---- inactive: the encoder ignores the option
    Row("x265 amp without rect", "libx265", {"amp": True, "rect": False}, INACTIVE,
        "video.advanced.amp", _silent(amp="0")),
    Row("x264 HRD without VBV", "libx264", {"nal-hrd": "vbr"}, INACTIVE,
        "video.advanced.nal-hrd", _warns(r"NAL HRD parameters require VBV parameters")),
    Row("x265 HRD without VBV", "libx265", {"hrd": True}, INACTIVE, "video.advanced.hrd",
        _warns(r"NAL HRD parameters require VBV parameters, ignored", hrd="0")),
    Row("x265 rd-refine at RD 4", "libx265", {"rd-refine": True, "rd": 4}, INACTIVE,
        "video.advanced.rd-refine",
        _warns(r"rd-refine disabled, requires RD level > 4 and adaptive quant")),
    Row("x265 limit-tu at TU inter depth 1", "libx265", {"limit-tu": 2}, INACTIVE,
        "video.advanced.limit-tu",
        _warns(r"limit-tu disabled, requires tu-inter-depth > 1", **{"limit-tu": "0"})),
    Row("x265 dynamic RD without VBV", "libx265", {"dynamic-rd": 2.0}, INACTIVE,
        "video.advanced.dynamic-rd",
        _warns(r"Dynamic-rd disabled, requires RD <= 4, VBV and aq-mode enabled")),
    Row("x264 psy-rd with psy off", "libx264", {"psy": False, "psy-rd": 1.2}, INACTIVE,
        "video.advanced.psy-rd", lambda e: e.returncode == 0 and "psy_rd" not in e.sei),
    Row("SVT-AV1 variance boost strength without boost", "libsvtav1",
        {"variance-boost-strength": 3}, INACTIVE, "video.advanced.variance-boost-strength",
        _warns(r"AQ mode / Variance Boost\s*:\s*2 / 0")),
    # ---- ignored: the encoder changes the value
    Row("x264 Blu-ray B-frames", "libx264", {"bluray-compat": True, "bframes": 5}, IGNORED,
        "video.advanced.bframes", _silent(bframes="3")),
    Row("x264 Blu-ray weighted P-frames", "libx264", {"bluray-compat": True, "weightp": "2"},
        IGNORED, "video.advanced.weightp", _silent(weightp="1")),
    Row("x264 Blu-ray B-pyramid", "libx264", {"bluray-compat": True, "b-pyramid": "normal"},
        IGNORED, "video.advanced.b-pyramid", _silent(b_pyramid="1")),
    Row("x265 TU size above the CTU", "libx265", {"ctu": "16", "max-tu-size": "32"}, IGNORED,
        "video.advanced.max-tu-size",
        _warns(r"Max TU size should be less than or equal to max CU size",
               **{"max-tu-size": "16"})),
    Row("x265 quantisation group above the CTU", "libx265", {"ctu": "32", "qg-size": "64"},
        IGNORED, "video.advanced.qg-size",
        _warns(r"QGSize should be less than or equal to maxCUSize", **{"qg-size": "32"})),
    Row("x265 pmode and limit-refs 2", "libx265", {"pmode": True, "limit-refs": "2"}, IGNORED,
        "video.advanced.limit-refs",
        _warns(r"Limit reference options 2 and 3 are not supported with pmode",
               **{"limit-refs": "0"})),
    Row("SVT-AV1 forward keyframes and 8-frame mini-GOPs", "libsvtav1",
        {"irefresh-type": "1", "hierarchical-levels": "3"}, IGNORED,
        "video.advanced.hierarchical-levels",
        _warns(r"Fwd key frame is only supported for hierarchical levels 4")),
    # ---- conflict: the encoder refuses to start
    Row("x265 min CU above the CTU", "libx265", {"ctu": "16", "min-cu-size": "32"}, CONFLICT,
        "video.advanced.min-cu-size",
        _fails(r"min CU size must be less than or equal to max CU size")),
    Row("SVT-AV1 min QP above max QP", "libsvtav1", {"min-qp": 40, "max-qp": 20}, CONFLICT,
        "video.advanced.min-qp",
        _fails(r"MinQpAllowed must be smaller than or equal to MaxQpAllowed")),
    Row("SVT-AV1 min QM above max QM", "libsvtav1",
        {"enable-qm": True, "qm-min": 12, "qm-max": 4}, CONFLICT, "video.advanced.qm-min",
        _fails(r"Min quant matrix level must not greater than max quant matrix level")),
    Row("VP9 qmin above qmax", "libvpx-vp9", {"qmin": 40, "qmax": 20}, CONFLICT,
        "video.advanced.qmin", _fails(r"Error while opening encoder|Failed to initialize"),
        rate_control=AverageBitrate(kbps=500), rate=_VP9_ABR),
    Row("VP9 CQ above qmax", "libvpx-vp9", {"qmax": 29}, CONFLICT, "video.advanced.qmax",
        _fails(r"CQ level 30 must be between minimum and maximum quantizer value \(0-29\)"),
        rate_control=ConstantQuality(value=30), rate=_VP9_CQ),
    Row("VP9 CQ below qmin", "libvpx-vp9", {"qmin": 31}, CONFLICT, "video.advanced.qmin",
        _fails(r"CQ level 30 must be between minimum and maximum quantizer value \(31-63\)"),
        rate_control=ConstantQuality(value=30), rate=_VP9_CQ),
]  # fmt: skip


@pytest.mark.parametrize("row", ROWS, ids=[r.id for r in ROWS])
def test_the_encoder_and_validation_agree(row: Row, tmp_path: Path) -> None:
    encoded = _encode(row.encoder, row.values, row.rate, tmp_path, "o")
    assert row.check(encoded), (encoded.returncode, encoded.sei, encoded.stderr[-1500:])
    video = VideoSettings(
        encoder=row.encoder, advanced=dict(row.values), rate_control=row.rate_control
    )
    issues = video_option_rule_issues(video, CapabilitySnapshot(), DEFS)
    assert [(i.code, i.path) for i in issues] == [(row.code, row.path)]


def test_vp9_rate_tolerances_do_nothing_in_constant_quality(tmp_path: Path) -> None:
    """libvpx's undershoot / overshoot are rate-control tolerances: a CQ encode (``-b:v 0``)
    is the same file with 0 and 100 (so they ``require`` average bitrate)."""
    low = _encode("libvpx-vp9", {"undershoot-pct": 0, "overshoot-pct": 0}, _VP9_CQ, tmp_path,
                  "low", frames=20)  # fmt: skip
    high = _encode("libvpx-vp9", {"undershoot-pct": 100, "overshoot-pct": 100}, _VP9_CQ,
                   tmp_path, "high", frames=20)  # fmt: skip
    assert low.digest
    assert low.digest == high.digest
    video = VideoSettings(
        encoder="libvpx-vp9",
        rate_control=ConstantQuality(value=30),
        advanced={"undershoot-pct": 50},
    )
    issues = video_option_rule_issues(video, CapabilitySnapshot(), DEFS)
    assert [(i.code, i.path) for i in issues] == [(INACTIVE, "video.advanced.undershoot-pct")]


def test_hdr10_opt_needs_bt2020(tmp_path: Path) -> None:
    """Recorded for the help text: x265 drops ``hdr10-opt`` unless the output is tagged
    BT.2020 ("Recommended Settings for HDR10-opt: colour primaries should be BT.2020,
    Disabling hdr10-opt.", exit 0). C-7 writes the source's tags when the output stays HDR."""
    plain = _encode("libx265", {"hdr10-opt": True}, (), tmp_path, "plain")
    assert plain.returncode == 0
    assert "colour primaries should be BT.2020" in plain.stderr
    assert plain.sei.get("hdr10-opt") == "0"
