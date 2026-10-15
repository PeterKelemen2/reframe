"""The definitions checked against the real FFmpeg build (``needs_ffmpeg``; ``needs_gpu`` for
the AMF / VAAPI encodes).

These tests are the record of where the data comes from: every private option name, preset,
tune, profile and level against ``ffmpeg -h encoder=<id>``; the x264 / x265 per-preset
defaults against what the libraries write into the stream; every rate-control argument,
audio bitrate and sample rate against a real encode; what each muxer accepts and which
flags it writes; and every filter chain against a real run. testdata/README.md
("Encoder definitions (C-6)") has the results as tables.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import struct
import subprocess
from collections.abc import Callable, Iterable, Sequence
from concurrent.futures import ThreadPoolExecutor
from functools import cache
from pathlib import Path
from typing import Any, cast

import pytest

from reframe.capabilities.parse import parse_encoder_help
from reframe.definitions import (
    ChoiceSetting,
    CodecSupport,
    ContainerDef,
    EncoderOption,
    QualityMode,
    VideoEncoderDef,
    load_definitions,
    supported_presets,
)
from reframe.definitions.models import TRACK_FLAGS, OptionMapping
from reframe.models.capabilities import EncoderStatus
from reframe.models.job import Container, OptionValue
from reframe.tools.versions import parse_ffmpeg_version

pytestmark = pytest.mark.needs_ffmpeg

DEFS = load_definitions()
VIDEO = DEFS.video_encoders
SOFTWARE = [e for e in VIDEO if not VIDEO[e].hardware]
_LAVFI_VIDEO = ["-f", "lavfi", "-i", "testsrc2=size=320x240:rate=25"]
#: Small enough for every level (H.265 level 1 allows 36 864 luma samples per picture).
_LAVFI_SMALL = ["-f", "lavfi", "-i", "testsrc2=size=160x96:rate=15"]
_GENERIC_ARGS = frozenset(
    {
        "-b:v",
        "-global_quality",
        "-pass",
        "-passlogfile",
        "-g",
        "-bf",
        "-refs",
        "-profile",
        "-level",
        "-compression_level",
        "-q:a",
        "-crf",
    }
)


# =========================================================================== helpers


def _tools() -> tuple[str, str]:
    from reframe_testing import media

    ffmpeg, ffprobe = media.find_ffmpeg(), media.find_ffprobe()
    assert ffmpeg is not None
    assert ffprobe is not None
    return ffmpeg, ffprobe


def _ffmpeg(args: Sequence[str], timeout: float = 120) -> subprocess.CompletedProcess[str]:
    ffmpeg, _ = _tools()
    return subprocess.run(
        [ffmpeg, "-hide_banner", "-nostdin", "-y", *args],
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )


def _probe(path: Path, *entries: str) -> dict[str, Any]:
    _, ffprobe = _tools()
    out = subprocess.run(
        [ffprobe, "-v", "error", "-of", "json", *entries, str(path)],
        capture_output=True,
        text=True,
        timeout=60,
        check=True,
    )
    result: dict[str, Any] = json.loads(out.stdout)
    return result


def _parallel[T](jobs: Iterable[T], run: Callable[[T], str | None]) -> list[str]:
    """Run ``run`` for every job in a thread pool; the problems it returns, in order."""
    with ThreadPoolExecutor(max_workers=min(8, os.cpu_count() or 2)) as pool:
        return [p for p in pool.map(run, list(jobs)) if p]


#: libx264, libx265 and libsvtav1 do not fail on a bad params entry: they log one of these
#: and encode on (exit 0).
_PARAM_ERRORS = re.compile(r"Error parsing option|Unknown option|Invalid value|bad parameter")


def _param_error(result: subprocess.CompletedProcess[str]) -> str | None:
    found = [ln for ln in result.stderr.splitlines() if _PARAM_ERRORS.search(ln)]
    return " | ".join(found) if found else None


def _fail_text(result: subprocess.CompletedProcess[str]) -> str:
    lines = [ln for ln in result.stderr.splitlines() if ln.strip()]
    return " | ".join(lines[-3:])


@cache
def _encoders_in_build() -> frozenset[str]:
    names = set()
    for line in _ffmpeg(["-encoders"]).stdout.splitlines():
        parts = line.split()
        if len(parts) >= 2 and re.fullmatch(r"[VAS][F.][S.][X.][B.][D.]", parts[0]):
            names.add(parts[1])
    return frozenset(names)


@cache
def _series() -> tuple[int, int]:
    """``(major, minor)`` of the FFmpeg build under test (``(8, 1)`` for n8.1.3)."""
    version = parse_ffmpeg_version(_ffmpeg(["-version"]).stdout)
    assert version is not None
    assert version.series is not None
    return version.series


#: Choices that older FFmpeg builds do not have: (encoder, setting, value) → the first
#: ``(major, minor)`` with it. FFmpeg n8.1.3 has no ``high_quality`` constant for
#: ``h264_amf`` / ``hevc_amf`` ``-quality`` (only speed, balanced, quality); n9.0.2 has it.
_ADDED_IN: dict[tuple[str, str, str], tuple[int, int]] = {
    ("h264_amf", "presets", "high_quality"): (9, 0),
    ("hevc_amf", "presets", "high_quality"): (9, 0),
}


@cache
def _help_text(encoder: str) -> str:
    return _ffmpeg(["-h", f"encoder={encoder}"]).stdout


@cache
def _help_range(encoder: str, option: str) -> tuple[float, float]:
    """``(from, to)`` of a private option in ``ffmpeg -h encoder=<id>``."""
    match = re.search(
        rf"^  -{re.escape(option)}\s+<[^>]+>.*\(from (-?[\d.]+) to (-?[\d.]+)\)",
        _help_text(encoder),
        re.MULTILINE,
    )
    assert match is not None, f"{encoder} -{option}"
    return float(match.group(1)), float(match.group(2))


@cache
def _help(encoder: str) -> dict[str, set[str]]:
    """``ffmpeg -h encoder=<id>``: private option name → its named constants."""
    options: dict[str, set[str]] = {}
    current: set[str] | None = None
    for line in _help_text(encoder).splitlines():
        opt = re.match(r"^  -(\S+)\s+<", line)
        if opt:
            current = options.setdefault(opt.group(1), set())
            continue
        const = re.match(r"^     (\S+)\s", line)
        if const and current is not None:
            current.add(const.group(1))
    return options


def _need_encoder(encoder: str) -> None:
    if encoder not in _encoders_in_build():
        pytest.skip(f"{encoder} is not in this FFmpeg build")


def _mapping_args(mapping: OptionMapping, value: str) -> tuple[list[str], dict[str, str]]:
    if mapping.kind == "x26x_param":
        return [], {mapping.name: value}
    if mapping.kind == "ffmpeg_arg":
        return [mapping.arg, value], {}
    return [f"-{mapping.name}", value], {}


def _written(value: OptionValue) -> str:
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def _encode_args(
    encoder: VideoEncoderDef,
    args: Sequence[str] = (),
    params: dict[str, str] | None = None,
    depth: int = 8,
    frames: int = 3,
    small: bool = False,
) -> list[str]:
    params_args: list[str] = []
    source = _LAVFI_SMALL if small else _LAVFI_VIDEO
    if params:
        assert encoder.params_arg is not None
        params_args = [encoder.params_arg, ":".join(f"{k}={v}" for k, v in params.items())]
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


# =========================================================================== help output


@pytest.mark.parametrize("encoder_id", sorted(VIDEO))
def test_private_options_and_choices_exist_in_the_build(encoder_id: str) -> None:
    """Every private option the definitions write is listed by ``ffmpeg -h encoder=<id>``,
    and every choice of an option with named constants is one of them."""
    _need_encoder(encoder_id)
    enc = VIDEO[encoder_id]
    known = _help(encoder_id)
    problems: list[str] = []
    if enc.params_arg is not None and enc.params_arg.lstrip("-") not in known:
        problems.append(f"params argument {enc.params_arg}")
    settings: list[tuple[str, ChoiceSetting]] = [
        (name, s)
        for name in ("presets", "tunes", "profiles", "levels")
        if (s := getattr(enc, name)) is not None
    ]
    series = _series()
    for name, setting in settings:
        if setting.mapping.kind != "private_opt":
            continue
        opt = setting.mapping.name
        if opt not in known:
            problems.append(f"{name}: -{opt}")
        elif known[opt]:  # named constants: every choice must be one
            missing = [c.written for c in setting.choices if c.written not in known[opt]]
            older = {
                value
                for (e, n, value), since in _ADDED_IN.items()
                if (e, n) == (encoder_id, name) and series < since
            }
            if set(missing) != older:
                problems.append(f"{name}: {missing} not constants of -{opt}, expected {older}")
            if name == "presets" and older:
                # The product hides them: C-4 reads the build's presets, supported_presets
                # offers only those.
                parsed = parse_encoder_help(_help_text(encoder_id))
                assert parsed is not None
                status = EncoderStatus(
                    id=encoder_id, presets=parsed.presets, private_options=parsed.private_options
                )
                offered = {c.value for c in supported_presets(enc, status)}
                if offered & older:
                    problems.append(f"presets {sorted(offered & older)} offered by the build")
    for option in enc.options:
        if option.mapping.kind == "private_opt":
            if option.mapping.name not in known:
                problems.append(f"option {option.key}: -{option.mapping.name}")
            elif option.type == "enum" and known[option.mapping.name]:
                missing = [
                    c.value
                    for c in option.choices or []
                    if c.value not in known[option.mapping.name]
                ]
                if missing:
                    problems.append(f"option {option.key}: {missing}")
    rc_args: list[str] = []
    if enc.rate_control.quality is not None:
        rc_args += enc.rate_control.quality.args
    if enc.rate_control.bitrate is not None:
        b = enc.rate_control.bitrate
        rc_args += b.args
        if b.two_pass is not None:
            rc_args += [*b.two_pass.args, *b.two_pass.turbo_args, *b.two_pass.full_args]
    rc_args += enc.extra_args
    for i, arg in enumerate(rc_args):
        if not arg.startswith("-") or arg in _GENERIC_ARGS:
            continue
        name = arg[1:]
        if name not in known:
            problems.append(f"rate control / extra argument {arg}")
            continue
        value = rc_args[i + 1] if i + 1 < len(rc_args) else ""
        if (
            known[name]
            and "{" not in value
            and not value.lstrip("-").isdigit()
            and value not in known[name]
        ):
            problems.append(f"{arg} {value}: not a constant")
    assert problems == []


@pytest.mark.parametrize("encoder_id", ["libx264", "libx265"])
def test_x26x_lists_match_the_library(encoder_id: str) -> None:
    """x264 / x265 take free text; the library prints its own lists for a bad value."""
    enc = VIDEO[encoder_id]
    out = _ffmpeg([*_encode_args(enc, ["-preset", "bogus"]), "-f", "null", "-"]).stderr
    presets = re.search(r"Possible presets: (.+)", out)
    tunes = re.search(r"Possible tunes: (.+)", out)
    assert presets is not None
    assert tunes is not None
    assert enc.presets is not None
    assert enc.tunes is not None
    assert enc.presets.values() == presets.group(1).split()
    library_tunes = set(tunes.group(1).split())
    assert set(enc.tunes.values()) | {"fastdecode"} <= library_tunes
    out = _ffmpeg([*_encode_args(enc, ["-profile", "bogus"]), "-f", "null", "-"]).stderr
    profiles = re.search(r"Possible profiles: (.+)", out)
    assert profiles is not None
    assert enc.profiles is not None
    assert set(enc.profiles.values()) <= set(profiles.group(1).split())


# =========================================================================== x264 / x265 SEI


def _sei_options(path: Path) -> dict[str, str]:
    match = re.search(rb"options: ([ -~]+)", path.read_bytes())
    assert match is not None, "no encoder settings SEI"
    out: dict[str, str] = {}
    for token in match.group(1).decode().split():
        if "=" in token:
            key, value = token.split("=", 1)
            out[key] = value
        elif token.startswith("no-"):
            out[token[3:]] = "0"
        else:
            out[token] = "1"
    if out.get("rskip") == "1" and "rskip-edge-threshold" in out:
        # x265 4.3 writes rskip=2 as "rskip=1 rskip-edge-threshold=0.050000".
        out["rskip"] = "2"
    return out


def _part(value: str, index: int, sep: str = ":") -> str:
    return value.split(sep)[index]


def _on(value: str) -> bool:
    return value == "1"


#: x264's ``analyse=<intra>:<inter>`` partition flags of the ``partitions`` choices.
_X264_PARTITIONS = {
    "0": "none",
    "0x3": "i8x8,i4x4",
    "0x113": "p8x8,b8x8,i8x8,i4x4",
    "0x133": "all",
}
#: ISO/IEC 23091-2 code points of the colour names (x265's settings SEI writes the numbers).
_CODE_POINTS: dict[str, dict[int, str]] = {
    "colorprim": {
        1: "bt709", 4: "bt470m", 5: "bt470bg", 6: "smpte170m", 7: "smpte240m", 8: "film",
        9: "bt2020", 10: "smpte428", 11: "smpte431", 12: "smpte432",
    },
    "transfer": {
        1: "bt709", 4: "bt470m", 5: "bt470bg", 6: "smpte170m", 7: "smpte240m", 8: "linear",
        9: "log100", 10: "log316", 11: "iec61966-2-4", 12: "bt1361e", 13: "iec61966-2-1",
        14: "bt2020-10", 15: "bt2020-12", 16: "smpte2084", 17: "smpte428", 18: "arib-std-b67",
    },
    "colormatrix": {
        0: "gbr", 1: "bt709", 4: "fcc", 5: "bt470bg", 6: "smpte170m", 7: "smpte240m",
        8: "ycgco", 9: "bt2020nc", 10: "bt2020c", 11: "smpte2085", 12: "chroma-derived-nc",
        13: "chroma-derived-c", 14: "ictcp",
    },
}  # fmt: skip


#: Option key → (SEI key, value as the definitions store it) for x264 and x265.
_SEI: dict[str, dict[str, tuple[str, Callable[[str], OptionValue | None]]]] = {
    "libx264": {
        "bframes": ("bframes", int),
        "b-adapt": ("b_adapt", str),
        "b-pyramid": ("b_pyramid", lambda v: {"0": "none", "1": "strict", "2": "normal"}[v]),
        "ref": ("ref", int),
        "keyint": ("keyint", int),
        "min-keyint": ("keyint_min", int),
        "scenecut": ("scenecut", int),
        "rc-lookahead": ("rc_lookahead", int),
        "weightp": ("weightp", str),
        "aq-mode": ("aq", lambda v: _part(v, 0)),
        "aq-strength": ("aq", lambda v: float(_part(v, 1)) if ":" in v else None),
        "mbtree": ("mbtree", lambda v: v == "1"),
        "qcomp": ("qcomp", float),
        "vbv-maxrate": ("vbv_maxrate", int),
        "vbv-bufsize": ("vbv_bufsize", int),
        "psy-rd": ("psy_rd", lambda v: float(_part(v, 0))),
        "psy-trellis": ("psy_rd", lambda v: float(_part(v, 1))),
        "deblock-alpha": ("deblock", lambda v: int(_part(v, 1))),
        "deblock-beta": ("deblock", lambda v: int(_part(v, 2))),
        "me": ("me", str),
        "subme": ("subme", int),
        "merange": ("me_range", int),
        "trellis": ("trellis", str),
        "direct": (
            "direct",
            lambda v: {"0": "none", "1": "spatial", "2": "temporal", "3": "auto"}[v],
        ),
        # M9
        "open-gop": ("open_gop", _on),
        "b-bias": ("b_bias", int),
        "weightb": ("weightb", _on),
        "bluray-compat": ("bluray_compat", _on),
        "ipratio": ("ip_ratio", float),
        "pbratio": ("pb_ratio", float),
        "qpmin": ("qpmin", int),
        "qpmax": ("qpmax", int),
        "nal-hrd": ("nal_hrd", str),
        "partitions": ("analyse", lambda v: _X264_PARTITIONS[_part(v, 1)]),
        "8x8dct": ("8x8dct", _on),
        "mixed-refs": ("mixed_ref", _on),
        "fast-pskip": ("fast_pskip", _on),
        "chroma-me": ("chroma_me", _on),
        "dct-decimate": ("decimate", _on),
        "cabac": ("cabac", _on),
        "psy": ("psy", _on),
        "nr": ("nr", int),
        "deadzone-inter": ("deadzone", lambda v: int(_part(v, 0, ","))),
        "deadzone-intra": ("deadzone", lambda v: int(_part(v, 1, ","))),
        "cqm": ("cqm", lambda v: {"0": "flat", "1": "jvt"}[v]),
        "threads": ("threads", int),
        "lookahead-threads": ("lookahead_threads", int),
        "sliced-threads": ("sliced_threads", _on),
    },
    "libx265": {
        "bframes": ("bframes", int),
        "b-adapt": ("b-adapt", str),
        "ref": ("ref", int),
        "keyint": ("keyint", int),
        "min-keyint": ("min-keyint", int),
        "scenecut": ("scenecut", int),
        "rc-lookahead": ("rc-lookahead", int),
        "aq-mode": ("aq-mode", str),
        "aq-strength": ("aq-strength", float),
        "cutree": ("cutree", lambda v: v == "1"),
        "psy-rd": ("psy-rd", float),
        "psy-rdoq": ("psy-rdoq", float),
        "rdoq-level": ("rdoq-level", str),
        "rd": ("rd", int),
        "me": ("me", str),
        "subme": ("subme", int),
        "merange": ("merange", int),
        "ctu": ("ctu", str),
        "deblock-tc": ("deblock", lambda v: int(_part(v, 0)) if ":" in v else None),
        "deblock-beta": ("deblock", lambda v: int(_part(v, 1)) if ":" in v else None),
        "sao": ("sao", lambda v: v == "1"),
        "limit-sao": ("limit-sao", lambda v: v == "1"),
        "selective-sao": ("selective-sao", int),
        "strong-intra-smoothing": ("strong-intra-smoothing", lambda v: v == "1"),
        "hdr10": ("hdr10", lambda v: v == "1"),
        "hdr10-opt": ("hdr10-opt", lambda v: v == "1"),
        "master-display": ("master-display", str),
        "max-cll": ("cll", str),
        "repeat-headers": ("repeat-headers", lambda v: v == "1"),
        # M9
        "b-pyramid": ("b-pyramid", _on),
        "bframe-bias": ("bframe-bias", int),
        "b-intra": ("b-intra", _on),
        "weightp": ("weightp", _on),
        "weightb": ("weightb", _on),
        "open-gop": ("open-gop", _on),
        "vbv-maxrate": ("vbv-maxrate", int),
        "vbv-bufsize": ("vbv-bufsize", int),
        "hrd": ("hrd", _on),
        "qcomp": ("qcomp", float),
        "ipratio": ("ipratio", float),
        "pbratio": ("pbratio", float),
        "qpmin": ("qpmin", int),
        "qpmax": ("qpmax", int),
        "aq-motion": ("aq-motion", _on),
        "qg-size": ("qg-size", str),
        "rc-grain": ("rc-grain", _on),
        "cbqpoffs": ("cbqpoffs", int),
        "crqpoffs": ("crqpoffs", int),
        "limit-refs": ("limit-refs", str),
        "limit-modes": ("limit-modes", _on),
        "rect": ("rect", _on),
        "amp": ("amp", _on),
        "min-cu-size": ("min-cu-size", str),
        "max-tu-size": ("max-tu-size", str),
        "tu-intra-depth": ("tu-intra-depth", int),
        "tu-inter-depth": ("tu-inter-depth", int),
        "limit-tu": ("limit-tu", int),
        "early-skip": ("early-skip", _on),
        "rskip": ("rskip", str),
        "fast-intra": ("fast-intra", _on),
        "tskip": ("tskip", _on),
        "max-merge": ("max-merge", int),
        "temporal-mvp": ("temporal-mvp", _on),
        "signhide": ("signhide", _on),
        "rd-refine": ("rd-refine", _on),
        "dynamic-rd": ("dynamic-rd", float),
        "nr-intra": ("nr-intra", int),
        "nr-inter": ("nr-inter", int),
        "sao-non-deblock": ("sao-non-deblock", _on),
        # x265 writes the colour tags as ISO/IEC 23091-2 code points.
        "colorprim": ("colorprim", lambda v: _CODE_POINTS["colorprim"][int(v)]),
        "transfer": ("transfer", lambda v: _CODE_POINTS["transfer"][int(v)]),
        "colormatrix": ("colormatrix", lambda v: _CODE_POINTS["colormatrix"][int(v)]),
        "aud": ("aud", _on),
        "frame-threads": ("frame-threads", int),
        "wpp": ("wpp", _on),
        "pmode": ("pmode", _on),
        "pme": ("pme", _on),
        "lookahead-slices": ("lookahead-slices", int),
    },
}

#: Options read from the stream's VUI with ffprobe (x264 does not list them in its SEI):
#: option key → ffprobe stream field.
_VUI: dict[str, dict[str, str]] = {
    "libx264": {
        "colorprim": "color_primaries",
        "transfer": "color_transfer",
        "colormatrix": "color_space",
        "chromaloc": "chroma_location",
    },
    # x265's SEI has only "chromaloc=1" (present) and a range flag: ffprobe reads the VUI.
    "libx265": {"range": "color_range", "chromaloc": "chroma_location"},
}
#: ffprobe's names of the values of VUI options.
_VUI_VALUES: dict[str, dict[str, str]] = {
    "chromaloc": {
        "0": "left",
        "1": "center",
        "2": "topleft",
        "3": "top",
        "4": "bottomleft",
        "5": "bottom",
    },
    "range": {"limited": "tv", "full": "pc"},
}
#: Options checked in the encoder's log: option key → (pattern with ``{value}``).
_LOG: dict[str, dict[str, str]] = {
    "libx264": {},
    "libx265": {"pools": "Thread pool created using {value} threads"},
}
#: x265 turns lookahead-slices off below 720 lines: its table is read from a 720p encode.
_SEI_720P = frozenset({"lookahead-slices"})

_EXT = {"libx264": "h264", "libx265": "hevc"}


@pytest.mark.parametrize("encoder_id", ["libx264", "libx265"])
def test_per_preset_defaults_match_the_library(encoder_id: str, tmp_path: Path) -> None:
    """Every per-preset default table equals what the library writes for that preset."""
    enc = VIDEO[encoder_id]
    assert enc.presets is not None
    sei = _SEI[encoder_id]

    def check(preset: str) -> str | None:
        out = tmp_path / f"{preset}.{_EXT[encoder_id]}"
        result = _ffmpeg([*_encode_args(enc, ["-preset", preset]), str(out)])
        if result.returncode:
            return f"{preset}: {_fail_text(result)}"
        options = _sei_options(out)
        options_720p: dict[str, str] = {}
        if any(o.key in _SEI_720P for o in enc.options):
            big = tmp_path / f"{preset}-720p.{_EXT[encoder_id]}"
            source = ["-f", "lavfi", "-i", "testsrc2=size=1280x720:rate=25"]
            args = [*source, *_encode_args(enc, ["-preset", preset])[len(_LAVFI_VIDEO) :]]
            result = _ffmpeg([*args, str(big)])
            if result.returncode:
                return f"{preset} 720p: {_fail_text(result)}"
            options_720p = _sei_options(big)
        wrong = []
        for option in enc.options:
            if option.default.kind == "fixed" and option.key in sei:
                key, convert = sei[option.key]
                if key in options and convert(options[key]) != option.default.value:
                    wrong.append(f"{option.key}={options[key]} (fixed {option.default.value})")
            if option.default.kind != "preset":
                continue
            key, convert = sei[option.key]
            read = options_720p if option.key in _SEI_720P else options
            actual = convert(read[key]) if key in read else None
            expected = option.default.values.get(preset)
            if actual != expected:
                wrong.append(f"{option.key}: library {actual!r}, table {expected!r}")
        return f"{preset}: {wrong}" if wrong else None

    assert _parallel(enc.presets.values(), check) == []


def _build_params(
    enc: VideoEncoderDef, values: dict[str, OptionValue], preset: str
) -> dict[str, str]:
    """The params a builder writes for ``values`` (composite parts joined with ``,``)."""
    params: dict[str, str] = {}
    composite: dict[str, dict[int, str]] = {}
    for option in enc.options:
        if option.mapping.kind != "x26x_param":
            continue
        name, part = option.mapping.name, option.mapping.part
        if option.key in values:
            value = _written(values[option.key])
        elif part is not None and option.default.kind == "preset":
            value = _written(option.default.values[preset])
        else:
            continue
        if part is None:
            params[name] = value
        else:
            composite.setdefault(name, {})[part] = value
    for name, parts in composite.items():
        if any(
            o.key in values
            for o in enc.options
            if o.mapping.kind == "x26x_param" and o.mapping.name == name
        ):
            params[name] = ",".join(parts[i] for i in sorted(parts))
    return params


#: A non-default value for every option, to see that the parameter reaches the library.
_TEST_VALUES: dict[str, dict[str, OptionValue]] = {
    "libx264": {
        "bframes": 5,
        "b-adapt": "2",
        "b-pyramid": "strict",
        "ref": 4,
        "keyint": 120,
        "min-keyint": 12,
        "scenecut": 30,
        "rc-lookahead": 25,
        "weightp": "1",
        "aq-mode": "2",
        "aq-strength": 0.8,
        "mbtree": False,
        "qcomp": 0.7,
        "vbv-maxrate": 5000,
        "vbv-bufsize": 10000,
        "psy-rd": 1.1,
        "psy-trellis": 0.2,
        "deblock-alpha": -1,
        "deblock-beta": -2,
        "me": "umh",
        "subme": 9,
        "merange": 20,
        "trellis": "2",
        "direct": "auto",
        "open-gop": True,
        "b-bias": 10,
        "weightb": False,
        "ipratio": 1.5,
        "pbratio": 1.2,
        "qpmin": 2,
        "qpmax": 60,
        "nal-hrd": "vbr",
        "partitions": "all",
        "mixed-refs": False,
        "fast-pskip": False,
        "chroma-me": False,
        "dct-decimate": False,
        "nr": 100,
        "deadzone-inter": 10,
        "deadzone-intra": 8,
        "cqm": "jvt",
        "threads": 4,
        "lookahead-threads": 2,
        "colorprim": "bt2020",
        "transfer": "smpte2084",
        "colormatrix": "bt2020nc",
        "chromaloc": "2",
        # Later encodes (they change other values): see _LATER.
        "psy": False,
        "cabac": False,
        "8x8dct": False,
        "sliced-threads": True,
        "bluray-compat": True,
    },
    "libx265": {
        "bframes": 6,
        "b-adapt": "1",
        "ref": 2,
        "keyint": 120,
        "min-keyint": 12,
        "scenecut": 30,
        "rc-lookahead": 30,
        "aq-mode": "3",
        "aq-strength": 0.8,
        "cutree": False,
        "psy-rd": 1.5,
        "psy-rdoq": 2.0,
        "rdoq-level": "1",
        "rd": 4,
        "me": "2",
        "subme": 3,
        "merange": 48,
        "ctu": "32",
        "deblock-tc": -1,
        "deblock-beta": -2,
        "sao": False,
        "limit-sao": True,
        "selective-sao": 2,
        "strong-intra-smoothing": False,
        "hdr10": True,
        "hdr10-opt": True,
        "master-display": "G(13250,34500)B(7500,3000)R(34000,16000)WP(15635,16450)L(10000000,1)",
        "max-cll": "1000,400",
        "repeat-headers": True,
        "b-pyramid": False,
        "bframe-bias": 10,
        "b-intra": False,
        "weightp": False,
        "weightb": True,
        "open-gop": False,
        "vbv-maxrate": 5000,
        "vbv-bufsize": 10000,
        "hrd": True,
        "qcomp": 0.7,
        "ipratio": 1.5,
        "pbratio": 1.2,
        "qpmin": 2,
        "qpmax": 60,
        "aq-motion": True,
        "qg-size": "16",
        "rc-grain": True,
        "cbqpoffs": -2,
        "crqpoffs": -3,
        "limit-refs": "2",
        "limit-modes": True,
        "rect": True,
        "amp": True,
        "min-cu-size": "16",
        "max-tu-size": "16",
        "tu-intra-depth": 3,
        "tu-inter-depth": 3,
        "limit-tu": 2,
        "early-skip": False,
        "rskip": "2",
        "fast-intra": True,
        "tskip": True,
        "max-merge": 4,
        "temporal-mvp": False,
        "signhide": False,
        "dynamic-rd": 2.0,
        "nr-intra": 100,
        "nr-inter": 200,
        # hdr10-opt needs BT.2020 colour: these are also the values the test writes for it.
        "colorprim": "bt2020",
        "transfer": "smpte2084",
        "colormatrix": "bt2020nc",
        "range": "full",
        "chromaloc": "2",
        "aud": True,
        "frame-threads": 2,
        "wpp": False,
        "pmode": True,
        "pme": True,
        "pools": "2",
        # Later encodes: see _LATER.
        "rd-refine": True,
        "sao-non-deblock": True,
        "lookahead-slices": 2,
    },
}

#: Values checked in later encodes, with the other values they need (x265 turns SAO back on
#: for selective-sao even with sao=0; rd-refine needs RD 5 or 6; lookahead-slices needs 720
#: lines; pmode turns limit-refs 2 and 3 off; x264's psy=0 drops psy-rd from the SEI, cabac=0
#: and 8x8dct=0 change the partitions, bluray-compat lowers the B-frames and weighted
#: P-frames, cqm=jvt raises qpmin).
_LATER: dict[str, list[tuple[dict[str, OptionValue], dict[str, OptionValue]]]] = {
    "libx264": [
        (
            {"psy": False, "cabac": False, "8x8dct": False, "sliced-threads": True},
            {"partitions": "none"},
        ),
        ({"bluray-compat": True}, {}),
        ({"cqm": "jvt"}, {}),
    ],
    "libx265": [
        ({"limit-sao": True, "selective-sao": 2, "sao-non-deblock": True}, {"sao": True}),
        ({"rd-refine": True}, {"rd": 5}),
        ({"lookahead-slices": 2}, {}),
        ({"pmode": True}, {}),
    ],
}


@pytest.mark.parametrize("encoder_id", ["libx264", "libx265"])
def test_every_x26x_option_reaches_the_library(encoder_id: str, tmp_path: Path) -> None:
    """Every option set to a value that is not its default shows up in what the library
    writes: the settings SEI, the VUI (x264's colour tags, read with ffprobe) or the log."""
    enc = VIDEO[encoder_id]
    values = _TEST_VALUES[encoder_id]
    assert set(values) == {o.key for o in enc.options}
    sei, vui, log = _SEI[encoder_id], _VUI[encoder_id], _LOG[encoder_id]
    assert set(sei) | set(vui) | set(log) >= set(values)
    later = _LATER[encoder_id]
    later_keys = {k for checked, _ in later for k in checked}
    sets: list[tuple[dict[str, OptionValue], dict[str, OptionValue]]] = [
        ({k: v for k, v in values.items() if k not in later_keys}, {})
    ]
    sets += [({k: values[k] for k in checked}, extra) for checked, extra in later]
    for index, (checked, extra) in enumerate(sets):
        out = tmp_path / f"o{index}.{_EXT[encoder_id]}"
        params = _build_params(enc, {**checked, **extra}, "medium")
        if encoder_id == "libx265" and "colorprim" not in params:
            # hdr10-opt needs BT.2020 colour ("Recommended Settings for HDR10-opt: colour
            # primaries should be BT.2020, Disabling hdr10-opt."); C-7 writes these tags.
            params |= {"colorprim": "bt2020", "transfer": "smpte2084", "colormatrix": "bt2020nc"}
        args = _encode_args(enc, ["-preset", "medium"], params, depth=10)
        if "lookahead-slices" in checked:
            args = ["-f", "lavfi", "-i", "testsrc2=size=1280x720:rate=25", *args[4:]]
        result = _ffmpeg([*args, str(out)])
        assert result.returncode == 0, _fail_text(result)
        assert _param_error(result) is None
        options = _sei_options(out)
        stream: dict[str, Any] = {}
        if any(key in vui for key in checked):
            stream = _probe(out, "-show_streams")["streams"][0]
        for key, value in checked.items():
            if key in log:
                assert log[key].format(value=value) in result.stderr, key
                continue
            if key in vui:
                expected = _VUI_VALUES.get(key, {}).get(str(value), value)
                assert stream.get(vui[key]) == expected, key
                continue
            sei_key, convert = sei[key]
            assert sei_key in options, key
            got = convert(options[sei_key])
            if isinstance(value, float):
                assert got == pytest.approx(value), key
            else:
                assert got == value, key


def test_x265_level_idc_reaches_the_library(tmp_path: Path) -> None:
    enc = VIDEO["libx265"]
    assert enc.levels is not None
    out = tmp_path / "o.hevc"
    result = _ffmpeg([*_encode_args(enc, [], {"level-idc": "4.1"}), str(out)])
    assert result.returncode == 0, _fail_text(result)
    assert _sei_options(out)["level-idc"] == "41"


# =========================================================================== software choices


def _choice_jobs(enc: VideoEncoderDef) -> list[tuple[str, list[str], dict[str, str], int]]:
    jobs: list[tuple[str, list[str], dict[str, str], int]] = []
    for name in ("presets", "tunes", "profiles", "levels"):
        setting: ChoiceSetting | None = getattr(enc, name)
        if setting is None:
            continue
        for choice in setting.choices:
            depths = choice.bit_depths or [int(d) for d in enc.pix_fmts]
            for depth in depths:
                if str(depth) not in enc.pix_fmts:
                    continue
                args, params = _mapping_args(setting.mapping, choice.written)
                jobs.append((f"{name}={choice.value}@{depth}", args, params, depth))
    if enc.fast_decode is not None:
        fd = enc.fast_decode
        args = ["-tune", fd.tune] if fd.tune else list(fd.args)
        jobs.append(("fast_decode", args, dict(fd.params), 8))
    return jobs


@pytest.mark.parametrize("encoder_id", SOFTWARE)
def test_every_software_choice_encodes(encoder_id: str) -> None:
    """Every preset, tune, profile and level (at each bit depth it is valid for) encodes."""
    enc = VIDEO[encoder_id]

    def run(job: tuple[str, list[str], dict[str, str], int]) -> str | None:
        label, args, params, depth = job
        result = _ffmpeg(
            [*_encode_args(enc, args, params, depth=depth, frames=2, small=True), "-f", "null", "-"]
        )
        if result.returncode:
            return f"{label}: {_fail_text(result)}"
        error = _param_error(result)
        return f"{label}: {error}" if error else None

    assert _parallel(_choice_jobs(enc), run) == []


def test_svtav1_options_parse(tmp_path: Path) -> None:
    """libsvtav1 only logs a bad parameter and encodes on: check its log, the
    ``SVT [config]`` lines and the stream (colour tags, HDR10 metadata)."""
    enc = VIDEO["libsvtav1"]
    values: dict[str, OptionValue] = {
        "film-grain": 8,
        "film-grain-denoise": False,
        "adaptive-film-grain": True,
        "keyint": 240,
        "scd": True,
        "lookahead": 60,
        "enable-overlays": True,
        "enable-tf": "2",
        "tf-strength": 1,
        "enable-qm": True,
        "qm-min": 2,
        "qm-max": 12,
        "enable-variance-boost": True,
        "variance-boost-strength": 3,
        "variance-octile": 6,
        "variance-boost-curve": "1",
        "sharpness": 2,
        "aq-mode": "2",
        "qp-scale-compress-strength": 2,
        "min-qp": 10,
        "max-qp": 55,
        "irefresh-type": "1",
        "hierarchical-levels": "4",
        "luminance-qp-bias": 20,
        "ac-bias": 1.5,
        "enable-dlf": "2",
        "enable-cdef": False,
        "enable-restoration": False,
        "color-primaries": "bt2020",
        "transfer-characteristics": "smpte2084",
        "matrix-coefficients": "bt2020-ncl",
        "color-range": "full",
        "chroma-sample-position": "topleft",
        "mastering-display": "G(0.265,0.69)B(0.15,0.06)R(0.68,0.32)WP(0.3127,0.329)L(1000,0.0001)",
        "content-light": "1000,400",
        "lp": 2,
        "tile-rows": 1,
        "tile-columns": 1,
    }
    assert set(values) == {o.key for o in enc.options}
    params = {
        o.mapping.name: _written(values[o.key])
        for o in enc.options
        if o.mapping.kind == "x26x_param"
    }
    out = tmp_path / "o.ivf"
    result = _ffmpeg([*_encode_args(enc, ["-preset", "10"], params, depth=10), str(out)])
    assert result.returncode == 0, _fail_text(result)
    assert _param_error(result) is None
    log = result.stderr
    assert re.search(
        r"gop size / mini-gop size / key-frame type\s*:\s*240 / 16 / FWD key frame", log
    )
    assert re.search(r"film grain synth / denoising / level .*: 1 / 0 / 8", log)
    assert re.search(r"AQ mode / Variance Boost strength / octile / curve\s*:\s*2 / 3 / 6 / 1", log)
    assert re.search(r"sharpness / luminance-based QP bias\s*:\s*2 / 20", log)
    assert re.search(r"QP scale compress strength\s*:\s*2", log)
    assert re.search(r"Level of Parallelism: 2", log)
    probed = _probe(out, "-show_streams", "-show_frames", "-read_intervals", "%+#1")
    stream = probed["streams"][0]
    assert (stream["color_primaries"], stream["color_transfer"], stream["color_space"]) == (
        "bt2020",
        "smpte2084",
        "bt2020nc",
    )
    assert (stream["color_range"], stream["chroma_location"]) == ("pc", "topleft")
    side = {d["side_data_type"]: d for d in probed["frames"][0].get("side_data_list", [])}
    assert side["Content light level metadata"]["max_content"] == 1000
    assert side["Content light level metadata"]["max_average"] == 400
    assert side["Mastering display metadata"]["max_luminance"] == "256000/256"


def test_svtav1_option_defaults_in_the_log() -> None:
    """The fixed defaults of the SVT-AV1 set are what v4.2 logs when nothing is set (AQ mode
    2, sharpness 0, luminance QP bias 0, QP scale compress strength 0; with variance boost on:
    strength 2, octile 5, curve 0); key frames are closed (irefresh-type 2); the mini-GOP is
    16 at preset 10."""
    enc = VIDEO["libsvtav1"]
    plain = _ffmpeg([*_encode_args(enc, ["-preset", "10"]), "-f", "null", "-"]).stderr
    assert re.search(r"AQ mode / Variance Boost\s*:\s*2 / 0", plain)
    assert re.search(r"sharpness / luminance-based QP bias\s*:\s*0 / 0", plain)
    assert re.search(r"QP scale compress strength\s*:\s*0", plain)
    assert re.search(r"key-frame type\s*:\s*\d+ / 16 / key frame", plain)
    boost = _ffmpeg(
        [*_encode_args(enc, ["-preset", "10"], {"enable-variance-boost": "1"}), "-f", "null", "-"]
    ).stderr
    assert re.search(r"strength / octile / curve\s*:\s*2 / 2 / 5 / 0", boost)
    defaults = {o.key: o.default for o in enc.options}
    assert defaults["aq-mode"].kind == "fixed"
    assert defaults["aq-mode"].value == "2"
    assert defaults["irefresh-type"].value == "2"  # type: ignore[union-attr]
    assert defaults["variance-octile"].value == 5  # type: ignore[union-attr]


#: Other options to set with an option at the end of its range, where x265 has a rule across
#: two options (recorded in ``test_recorded_cross_option_rules``; C-8 validates them).
_RANGE_ARGS: dict[str, list[str]] = {"libvpx-vp9": ["-b:v", "500k"]}
_RANGE_COMPANIONS: dict[tuple[str, str], dict[str, str]] = {
    ("libx265", "rc-lookahead"): {"bframes": "0"},
}


@pytest.mark.parametrize("encoder_id", ["libx264", "libx265", "libsvtav1", "libvpx-vp9"])
def test_option_range_ends_encode(encoder_id: str) -> None:
    """Every number option at its minimum and at its maximum reaches the library without an
    error. M2 review: x265 ``ref`` 9-16 and ``merange`` 32768 stopped the encoder, SVT-AV1
    ``lookahead=-1`` was rejected ("Error parsing option lookahead: -1.")."""
    enc = VIDEO[encoder_id]
    jobs: list[tuple[str, list[str], dict[str, str]]] = []
    for option in enc.options:
        if option.type not in ("int", "float"):
            continue
        assert option.min is not None
        assert option.max is not None
        for value in (option.min, option.max):
            args, params = _mapping_args(option.mapping, _written(value))
            params = _RANGE_COMPANIONS.get((encoder_id, option.key), {}) | params
            # libvpx without a rate control uses CRF 32, which must lie inside qmin..qmax.
            args = [*_RANGE_ARGS.get(encoder_id, []), *args]
            jobs.append((f"{option.key}={_written(value)}", args, params))

    def run(job: tuple[str, list[str], dict[str, str]]) -> str | None:
        label, args, params = job
        result = _ffmpeg(
            [*_encode_args(enc, args, params, frames=2, small=True), "-f", "null", "-"]
        )
        if result.returncode:
            return f"{label}: {_fail_text(result)}"
        error = _param_error(result)
        return f"{label}: {error}" if error else None

    assert _parallel(jobs, run) == []


def test_recorded_cross_option_rules(tmp_path: Path) -> None:
    """Rules across two options that a range cannot express (for C-8's validation):

    - x265: ``rc-lookahead`` at or below ``bframes`` stops the encoder ("Lookahead depth must
      be greater than the max consecutive bframe count"); ``ref`` 9 and more with B-frames
      stops it too ("NumPocTotalCurr (total references) is non-compliant"), so the range ends
      at 8.
    - x264: ``subme`` 10 and 11 need ``trellis=2``; with a lower trellis x264 writes
      ``subme=9`` without a message.
    """
    x265, x264 = VIDEO["libx265"], VIDEO["libx264"]

    def x265_run(params: dict[str, str]) -> subprocess.CompletedProcess[str]:
        return _ffmpeg([*_encode_args(x265, [], params, frames=2, small=True), "-f", "null", "-"])

    for bframes, lookahead, ok in (("4", "4", False), ("4", "5", True), ("0", "0", True)):
        result = x265_run({"bframes": bframes, "rc-lookahead": lookahead})
        assert (result.returncode == 0) is ok, (bframes, lookahead)
        if not ok:
            assert "Lookahead depth must be greater than" in result.stderr
    result = x265_run({"ref": "9"})
    assert result.returncode != 0
    assert "NumPocTotalCurr" in result.stderr
    assert x265_run({"ref": "9", "bframes": "0"}).returncode == 0
    assert x265_run({"ref": "8"}).returncode == 0
    for trellis, written in (("1", "9"), ("2", "10")):
        out = tmp_path / f"t{trellis}.h264"
        params = {"subme": "10", "trellis": trellis}
        result = _ffmpeg([*_encode_args(x264, [], params, frames=2, small=True), str(out)])
        assert result.returncode == 0, _fail_text(result)
        assert _sei_options(out)["subme"] == written
    svt = VIDEO["libsvtav1"]
    result = _ffmpeg(
        [*_encode_args(svt, ["-preset", "10"], {"lookahead": "-1"}, small=True), "-f", "null", "-"]
    )
    assert result.returncode == 0
    assert "Error parsing option lookahead: -1." in result.stderr
    result = _ffmpeg(
        [*_encode_args(svt, ["-preset", "10"], {"lookahead": "121"}, small=True), "-f", "null", "-"]
    )
    assert result.returncode != 0
    assert "The lookahead distance must be [0 - 120]" in result.stderr


@pytest.mark.parametrize("encoder_id", SOFTWARE)
def test_software_rate_control_encodes(encoder_id: str, tmp_path: Path) -> None:
    """Constant quality at min / default / max, average bitrate, and 2-pass with a turbo and
    a full first pass."""
    enc = VIDEO[encoder_id]
    q = enc.rate_control.quality
    b = enc.rate_control.bitrate
    assert q is not None
    assert b is not None
    runs: list[tuple[str, list[str], dict[str, str]]] = []
    for value in (q.min, q.default, q.max):
        text = _written(value)
        runs.append(
            (
                f"quality {text}",
                [a.replace("{value}", text) for a in q.args],
                {k: v.replace("{value}", text) for k, v in q.params.items()},
            )
        )
    runs.append(("bitrate", [a.replace("{kbps}", "500") for a in b.args], dict(b.params)))

    def run(job: tuple[str, list[str], dict[str, str]]) -> str | None:
        label, args, params = job
        result = _ffmpeg([*_encode_args(enc, args, params, frames=5), "-f", "null", "-"])
        if result.returncode:
            return f"{label}: {_fail_text(result)}"
        error = _param_error(result)
        return f"{label}: {error}" if error else None

    assert _parallel(runs, run) == []
    tp = b.two_pass
    assert tp is not None
    assert tp.mode == "two_runs"
    for turbo in (True, False):
        passlog = str(tmp_path / f"log{turbo}")
        out = tmp_path / f"two_pass_{turbo}.mkv"
        for number in ("1", "2"):

            def fill(text: str, number: str = number, passlog: str = passlog) -> str:
                return text.replace("{pass}", number).replace("{passlog}", passlog)

            args = [fill(a) for a in [*b.args, *tp.args]]
            params = {k: fill(v) for k, v in {**b.params, **tp.params}.items()}
            if number == "1":
                args += tp.turbo_args if turbo else tp.full_args
                params |= tp.turbo_params if turbo else tp.full_params
            args = [a.replace("{kbps}", "500") for a in args]
            target = ["-f", "null", "-"] if number == "1" else [str(out)]
            result = _ffmpeg([*_encode_args(enc, args, params, frames=10), *target])
            assert result.returncode == 0, f"pass {number}: {_fail_text(result)}"
            assert _param_error(result) is None
        assert out.stat().st_size > 0


def _quality_args(q: QualityMode, value: float | None) -> tuple[list[str], dict[str, str]]:
    """The quality mode's arguments for ``value``; ``None`` = the arguments without any
    placeholder pair (the mode with no quality value: what the encoder does when it is not
    set)."""
    if value is None:
        args: list[str] = []
        for flag, arg in zip(q.args[::2], q.args[1::2], strict=True):
            if "{" not in arg:
                args += [flag, arg]
        return args, {k: v for k, v in q.params.items() if "{" not in v}

    def fill(text: str) -> str:
        text = text.replace("{value}", _written(value))
        for name, derived in q.derived.items():
            text = text.replace("{" + name + "}", _written(derived.compute(value)))
        return text

    return [fill(a) for a in q.args], {k: fill(v) for k, v in q.params.items()}


def _quality_points(q: QualityMode) -> dict[str, float | None]:
    """Each end of the range, its neighbour one unit in, the default and "not set"."""
    unit = max(q.step, 1)
    return {
        "unset": None,
        "min": q.min,
        "min+1": q.min + unit,
        "default": q.default,
        "max-1": q.max - unit,
        "max": q.max,
    }


def _check_quality_points(results: dict[str, tuple[int, str]]) -> list[str]:
    """M2 review: an end of the range that the encoder ignores (SVT-AV1 ``-crf 0``, VAAPI
    ``-global_quality 0`` and AMF AV1 QP 0 = the default quality; VAAPI 52 = 51) gives the
    same file as another value."""
    size = {k: v[0] for k, v in results.items()}
    digest = {k: v[1] for k, v in results.items()}
    problems = [
        f"{a} gives the same file as {b}"
        for a, b in (("min", "unset"), ("min", "min+1"), ("max", "max-1"))
        if digest[a] == digest[b]
    ]
    if not size["min"] > size["default"] > size["max"]:
        problems.append(f"sizes do not fall with the quality value: {size}")
    return problems


def _encode_digest(args: Sequence[str], out: Path, timeout: float = 120) -> tuple[int, str] | str:
    """Encode to ``out`` (bit-exact Matroska): ``(size, md5)``, or the error text."""
    result = _ffmpeg([*args, "-fflags", "+bitexact", "-f", "matroska", str(out)], timeout)
    if result.returncode:
        return _fail_text(result)
    data = out.read_bytes()
    return len(data), hashlib.md5(data).hexdigest()


@pytest.mark.parametrize("encoder_id", SOFTWARE)
def test_quality_range_ends_are_honoured(encoder_id: str, tmp_path: Path) -> None:
    """Each end of the constant-quality range has its own effect: the best end is not "not
    set" and the worst end is not clamped to the one before it."""
    enc = VIDEO[encoder_id]
    q = enc.rate_control.quality
    assert q is not None
    points = _quality_points(q)
    results: dict[str, tuple[int, str]] = {}

    def run(label: str) -> str | None:
        args, params = _quality_args(q, points[label])
        got = _encode_digest(_encode_args(enc, args, params, frames=5), tmp_path / f"{label}.mkv")
        if isinstance(got, str):
            return f"{label}: {got}"
        results[label] = got
        return None

    assert _parallel(points, run) == []
    assert _check_quality_points(results) == []


@pytest.mark.parametrize("encoder_id", sorted(e for e, d in VIDEO.items() if d.family == "nvenc"))
def test_nvenc_initial_qps_span_the_build_range(encoder_id: str) -> None:
    """The initial QPs derived from the CQ value use the scale of ``-init_qp*``: the worst CQ
    gives the worst initial QP. M2 review: av1_nvenc's ``-cq`` is 0-63 but ``-init_qp*`` is
    0-255, and the QPs were written on the 0-63 scale (no NVIDIA hardware here: the ranges of
    ``ffmpeg -h`` only)."""
    _need_encoder(encoder_id)
    q = VIDEO[encoder_id].rate_control.quality
    assert q is not None
    assert _help_range(encoder_id, "cq")[1] == q.max
    for name, option in (("qp_i", "init_qpI"), ("qp_p", "init_qpP"), ("qp_b", "init_qpB")):
        low, high = _help_range(encoder_id, option)
        derived = q.derived[name]
        assert low <= derived.compute(q.min)
        assert derived.compute(q.max) <= high
        assert derived.compute(q.max) >= 0.9 * high, (name, derived.compute(q.max))


# =========================================================================== audio


_MIXDOWN_LAYOUT = {"mono": "mono", "stereo": "stereo", "dpl2": "stereo", "5.1": "5.1", "7.1": "7.1"}


def _audio_encode(
    encoder: str, layout: str, args: Sequence[str], rate: int = 48000
) -> subprocess.CompletedProcess[str]:
    """Encode noise; ``-ar`` forces the output rate (without it FFmpeg would negotiate a rate
    the encoder supports)."""
    return _ffmpeg(
        [
            "-f",
            "lavfi",
            "-i",
            f"anoisesrc=sample_rate={rate}:duration=0.3:amplitude=0.3,"
            f"aformat=channel_layouts={layout}",
            "-c:a",
            encoder,
            "-ar",
            str(rate),
            *args,
            "-f",
            "null",
            "-",
        ]
    )


@pytest.mark.parametrize("encoder_id", sorted(DEFS.audio_encoders))
def test_audio_bitrates_and_sample_rates_encode(encoder_id: str) -> None:
    """Every mixdown at its minimum, default and maximum (and every allowed value for the
    fixed-step encoders), every sample rate, and the VBR quality ends."""
    _need_encoder(encoder_id)
    enc = DEFS.audio_encoders[encoder_id]
    jobs: list[tuple[str, str, list[str], int]] = []
    for mixdown in enc.mixdowns:
        layout = _MIXDOWN_LAYOUT[mixdown]
        if enc.bitrate is None:
            jobs.append((mixdown, layout, [], 48000))
            continue
        limits = enc.bitrate.by_mixdown[mixdown]
        values = enc.bitrate.values(mixdown) or [limits.min, limits.default, limits.max]
        jobs += [(f"{mixdown} {v}k", layout, ["-b:a", f"{v}k"], 48000) for v in values]
    jobs += [(f"{rate} Hz", "stereo", [], rate) for rate in enc.samplerates]
    if enc.quality is not None:
        q = enc.quality
        jobs += [
            (f"quality {v}", "stereo", [q.arg, _written(v)], 48000)
            for v in (q.min, q.default, q.max)
        ]

    def run(job: tuple[str, str, list[str], int]) -> str | None:
        label, layout, args, rate = job
        result = _audio_encode(encoder_id, layout, args, rate)
        return f"{label}: {_fail_text(result)}" if result.returncode else None

    assert _parallel(jobs, run) == []


def test_recorded_audio_encoder_behaviour(tmp_path: Path) -> None:
    """testdata/README.md: AC-3 snaps silently, Opus and AC-3 reject unlisted rates, 7.1 is
    negotiated down for AC-3."""
    out = tmp_path / "a.ac3"
    ffmpeg_args = [
        "-f",
        "lavfi",
        "-i",
        "sine=duration=0.3",
        "-c:a",
        "ac3",
        "-b:a",
        "150k",
        str(out),
    ]
    assert _ffmpeg(ffmpeg_args).returncode == 0
    assert _probe(out, "-show_streams")["streams"][0]["bit_rate"] == "160000"
    assert _audio_encode("libopus", "stereo", [], 44100).returncode != 0
    assert _audio_encode("ac3", "stereo", [], 96000).returncode != 0
    assert _audio_encode("libopus", "stereo", ["-b:a", "600k"]).returncode != 0
    out71 = tmp_path / "b.ac3"
    assert (
        _ffmpeg(
            [
                "-f",
                "lavfi",
                "-i",
                "sine=duration=0.3,aformat=channel_layouts=7.1",
                "-c:a",
                "ac3",
                str(out71),
            ]
        ).returncode
        == 0
    )
    assert _probe(out71, "-show_streams")["streams"][0]["channels"] == 6


# =========================================================================== containers


_VIDEO_SOURCES: dict[str, list[str]] = {
    "h264": ["-c:v", "libx264"],
    "hevc": ["-c:v", "libx265"],
    "av1": ["-c:v", "libsvtav1"],
    "vp9": ["-c:v", "libvpx-vp9", "-deadline", "realtime"],
    "vp8": ["-c:v", "libvpx"],
    "mpeg1video": ["-c:v", "mpeg1video"],
    "mpeg2video": ["-c:v", "mpeg2video"],
    "mpeg4": ["-c:v", "mpeg4"],
    "mjpeg": ["-c:v", "mjpeg"],
}
_AUDIO_SOURCES: dict[str, list[str]] = {
    "aac": ["-c:a", "aac"],
    "ac3": ["-c:a", "ac3"],
    "eac3": ["-c:a", "eac3"],
    "opus": ["-c:a", "libopus"],
    "flac": ["-c:a", "flac"],
    "mp3": ["-c:a", "libmp3lame"],
    "truehd": ["-c:a", "truehd", "-strict", "-2"],
    "dts": ["-c:a", "dca", "-strict", "-2"],
    "alac": ["-c:a", "alac"],
    "vorbis": ["-c:a", "libvorbis"],
    "pcm_s16le": ["-c:a", "pcm_s16le"],
    "pcm_s24le": ["-c:a", "pcm_s24le"],
    "pcm_s32le": ["-c:a", "pcm_s32le"],
}


@pytest.fixture(scope="module")
def stream_sources(
    tmp_path_factory: pytest.TempPathFactory, fixture_media_module: Callable[[str], Path]
) -> dict[str, Path]:
    """One short Matroska file per codec (``-c copy`` sources)."""
    folder = tmp_path_factory.mktemp("sources")
    jobs = [
        (n, ["-f", "lavfi", "-i", "testsrc2=size=160x120:rate=25:duration=0.4", *a])
        for n, a in _VIDEO_SOURCES.items()
    ]
    jobs += [
        (n, ["-f", "lavfi", "-i", "sine=duration=0.4:sample_rate=48000", *a])
        for n, a in _AUDIO_SOURCES.items()
    ]
    srt = fixture_media_module("text-subs").with_name("text-subs.en.srt")
    ass = srt.with_name("text-subs.en.ass")
    jobs += [
        ("subrip", ["-i", str(srt), "-c:s", "srt"]),
        ("ass", ["-i", str(ass), "-c:s", "ass"]),
        ("webvtt", ["-i", str(srt), "-c:s", "webvtt"]),
    ]
    vobsub = fixture_media_module("vobsub")
    jobs.append(("dvd_subtitle", ["-i", str(vobsub), "-map", "0:s:0", "-c:s", "copy"]))
    jobs.append(("dvb_subtitle", ["-i", str(vobsub), "-map", "0:s:0", "-c:s", "dvbsub"]))
    sources: dict[str, Path] = {}

    def make(job: tuple[str, list[str]]) -> str | None:
        name, args = job
        out = folder / f"{name}.mkv"
        result = _ffmpeg([*args, str(out)])
        if result.returncode:
            return f"{name}: {_fail_text(result)}"
        sources[name] = out
        return None

    assert _parallel(jobs, make) == []
    mov_text = folder / "mov_text.mp4"
    assert _ffmpeg(["-i", str(srt), "-c:s", "mov_text", str(mov_text)]).returncode == 0
    sources["mov_text"] = mov_text
    return sources


@pytest.fixture(scope="module")
def fixture_media_module() -> Callable[[str], Path]:
    from reframe_testing.pytest_plugin import fixture_media_path

    return fixture_media_path


def _container(name: str) -> ContainerDef:
    return DEFS.containers[cast(Container, name)]


def _copy_into(
    source: Path, container: str, out: Path, extra: Sequence[str] = ()
) -> subprocess.CompletedProcess[str]:
    return _ffmpeg(
        [
            "-i",
            str(source),
            "-map",
            "0",
            "-c",
            "copy",
            *extra,
            "-f",
            _container(container).muxer,
            str(out),
        ]
    )


@pytest.mark.parametrize("container", ["mkv", "mp4", "webm"])
def test_listed_codecs_can_be_copied_in(
    container: str, stream_sources: dict[str, Path], tmp_path: Path
) -> None:
    cont = _container(container)
    jobs: list[tuple[str, list[str]]] = []
    kinds: tuple[tuple[CodecSupport, list[str]], ...] = (
        (cont.video, list(_VIDEO_SOURCES)),
        (cont.audio, list(_AUDIO_SOURCES)),
        (cont.subtitles, []),
    )
    for support, all_of_kind in kinds:
        names = all_of_kind if "*" in support.copy_codecs else support.copy_codecs
        for name in names:
            if name not in stream_sources:
                continue  # hdmv_pgs_subtitle: FFmpeg has no PGS encoder to make a source
            jobs.append((name, support.copy_args.get(name, [])))

    def run(job: tuple[str, list[str]]) -> str | None:
        name, extra = job
        out = tmp_path / f"{name}{cont.extensions[0]}"
        result = _copy_into(stream_sources[name], container, out, extra)
        if result.returncode:
            return f"{name}: {_fail_text(result)}"
        got = _probe(out, "-show_streams")["streams"][0]["codec_name"]
        return None if got == name else f"{name}: read back as {got}"

    assert _parallel(jobs, run) == []


@pytest.mark.parametrize(
    ("container", "codec"),
    [
        ("mp4", "subrip"),
        ("mp4", "ass"),
        ("mp4", "webvtt"),
        ("mp4", "vp8"),
        ("webm", "h264"),
        ("webm", "hevc"),
        ("webm", "aac"),
        ("webm", "ac3"),
        ("webm", "flac"),
        ("webm", "subrip"),
        ("webm", "dvd_subtitle"),
        ("mkv", "mov_text"),
    ],
)
def test_unlisted_codecs_are_rejected(
    container: str, codec: str, stream_sources: dict[str, Path], tmp_path: Path
) -> None:
    cont = _container(container)
    assert not any(
        s.can_copy(codec)
        for s in (cont.video, cont.audio, cont.subtitles)
        if "*" not in s.copy_codecs
    )
    result = _copy_into(stream_sources[codec], container, tmp_path / f"x{cont.extensions[0]}")
    assert result.returncode != 0


def test_truehd_in_mp4_needs_strict(stream_sources: dict[str, Path], tmp_path: Path) -> None:
    result = _copy_into(stream_sources["truehd"], "mp4", tmp_path / "t.mp4")
    assert result.returncode != 0
    assert "-strict -2" in result.stderr


#: Streams for the Matroska ``copy_except`` check: codec → (encoder, source muxer, input).
#: ``direct``: no muxer could hold the codec as a readable source, so it is encoded straight
#: into Matroska (the muxer sees the same codec as with ``-c copy``). Audio input is
#: ``rate/layout``; video input is a pixel format.
_MKV_SOURCES: dict[str, tuple[str, str, str]] = {
    # refused: "No wav codec tag found for codec …"
    "pcm_bluray": ("pcm_bluray", "direct", "48000/stereo"),
    "pcm_dvd": ("pcm_dvd", "vob", "48000/stereo"),
    "s302m": ("s302m", "mpegts", "48000/stereo"),
    "pcm_s24daud": ("pcm_s24daud", "direct", "48000/stereo"),
    "pcm_vidc": ("pcm_vidc", "direct", "48000/stereo"),
    **{
        c: (c, "nut", "48000/stereo")
        for c in (
            "pcm_s8",
            "pcm_s8_planar",
            "pcm_s16le_planar",
            "pcm_s16be_planar",
            "pcm_s24le_planar",
            "pcm_s32le_planar",
            "pcm_s64be",
            "pcm_u16le",
            "pcm_u16be",
            "pcm_u24le",
            "pcm_u24be",
            "pcm_u32le",
            "pcm_u32be",
            "pcm_f32be",
            "pcm_f64be",
        )
    },
    **{
        c: (c, "direct", "48000/stereo")
        for c in (
            "adpcm_adx",
            "adpcm_argo",
            "adpcm_ima_alp",
            "adpcm_ima_amv",
            "adpcm_ima_apm",
            "adpcm_ima_ssi",
            "adpcm_ima_ws",
            "aptx",
            "aptx_hd",
            "sbc",
        )
    },
    "roq_dpcm": ("roq_dpcm", "direct", "22050/stereo"),
    "adpcm_g726le": ("g726le", "direct", "8000/mono"),
    "adpcm_ima_qt": ("adpcm_ima_qt", "mov", "48000/stereo"),
    "gsm": ("libgsm", "mov", "8000/mono"),
    "nellymoser": ("nellymoser", "mov", "44100/mono"),
    "comfortnoise": ("comfortnoise", "nut", "8000/mono"),
    # muxed with exit 0, but FFmpeg cannot read the file back
    "dfpwm": ("dfpwm", "wav", "48000/stereo"),
    "dirac": ("vc2", "nut", "yuv420p"),
    "gif": ("gif", "nut", "rgb8"),
    "qtrle": ("qtrle", "mov", "rgb24"),
    "rpza": ("rpza", "nut", "rgb555le"),
    "svq1": ("svq1", "nut", "yuv410p"),
    # refused: "Raw RGB is not supported Natively in Matroska"
    "rawvideo": ("rawvideo", "nut", "rgb24"),
    # copied and read back
    **{
        c: (c, "nut", "48000/stereo")
        for c in (
            "pcm_s16le",
            "pcm_s16be",
            "pcm_s24le",
            "pcm_s24be",
            "pcm_s32le",
            "pcm_s32be",
            "pcm_s64le",
            "pcm_u8",
            "pcm_f32le",
            "pcm_f64le",
            "pcm_alaw",
            "pcm_mulaw",
            "adpcm_ima_wav",
            "mp2",
            "wavpack",
        )
    },
    "adpcm_ms": ("adpcm_ms", "wav", "48000/stereo"),
    "adpcm_g722": ("g722", "nut", "16000/mono"),
    "alac": ("alac", "matroska", "48000/stereo"),
    "tta": ("tta", "matroska", "48000/stereo"),
    "ffv1": ("ffv1", "nut", "yuv420p"),
    "prores": ("prores", "nut", "yuv422p10le"),
    "png": ("png", "nut", "rgb24"),
}
#: Denied without a stream: FFmpeg has no encoder for them, and no hand-made source worked.
_MKV_NOT_VERIFIED = frozenset(
    {"pcm_f16le", "pcm_f24le", "pcm_lxf", "pcm_sga", "dsd_lsbf", "dsd_msbf"}
)
_MKV_UNREADABLE = frozenset({"dfpwm", "dirac", "gif", "qtrle", "rpza", "svq1"})
#: Unreadable only from this FFmpeg ``(major, minor)`` on: n8.1.3 copies svq1 into Matroska
#: and reads it back; both n9.0.2 builds cannot read the file. It stays denied (the bundled
#: build is n9).
_MKV_UNREADABLE_SINCE: dict[str, tuple[int, int]] = {"svq1": (9, 0)}


def _dsf(path: Path, lsb_first: bool) -> Path:
    """A minimal DSF file (two channels of DSD silence): FFmpeg reads it as
    ``dsd_lsbf_planar`` (1 bit per sample) or ``dsd_msbf_planar`` (8)."""
    channels, block, blocks = 2, 4096, 4
    data = bytes([0x69]) * (block * channels * blocks)
    bits = 1 if lsb_first else 8
    fmt = b"fmt " + struct.pack(
        "<QIIIIIIQII", 52, 1, 0, 2, channels, 2_822_400, bits, block * blocks * 8, block, 0
    )
    chunk = b"data" + struct.pack("<Q", 12 + len(data)) + data
    head = b"DSD " + struct.pack("<QQQ", 28, 28 + len(fmt) + len(chunk), 0)
    path.write_bytes(head + fmt + chunk)
    return path


def _codec_back(path: Path) -> str | None:
    """The first stream's codec as ffprobe reads it back (``None``: unreadable)."""
    _, ffprobe = _tools()
    out = subprocess.run(
        [ffprobe, "-v", "error", "-of", "json", "-show_streams", str(path)],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    try:
        streams = json.loads(out.stdout).get("streams", [])
    except json.JSONDecodeError:
        return None
    codec = streams[0].get("codec_name") if streams else None
    return codec if isinstance(codec, str) else None


def test_mkv_copy_except_matches_the_muxer(tmp_path: Path) -> None:
    """M2 review: Matroska took every audio codec (``copy = ["*"]``), so pcm_bluray was
    planned as a copy that FFmpeg refused ("No wav codec tag found for codec pcm_bluray",
    exit 234). Every denied codec really fails (or writes a file FFmpeg cannot read back), and
    the PCM variants that are not denied copy and read back."""
    mkv = _container("mkv")
    denied = set(mkv.audio.copy_except) | set(mkv.video.copy_except)
    assert denied <= set(_MKV_SOURCES) | _MKV_NOT_VERIFIED | {"dsd_lsbf_planar", "dsd_msbf_planar"}
    in_build = _encoders_in_build()

    def run(codec: str) -> str | None:
        encoder, muxer, spec = _MKV_SOURCES[codec]
        if encoder not in in_build:
            return None  # libgsm is in the Arch build only
        if "/" in spec:
            rate, layout = spec.split("/")
            source = f"sine=sample_rate={rate}:duration=0.4,aformat=channel_layouts={layout}"
            make = ["-f", "lavfi", "-i", source, "-c:a", encoder]
        else:
            source = "testsrc2=size=176x144:rate=25"
            make = ["-f", "lavfi", "-i", source, "-frames:v", "2", "-pix_fmt", spec]
            make += ["-c:v", encoder]
        make += ["-strict", "-2"]
        allowed = (mkv.audio if "/" in spec else mkv.video).can_copy(codec)
        out = tmp_path / f"{codec}.out.mkv"
        if muxer == "direct":
            result = _ffmpeg([*make, "-f", "matroska", str(out)])
            refused = result.returncode != 0 and "No wav codec tag found" in result.stderr
            return None if refused and not allowed else f"{codec}: {_fail_text(result)}"
        src = tmp_path / f"{codec}.src"
        result = _ffmpeg([*make, "-f", muxer, str(src)])
        if result.returncode or _codec_back(src) != codec:
            return f"{codec}: no source ({_fail_text(result)}, read as {_codec_back(src)})"
        result = _copy_into(src, "mkv", out, ["-strict", "-2"])
        back = _codec_back(out) if result.returncode == 0 else None
        if allowed:
            return None if back == codec else f"{codec}: allowed, but {_fail_text(result)}"
        if codec in _MKV_UNREADABLE and _series() < _MKV_UNREADABLE_SINCE.get(codec, (0, 0)):
            ok = result.returncode == 0 and back == codec
        elif codec in _MKV_UNREADABLE:
            ok = result.returncode == 0 and back is None
        else:
            ok = result.returncode != 0 and (
                "No wav codec tag found" in result.stderr
                or "Raw RGB is not supported" in result.stderr
            )
        return None if ok else f"{codec}: denied, but rc {result.returncode}, read as {back}"

    problems = _parallel(sorted(_MKV_SOURCES), run)
    for lsb_first, codec in ((True, "dsd_lsbf_planar"), (False, "dsd_msbf_planar")):
        source = _dsf(tmp_path / f"{codec}.dsf", lsb_first)
        assert _codec_back(source) == codec
        assert not mkv.audio.can_copy(codec)
        result = _copy_into(source, "mkv", tmp_path / f"{codec}.mkv")
        if result.returncode == 0 or "No wav codec tag found" not in result.stderr:
            problems.append(f"{codec}: denied, but rc {result.returncode}")
    assert problems == []


@pytest.mark.parametrize("container", ["mkv", "mp4", "webm"])
def test_subtitle_encode_targets(
    container: str, fixture_media: Callable[[str], Path], tmp_path: Path
) -> None:
    cont = _container(container)
    srt = fixture_media("text-subs").with_name("text-subs.en.srt")
    for target in ("srt", "ass", "webvtt", "mov_text"):
        out = tmp_path / f"{target}{cont.extensions[0]}"
        result = _ffmpeg(["-i", str(srt), "-c:s", target, "-f", cont.muxer, str(out)])
        assert (result.returncode == 0) == (target in cont.subtitles.encode), (
            target,
            _fail_text(result),
        )


@pytest.mark.parametrize("container", ["mkv", "mp4", "webm"])
def test_flags_the_muxer_writes(container: str, tmp_path: Path) -> None:
    cont = _container(container)
    codec = {"mkv": "aac", "mp4": "aac", "webm": "libopus"}[container]
    for flag in TRACK_FLAGS:
        disposition = DEFS.track_flags[flag].disposition
        out = tmp_path / f"{flag}{cont.extensions[0]}"
        result = _ffmpeg(
            [
                "-f",
                "lavfi",
                "-i",
                "sine=duration=0.2",
                "-f",
                "lavfi",
                "-i",
                "sine=duration=0.2",
                "-map",
                "0",
                "-map",
                "1",
                "-c:a",
                codec,
                "-disposition:a:0",
                disposition,
                "-disposition:a:1",
                "0",
                str(out),
            ]
        )
        assert result.returncode == 0, _fail_text(result)
        got = _probe(out, "-show_streams")["streams"][0]["disposition"][disposition]
        assert bool(got) == (flag in cont.flags), flag


@pytest.mark.parametrize("container", ["mkv", "mp4", "webm"])
def test_default_flag_without_a_default_track(container: str, tmp_path: Path) -> None:
    cont = _container(container)
    codec = {"mkv": "aac", "mp4": "aac", "webm": "libopus"}[container]
    out = tmp_path / f"d{cont.extensions[0]}"
    result = _ffmpeg(
        [
            "-f",
            "lavfi",
            "-i",
            "sine=duration=0.2",
            "-f",
            "lavfi",
            "-i",
            "sine=duration=0.2",
            "-map",
            "0",
            "-map",
            "1",
            "-c:a",
            codec,
            "-disposition:a:0",
            "0",
            "-disposition:a:1",
            "0",
            str(out),
        ]
    )
    assert result.returncode == 0
    first = _probe(out, "-show_streams")["streams"][0]["disposition"]["default"]
    assert bool(first) == cont.default_always_set


@pytest.mark.parametrize("container", ["mkv", "mp4", "webm"])
def test_chapters_and_attachments(
    container: str, fixture_media: Callable[[str], Path], tmp_path: Path
) -> None:
    cont = _container(container)
    video = (
        ["-c:v", "libvpx-vp9", "-deadline", "realtime"]
        if container == "webm"
        else ["-c:v", "libx264"]
    )
    out = tmp_path / f"c{cont.extensions[0]}"
    result = _ffmpeg(
        ["-i", str(fixture_media("chapters")), "-map", "0:v", *video, "-frames:v", "5", str(out)]
    )
    assert result.returncode == 0, _fail_text(result)
    assert (len(_probe(out, "-show_chapters")["chapters"]) == 4) == cont.chapters
    out = tmp_path / f"a{cont.extensions[0]}"
    result = _ffmpeg(
        [
            "-i",
            str(fixture_media("text-subs")),
            "-map",
            "0:v",
            "-map",
            "0:t",
            *video,
            "-frames:v",
            "5",
            str(out),
        ]
    )
    attachments = 0
    if result.returncode == 0:
        streams = _probe(out, "-show_streams")["streams"]
        attachments = sum(1 for s in streams if s["codec_type"] == "attachment")
    assert (attachments == 1) == cont.attachments  # WebM drops it silently, MP4 fails


def test_mp4_codec_tags_and_format_flags(tmp_path: Path) -> None:
    mp4 = DEFS.containers["mp4"]
    out = tmp_path / "h.mp4"
    args = ["-tag:v", mp4.codec_tags["hevc"], *mp4.format_flags["web_optimized"]]
    result = _ffmpeg([*_LAVFI_VIDEO, "-frames:v", "3", "-c:v", "libx265", *args, str(out)])
    assert result.returncode == 0, _fail_text(result)
    assert _probe(out, "-show_streams")["streams"][0]["codec_tag_string"] == "hvc1"
    data = out.read_bytes()
    assert data.index(b"moov") < data.index(b"mdat")  # +faststart moved the index forward


# =========================================================================== filters

_CUSTOM: dict[str, str] = {
    "detelecine": "order=auto",
    "interlace_detection": "intl_thres=1.2",
    "deinterlace": "mode=send_frame",
    "denoise": "s=2",
    "deblock": "filter=weak",
    "custom": "hflip",
    "colorspace": "p=bt709:t=bt709:m=bt709",
    "sharpen": "la=0.5",
    "chroma_smooth": "ca=-1",
}
_CUSTOM_BY_IMPL = {
    "hqdn3d": "luma_spatial=3",
    "yadif": "mode=send_field",
    "cas": "strength=0.4",
    "libplacebo": "colorspace=bt709",
}
_COLOUR_FILTERS = frozenset({"tonemap", "colorspace"})


@cache
def _filters_in_build() -> frozenset[str]:
    names = set()
    for line in _ffmpeg(["-filters"]).stdout.splitlines():
        parts = line.split()
        if len(parts) >= 3 and re.fullmatch(r"[T.][S.][C.]", parts[0]):
            names.add(parts[1])
    return frozenset(names)


def _filter_jobs() -> list[tuple[str, str, str]]:
    """(label, "filter/implementation", chain) for every preset and tune chain."""
    jobs: list[tuple[str, str, str]] = []
    for filter_id, f in DEFS.filters.items():
        for impl in f.implementations:
            key = f"{filter_id}/{impl.id}"
            for preset in impl.presets:
                chains = [(preset.id, preset.chain)] if preset.chain is not None else []
                chains += [(f"{preset.id}+{tune}", c) for tune, c in preset.tune_chains.items()]
                for label, chain in chains:
                    custom = _CUSTOM_BY_IMPL.get(impl.id, _CUSTOM.get(filter_id, ""))
                    text = chain.replace("{custom}", custom)
                    if impl.combed_only:
                        combed = f"idet,{text}:{impl.combed_only}"
                        jobs.append((f"{key} {label} combed only", key, combed))
                    jobs.append((f"{key} {label}", key, text))
    return jobs


def test_every_filter_chain_runs(fixture_media: Callable[[str], Path]) -> None:
    hdr = fixture_media("hdr10")
    available = _filters_in_build()
    impls = {f"{f.id}/{i.id}": i for f in DEFS.filters.values() for i in f.implementations}

    def run(job: tuple[str, str, str]) -> str | None:
        label, impl_id, chain = job
        if not set(impls[impl_id].filters) <= available:
            return None
        colour = impl_id.split("/")[0] in _COLOUR_FILTERS
        source = (
            ["-i", str(hdr)] if colour else ["-f", "lavfi", "-i", "testsrc2=size=320x240:rate=25"]
        )
        tail = ",format=yuv420p" if colour else ""
        result = _ffmpeg([*source, "-vf", chain + tail, "-frames:v", "2", "-f", "null", "-"])
        if result.returncode == 0:
            return None
        if impls[impl_id].needs_vulkan and "Generic error in an external library" in result.stderr:
            return None  # no Vulkan driver on this machine: libplacebo cannot run here
        return f"{label}: {chain}: {_fail_text(result)}"

    assert _parallel(_filter_jobs(), run) == []


def test_zscale_needs_tagged_input() -> None:
    """Why ``requires_tagged_input``: zscale fails on an untagged source."""
    chain = "zscale=p=bt709:t=bt709:m=bt709,format=yuv420p"
    untagged = _ffmpeg([*_LAVFI_VIDEO, "-vf", chain, "-frames:v", "2", "-f", "null", "-"])
    tagged = _ffmpeg(
        [
            *_LAVFI_VIDEO,
            "-vf",
            "setparams=color_primaries=bt470bg:color_trc=smpte170m:colorspace=bt470bg," + chain,
            "-frames:v",
            "2",
            "-f",
            "null",
            "-",
        ]
    )
    assert untagged.returncode != 0
    assert tagged.returncode == 0


def test_idet_flags_interlaced_frames(fixture_media: Callable[[str], Path]) -> None:
    """Interlace detection works because idet sets the frames' interlaced flag, which
    bwdif / yadif ``deint=interlaced`` reads. setfield=prog clears the source flag first."""
    src = fixture_media("interlaced")
    result = _ffmpeg(
        ["-i", str(src), "-vf", "setfield=prog,idet,showinfo", "-frames:v", "12", "-f", "null", "-"]
    )
    assert result.returncode == 0
    flags = re.findall(r" i:(\S)", result.stderr)
    assert flags, result.stderr
    assert flags[-1] in ("T", "B"), flags


@pytest.mark.parametrize("encoder_id", ["libx264", "libx265", "libsvtav1"])
def test_a_bad_params_entry_does_not_fail_the_encode(encoder_id: str) -> None:
    """Recorded for C-8's custom-parameter dry run: the exit code is 0, only the log says it
    ("Error parsing option 'bogus = 1'." / "Unknown option: bogus." / "Error parsing option
    bogus: 1.")."""
    enc = VIDEO[encoder_id]
    result = _ffmpeg([*_encode_args(enc, [], {"bogus": "1"}, small=True), "-f", "null", "-"])
    assert result.returncode == 0
    assert _param_error(result) is not None


# =========================================================================== hardware


_HW_SETUP = {
    "vaapi": ["-init_hw_device", "vaapi=va:/dev/dri/renderD128", "-filter_hw_device", "va"],
}


def _hw_args(enc: VideoEncoderDef, depth: int) -> list[str]:
    pix = enc.pix_fmts[str(depth)]  # type: ignore[index]
    if enc.family == "vaapi":
        return [
            *_HW_SETUP["vaapi"],
            *_LAVFI_VIDEO,
            "-frames:v",
            "5",
            "-vf",
            f"format={pix},hwupload",
            "-c:v",
            enc.id,
        ]
    return [*_LAVFI_VIDEO, "-frames:v", "5", "-pix_fmt", pix, "-c:v", enc.id]


def _hw_usable(enc: VideoEncoderDef) -> bool:
    if enc.id not in _encoders_in_build():
        return False
    return _ffmpeg([*_hw_args(enc, 8), "-f", "null", "-"], timeout=30).returncode == 0


def _option_test_value(option: EncoderOption) -> str:
    if option.type == "bool":
        return "1"
    if option.type == "enum":
        return (option.choices or [])[-1].value
    assert option.min is not None
    assert option.max is not None
    return _written(min(option.max, max(option.min, 2)))


@pytest.mark.needs_gpu
@pytest.mark.parametrize(
    "encoder_id", sorted(e for e, d in VIDEO.items() if d.family in ("amf", "vaapi"))
)
def test_hardware_choices_rate_control_and_options_encode(encoder_id: str) -> None:
    """AMF and VAAPI on a real GPU (AMD RX 7600 when recorded): every preset, profile and
    level, constant quality at min / default / max, average bitrate, and every option.

    Choices an older build lacks (``_ADDED_IN``: n8.1.3 has no ``high_quality`` for
    ``h264_amf`` / ``hevc_amf``, so ``supported_presets`` does not offer it there) must fail
    on that build and work on the newer ones: the test asserts what each version does."""
    enc = VIDEO[encoder_id]
    if not _hw_usable(enc):
        pytest.skip(f"{encoder_id} does not work on this machine")
    series = _series()
    missing = {
        f"{name}={value}"
        for (e, name, value), since in _ADDED_IN.items()
        if e == encoder_id and series < since
    }
    jobs: list[tuple[str, list[str], int]] = []
    absent: list[tuple[str, list[str], int]] = []
    for label, args, _params, depth in _choice_jobs(enc):
        if enc.family == "amf" and enc.codec == "h264" and depth == 10:
            continue
        (absent if label.split("@", 1)[0] in missing else jobs).append((label, args, depth))
    assert len({label.split("@", 1)[0] for label, _a, _d in absent}) == len(missing)
    q, b = enc.rate_control.quality, enc.rate_control.bitrate
    assert q is not None
    assert b is not None
    for value in (q.min, q.default, q.max):
        args = []
        for arg in q.args:
            text = arg.replace("{value}", _written(value))
            for name, derived in q.derived.items():
                text = text.replace("{" + name + "}", _written(derived.compute(value)))
            args.append(text)
        jobs.append((f"quality {value}", args, 8))
    jobs.append(("bitrate", [a.replace("{kbps}", "2000") for a in b.args], 8))
    for option in enc.options:
        args, _ = _mapping_args(option.mapping, _option_test_value(option))
        jobs.append((f"option {option.key}", args, 8))

    def run(job: tuple[str, list[str], int]) -> str | None:
        label, args, depth = job
        result = _ffmpeg([*_hw_args(enc, depth), *args, "-f", "null", "-"], timeout=60)
        return f"{label}: {_fail_text(result)}" if result.returncode else None

    problems: list[str] = []
    for job in jobs:  # one at a time: the GPU sessions are limited
        problem = run(job)
        if problem:
            problems.append(problem)
    for job in absent:  # the older build refuses the value
        if run(job) is None:
            problems.append(f"{job[0]}: works on {series}, expected to fail")
    assert problems == []


@pytest.mark.needs_gpu
@pytest.mark.parametrize(
    "encoder_id", sorted(e for e, d in VIDEO.items() if d.family in ("amf", "vaapi"))
)
def test_hardware_quality_range_ends_are_honoured(encoder_id: str, tmp_path: Path) -> None:
    """As ``test_quality_range_ends_are_honoured``, on the GPU (AMD RX 7600 when recorded).
    M2 review: VAAPI ``-global_quality 0`` gave the driver's QP (h264 20, hevc 25), 52 the
    same file as 51; AMF AV1 QP 0 logged ``AMF_OUT_OF_RANGE`` and gave the default."""
    enc = VIDEO[encoder_id]
    if not _hw_usable(enc):
        pytest.skip(f"{encoder_id} does not work on this machine")
    q = enc.rate_control.quality
    assert q is not None
    results: dict[str, tuple[int, str]] = {}
    for label, value in _quality_points(q).items():  # one at a time: GPU sessions are limited
        args, _ = _quality_args(q, value)
        got = _encode_digest([*_hw_args(enc, 8), *args], tmp_path / f"{label}.mkv", timeout=60)
        assert not isinstance(got, str), f"{label}: {got}"
        results[label] = got
    assert _check_quality_points(results) == []


@pytest.mark.needs_gpu
def test_av1_amf_pads_the_picture(tmp_path: Path) -> None:
    """Recorded for C-7 / C-8: av1_amf on the RX 7600 (VCN 4) writes 1920x1080 as 1920x1082
    and 720x480 as 768x480 (the width up to a multiple of 64; a height that is not a multiple
    of 16 gets 2 more lines); the extra lines repeat the picture's edge. av1_vaapi on the same
    GPU keeps 1920x1080; hevc_amf keeps the display size and pads only the coded size."""
    enc = VIDEO["av1_amf"]
    if not _hw_usable(enc):
        pytest.skip("av1_amf does not work on this machine")
    sizes: dict[str, tuple[int, int]] = {}
    for size in ("1920x1080", "720x480", "1280x720", "640x360"):
        out = tmp_path / f"{size}.mkv"
        args = ["-f", "lavfi", "-i", f"testsrc2=size={size}:rate=25", "-frames:v", "2"]
        result = _ffmpeg([*args, "-pix_fmt", "nv12", "-c:v", "av1_amf", str(out)], timeout=60)
        assert result.returncode == 0, _fail_text(result)
        stream = _probe(out, "-show_streams")["streams"][0]
        sizes[size] = (stream["width"], stream["height"])
    assert sizes == {
        "1920x1080": (1920, 1082),
        "720x480": (768, 480),
        "1280x720": (1280, 720),
        "640x360": (640, 362),
    }
