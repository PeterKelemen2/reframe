"""The built-in presets: valid, built from the definitions, and the HandBrake 1.11.2 values."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Any

import pytest

from reframe.definitions import Definitions, load_definitions
from reframe.models import (
    BUILT_IN_CATEGORIES,
    AverageBitrate,
    ConstantQuality,
    FitWithin,
    Preset,
    PresetFile,
    Rational,
    SameAsSource,
)
from reframe.presets import DEFAULT_BUILTIN_ID, builtin_ids, builtin_presets

BUILTIN_JSON = (
    Path(__file__).resolve().parents[2] / "src" / "reframe" / "presets" / "data" / "builtin.json"
)

#: RuleMixdown → the encoder mixdown whose bitrate limits apply.
RULE_MIXDOWN = {"stereo": "stereo", "5.1": "5.1", "mono": "mono", "dpl2": "dpl2"}


@pytest.fixture(scope="module")
def defs() -> Definitions:
    return load_definitions()


PRESETS = builtin_presets()
IDS = [p.id for p in PRESETS]


def by_id(preset_id: str) -> Preset:
    return next(p for p in PRESETS if p.id == preset_id)


def test_the_file_is_a_current_preset_file() -> None:
    import json

    data = json.loads(BUILTIN_JSON.read_text("utf-8"))
    file = PresetFile.model_validate(data)
    assert file.schema_version == PresetFile().schema_version
    assert [p.id for p in file.presets] == IDS
    # Nothing unknown hides in the JSON (a typo would be kept silently as an extra field).
    for preset in file.presets:
        assert_no_extras(preset, preset.id)


def assert_no_extras(model: Any, where: str) -> None:
    from pydantic import BaseModel

    if isinstance(model, BaseModel):
        assert not model.model_extra, f"{where}: unknown fields {model.model_extra}"
        for name in type(model).model_fields:
            assert_no_extras(getattr(model, name), f"{where}.{name}")
    elif isinstance(model, dict):
        for key, value in model.items():
            assert_no_extras(value, f"{where}.{key}")
    elif isinstance(model, list):
        for index, value in enumerate(model):
            assert_no_extras(value, f"{where}[{index}]")


def test_ids_are_unique_stable_slugs() -> None:
    assert len(set(IDS)) == len(IDS)
    for preset_id in IDS:
        assert re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", preset_id), preset_id
    assert builtin_ids() == frozenset(IDS)


def test_names_are_unique_without_case() -> None:
    names = [p.name.casefold() for p in PRESETS]
    assert len(set(names)) == len(names)


def test_every_preset_is_built_in_valid_and_ends_with_the_catch_all() -> None:
    for preset in PRESETS:
        assert preset.built_in
        assert preset.category in BUILT_IN_CATEGORIES, preset.id
        assert preset.description
        assert Preset.model_validate(preset.model_dump(mode="json")) == preset
        assert preset.audio_defaults.codec_rules[-1].is_catch_all, preset.id
        assert preset.naming is None


def test_every_category_has_presets() -> None:
    assert {p.category for p in PRESETS} == set(BUILT_IN_CATEGORIES)


def test_presets_of_the_m2_demo_exist() -> None:
    demo = by_id("h265-mkv-1080p")
    assert demo.name == "H.265 MKV 1080p"
    assert demo.video.encoder == "libx265"
    assert demo.output.container == "mkv"
    assert demo.dimensions.size == FitWithin(width=1920, height=1080)
    nvenc = by_id("h265-nvenc-1080p")
    assert nvenc.name == "H.265 NVENC 1080p"
    assert nvenc.video.encoder == "hevc_nvenc"
    assert nvenc.category == "Hardware"


def test_default_preset_is_h265_mkv_1080p() -> None:
    """Not HandBrake's default, Fast 1080p30."""
    import json

    assert DEFAULT_BUILTIN_ID == "h265-mkv-1080p"
    assert by_id(DEFAULT_BUILTIN_ID).name == "H.265 MKV 1080p"
    data = json.loads(BUILTIN_JSON.read_text("utf-8"))
    assert data["default_preset_id"] == DEFAULT_BUILTIN_ID


def test_builtin_presets_returns_copies() -> None:
    first = builtin_presets()
    first[0].video.encoder = "changed"
    assert builtin_presets()[0].video.encoder != "changed"


@pytest.mark.parametrize("preset", PRESETS, ids=IDS)
def test_video_uses_only_definition_values(preset: Preset, defs: Definitions) -> None:
    video = preset.video
    assert video.encoder in defs.video_encoders
    encoder = defs.video_encoders[video.encoder]
    container = defs.containers[preset.output.container]
    assert encoder.codec in container.video.encode
    rate = video.rate_control
    if isinstance(rate, ConstantQuality):
        quality = encoder.rate_control.quality
        assert quality is not None
        assert quality.min <= rate.value <= quality.max
    else:
        bitrate = encoder.rate_control.bitrate
        assert bitrate is not None
        assert bitrate.min_kbps <= rate.kbps <= bitrate.max_kbps
        assert not rate.two_pass or bitrate.two_pass is not None
    for name in ("preset", "tune", "profile", "level"):
        value = getattr(video, name)
        if value is None:
            continue
        setting = getattr(encoder, f"{name}s")
        assert setting is not None, f"{video.encoder} has no {name}s"
        choice = next((c for c in setting.choices if c.value == value), None)
        assert choice is not None, f"{video.encoder} {name} {value!r}"
        if choice.bit_depths is not None:
            assert video.bit_depth in choice.bit_depths
    assert str(video.bit_depth) in encoder.pix_fmts
    options = {o.key: o for o in encoder.options}
    for key, value in video.advanced.items():
        assert key in options, f"{video.encoder} has no option {key}"
        expected: dict[str, type | tuple[type, ...]] = {
            "int": int,
            "float": (int, float),
            "bool": bool,
            "string": str,
            "enum": str,
        }
        assert isinstance(value, expected[options[key].type])
    if video.custom_params:
        assert encoder.params_arg is not None, f"{video.encoder} takes no parameter string"
    assert not video.passthrough


@pytest.mark.parametrize("preset", PRESETS, ids=IDS)
def test_filters_use_only_definition_values(preset: Preset, defs: Definitions) -> None:
    for filter_id, config in preset.filters.root.items():
        assert filter_id in defs.filters
        implementation = defs.filters[filter_id].implementation_for(config)
        assert implementation is not None, f"{filter_id}: {config}"
        assert implementation.preset(config.preset) is not None
        if config.tune is not None:
            assert config.tune in {t.id for t in implementation.tunes}


@pytest.mark.parametrize("preset", PRESETS, ids=IDS)
def test_audio_uses_only_definition_values(preset: Preset, defs: Definitions) -> None:
    container = defs.containers[preset.output.container]
    audio = preset.audio_defaults
    outputs: list[tuple[str, str, int | None]] = []
    for rule in audio.codec_rules:
        outputs.append((rule.codec, rule.mixdown, rule.max_bitrate))
        outputs.extend((x.codec, x.mixdown, x.bitrate) for x in rule.extras.extra_outputs)
        if rule.extras.samplerate is not None:
            assert rule.extras.samplerate in defs.audio_encoders[rule.codec].samplerates
    for codec, mixdown, bitrate in outputs:
        assert codec in defs.audio_encoders, codec
        encoder = defs.audio_encoders[codec]
        assert encoder.codec in container.audio.encode, f"{codec} in {container.id}"
        assert encoder.bitrate is not None
        limits = encoder.bitrate.by_mixdown[RULE_MIXDOWN[mixdown]]  # type: ignore[index]
        assert bitrate is not None
        assert limits.min <= bitrate <= limits.max
        allowed = encoder.bitrate.values(RULE_MIXDOWN[mixdown])  # type: ignore[arg-type]
        assert allowed is None or bitrate in allowed
    fallback = defs.audio_encoders[audio.passthru.fallback_encoder]
    assert fallback.codec in container.audio.encode
    for codec in audio.passthru.allowed:
        name = defs.passthru_codecs[codec].codec_name
        assert "*" in container.audio.copy_codecs or name in container.audio.copy_codecs


#: The HandBrake 1.11.2 values of each built-in. The text column is space-separated: encoder,
#: quality (or ``<kbps>k`` for 2-pass average bit rate), speed preset, profile, level, bit
#: depth, fit box (or ``source``), frame rate ``fps:mode``, container, crop mode, comb detection
#: preset (with deinterlace ``default``); ``-`` = not set. Then the audio codec rules as
#: (codec, mixdown, kb/s).
SURROUND = [("ac3", "5.1", 640), ("aac", "stereo", 160)]
AAC160 = [("aac", "stereo", 160)]
AAC320 = [("aac", "stereo", 320)]
OPUS160 = [("libopus", "stereo", 160)]
HANDBRAKE: dict[str, tuple[str, str, list[tuple[str, str, int]]]] = {
    "very-fast-1080p30": (
        "Very Fast 1080p30",
        "libx264 24 veryfast main 4.0 8 1920x1080 30:peak mp4 auto fast",
        AAC160,
    ),
    "fast-1080p30": (
        "Fast 1080p30",
        "libx264 22 fast main 4.0 8 1920x1080 30:peak mp4 auto default",
        AAC160,
    ),
    "fast-720p30": (
        "Fast 720p30",
        "libx264 21 fast main 3.1 8 1280x720 30:peak mp4 auto default",
        AAC160,
    ),
    "hq-1080p30-surround": (
        "HQ 1080p30 Surround",
        "libx264 20 slow high 4.0 8 1920x1080 30:peak mp4 auto default",
        SURROUND,
    ),
    "super-hq-1080p30-surround": (
        "Super HQ 1080p30 Surround",
        "libx264 18 veryslow high 4.0 8 1920x1080 30:peak mp4 auto default",
        SURROUND,
    ),
    "fast-2160p60-4k-hevc": (
        "Fast 2160p60 4K HEVC",
        "libx265 24 faster main10 - 10 3840x2160 60:peak mp4 auto default",
        AAC160,
    ),
    "creator-1080p60": (
        "Creator 1080p60",
        "libx264 20 medium high 4.2 8 1920x1080 60:peak mp4 auto -",
        AAC320,
    ),
    "social-25-mb-1-minute-720p60": (
        "Social 25 MB 1 Minute 720p60",
        "libx264 3000k medium high 3.2 8 1280x720 60:peak mp4 auto -",
        AAC160,
    ),
    "android-1080p30": (
        "Android 1080p30",
        "libx264 22 medium main 4.0 8 1920x1080 30:peak mp4 auto default",
        AAC160,
    ),
    "apple-1080p30-surround": (
        "Apple 1080p30 Surround",
        "libx264 22 medium high 4.0 8 1920x1080 30:peak mp4 auto default",
        SURROUND,
    ),
    "chromecast-1080p30-surround": (
        "Chromecast 1080p30 Surround",
        "libx264 22 medium high 4.0 8 1920x1080 30:peak mp4 auto default",
        SURROUND,
    ),
    "h265-mkv-1080p": (
        "H.265 MKV 1080p30",
        "libx265 22 slow main10 - 10 1920x1080 -:variable mkv auto default",
        AAC160,
    ),
    "h265-mkv-720p": (
        "H.265 MKV 720p30",
        "libx265 21 slow main10 - 10 1280x720 -:variable mkv auto default",
        AAC160,
    ),
    "h265-mkv-2160p-4k": (
        "H.265 MKV 2160p60 4K",
        "libx265 24 slow main10 - 10 3840x2160 -:variable mkv auto default",
        AAC160,
    ),
    "h264-mkv-1080p": (
        "H.264 MKV 1080p30",
        "libx264 22 medium main 4.0 8 1920x1080 -:variable mkv auto default",
        AAC160,
    ),
    "av1-mkv-2160p-4k": (
        "AV1 MKV 2160p60 4K",
        "libsvtav1 35 4 - - 10 3840x2160 -:variable mkv auto default",
        OPUS160,
    ),
    "vp9-mkv-1080p": (
        "VP9 MKV 1080p30",
        "libvpx-vp9 30 medium - - 8 1920x1080 -:variable mkv auto default",
        OPUS160,
    ),
    "h265-nvenc-1080p": (
        "H.265 NVENC 1080p",
        "hevc_nvenc 27 p4 - - 8 1920x1080 -:variable mp4 none -",
        AAC160,
    ),
    "h265-nvenc-2160p-4k": (
        "H.265 NVENC 2160p 4K",
        "hevc_nvenc 30 p4 - - 8 3840x2160 -:variable mp4 none -",
        AAC160,
    ),
    "h265-qsv-1080p": (
        "H.265 QSV 1080p",
        "hevc_qsv 25 veryfast - - 8 1920x1080 -:variable mp4 none -",
        AAC160,
    ),
    "av1-qsv-2160p-4k": (
        "AV1 QSV 2160p 4K",
        "av1_qsv 24 veryfast - - 10 3840x2160 -:variable mp4 none -",
        AAC160,
    ),
    "h265-vcn-1080p": (
        "H.265 VCN 1080p",
        "hevc_amf 25 balanced main - 8 1920x1080 -:variable mp4 none -",
        AAC160,
    ),
    "av1-vcn-2160p-4k": (
        "AV1 VCN 2160p 4K",
        "av1_amf 120 balanced - - 10 3840x2160 -:variable mp4 none -",
        AAC160,
    ),
    "h265-vaapi-1080p": (
        "(H.265 VCN 1080p)",
        "hevc_vaapi 25 - - - 8 1920x1080 -:variable mp4 none -",
        AAC160,
    ),
    "production-standard": (
        "Production Standard",
        "libx264 10 fast high - 8 source -:constant mp4 none -",
        AAC320,
    ),
    "production-proxy-1080p": (
        "Production Proxy 1080p",
        "libx264 18 superfast high - 8 1920x1080 -:constant mp4 none -",
        AAC320,
    ),
}


def test_every_builtin_has_a_handbrake_row() -> None:
    assert set(HANDBRAKE) == set(IDS)


def _value(text: str) -> str | None:
    return None if text == "-" else text


@pytest.mark.parametrize("preset_id", list(HANDBRAKE))
def test_values_come_from_handbrake(preset_id: str) -> None:
    _handbrake_name, text, audio = HANDBRAKE[preset_id]
    encoder, quality, speed, profile, level, depth, box, rate, container, crop, comb = text.split()
    preset = by_id(preset_id)
    video = preset.video
    assert video.encoder == encoder
    if quality.endswith("k"):
        assert video.rate_control == AverageBitrate(
            kbps=int(quality[:-1]), two_pass=True, turbo_first_pass=True
        )
    else:
        assert video.rate_control == ConstantQuality(value=float(quality))
    assert video.preset == _value(speed)
    assert video.profile == _value(profile)
    assert video.level == _value(level)
    assert video.bit_depth == int(depth)
    if box == "source":
        assert preset.dimensions.size == SameAsSource()
    else:
        width, height = box.split("x")
        assert preset.dimensions.size == FitWithin(width=int(width), height=int(height))
    assert not preset.dimensions.allow_upscaling
    fps, mode = rate.split(":")
    assert video.framerate == (None if fps == "-" else Rational(num=int(fps), den=1))
    assert video.framerate_mode == mode
    assert preset.output.container == container
    assert preset.dimensions.crop.mode == crop
    if comb == "-":
        assert "deinterlace" not in preset.filters.root
        assert "interlace_detection" not in preset.filters.root
    else:
        assert preset.filters.root["interlace_detection"].preset == comb
        assert preset.filters.root["deinterlace"].preset == "default"
    assert set(preset.filters.root) <= {"interlace_detection", "deinterlace"}
    rules = preset.audio_defaults.codec_rules
    assert [(r.codec, r.mixdown, r.max_bitrate) for r in rules] == audio
    # HandBrake passes through only where its AudioList has a ``copy:*`` encoder; an encoder
    # entry such as ``aac`` always re-encodes.
    assert [r.if_fits for r in rules] == [
        "passthru" if r.codec == "ac3" else "reencode" for r in rules
    ]


def test_surround_presets_pass_ac3_through_and_add_aac_stereo() -> None:
    surround = 0
    for preset in PRESETS:
        rules = preset.audio_defaults.codec_rules
        if rules[0].codec != "ac3":
            continue
        surround += 1
        assert rules[0].source_channels == "5.1_or_more"
        assert rules[0].if_fits == "passthru"
        [extra] = rules[0].extras.extra_outputs
        assert (extra.codec, extra.mixdown, extra.bitrate) == ("aac", "stereo", 160)
        assert preset.audio_defaults.passthru.allowed == ["ac3"]
        assert rules[1].if_fits == "reencode"
    assert surround == 4


def test_passthru_lists_hold_what_handbrake_passes_through() -> None:
    for preset in PRESETS:
        passthru = preset.audio_defaults.passthru
        if preset.audio_defaults.codec_rules[-1].codec == "libopus":
            assert (passthru.allowed, passthru.fallback_encoder) == ([], "libopus")
        elif preset.audio_defaults.codec_rules[0].codec == "aac":
            assert (passthru.allowed, passthru.fallback_encoder) == ([], "aac")


def test_subtitle_and_track_selection_follow_handbrake() -> None:
    for preset in PRESETS:
        subs = preset.subtitle_defaults
        assert subs.selection.tracks_per_language == "none"
        assert subs.selection.no_match == "none"
        assert subs.selection.default_track == "none"
        hardware = preset.category == "Hardware"
        production = preset.category == "Production"
        assert subs.foreign_audio_search is not (hardware or production)
        assert subs.burn_in == ("none" if hardware else "foreign_audio")
        selection = preset.audio_defaults.selection
        assert selection.tracks_per_language == ("all" if production else "first")


def test_handbrake_extra_options_are_kept() -> None:
    x265 = (
        "strong-intra-smoothing=0:rect=0:aq-mode=1:rd=4:psy-rd=0.75:psy-rdoq=4.0:rdoq-level=1:"
        "rskip=2"
    )
    for preset_id in (
        "h265-mkv-1080p",
        "h265-mkv-720p",
        "h265-mkv-2160p-4k",
        "fast-2160p60-4k-hevc",
    ):
        assert by_id(preset_id).video.custom_params == x265
    assert by_id("h265-nvenc-1080p").video.advanced == {"rc-lookahead": 10}
    assert by_id("av1-mkv-2160p-4k").video.tune == "1"  # HandBrake "psnr"
    assert by_id("creator-1080p60").audio_defaults.codec_rules[0].extras.samplerate == 48000
    assert by_id("creator-1080p60").output.web_optimized
    assert by_id("chromecast-1080p30-surround").output.web_optimized
    general = [p for p in PRESETS if p.category in ("General", "Web")]
    assert all(p.output.align_av_start for p in general)


def _params_cases() -> list[tuple[str, str, str]]:
    cases = []
    for preset in PRESETS:
        if preset.video.custom_params:
            cases.append((preset.id, preset.video.encoder, preset.video.custom_params))
    return cases


#: A bad key in the parameter string is logged as a warning: the exit code stays 0.
BAD_PARAM = re.compile(r"unknown option|error parsing option", re.IGNORECASE)


def run_params(encoder: str, bit_depth: int, params: str, defs: Definitions) -> str:
    """Encode 10 frames with ``params``; returns FFmpeg's warnings."""
    from reframe_testing import media

    ffmpeg = media.find_ffmpeg()
    assert ffmpeg is not None
    definition = defs.video_encoders[encoder]
    assert definition.params_arg is not None
    pix_fmt = definition.pix_fmts[str(bit_depth)]  # type: ignore[index]
    result = subprocess.run(
        [
            ffmpeg, "-hide_banner", "-nostdin", "-v", "warning",
            "-f", "lavfi", "-i", "testsrc2=s=320x240:r=25:d=0.4",
            "-c:v", encoder, "-pix_fmt", pix_fmt, definition.params_arg, params,
            "-f", "null", "-",
        ],
        capture_output=True, text=True, timeout=120, check=False,
    )  # fmt: skip
    assert result.returncode == 0, result.stderr[-2000:]
    return result.stderr


@pytest.mark.needs_ffmpeg
@pytest.mark.parametrize(("preset_id", "encoder", "params"), _params_cases())
def test_handbrake_parameter_strings_work_in_ffmpeg(
    preset_id: str, encoder: str, params: str, defs: Definitions
) -> None:
    stderr = run_params(encoder, by_id(preset_id).video.bit_depth, params, defs)
    assert not BAD_PARAM.search(stderr), stderr[-2000:]


@pytest.mark.needs_ffmpeg
@pytest.mark.parametrize("encoder", ["libx264", "libx265", "libsvtav1"])
def test_a_bad_parameter_key_is_only_a_warning(encoder: str, defs: Definitions) -> None:
    assert BAD_PARAM.search(run_params(encoder, 8, "bogus-key=1", defs))


MULTITRACK = (
    Path(__file__).resolve().parents[4] / "testdata" / "probes" / "fixtures" / "multitrack.mkv.json"
)


AAC = [(1, "encode", "aac", 160), (2, "encode", "aac", 160), (3, "encode", "aac", 160)]
OPUS = [(n, "encode", "libopus", 160) for n in (1, 2, 3)]
AC3_PASSTHRU = [(1, "passthru", "ac3", None), *AAC]


@pytest.mark.parametrize(
    ("preset_id", "expected"),
    [
        # jpn AC-3 5.1 (192 kb/s), eng AAC 2.0, eng AAC 2.0 (no bit rate in the MKV)
        ("h265-mkv-1080p", AAC),
        ("hq-1080p30-surround", AC3_PASSTHRU),
        ("vp9-mkv-1080p", OPUS),
        ("h265-nvenc-1080p", AAC),
    ],
)
def test_m2_draft_of_the_multitrack_fixture(
    preset_id: str, expected: list[tuple[int, str, str, int | None]]
) -> None:
    """What ``draft_tracks`` does with the audio of the ``multitrack`` fixture: HandBrake
    re-encodes to AAC / Opus stereo and passes AC-3 5.1 through only in the Surround presets
    (plus an AAC stereo copy of it)."""
    import json

    from reframe.batch import draft_tracks
    from reframe.models import SourceFingerprint
    from reframe.probe import parse_ffprobe

    source = parse_ffprobe(
        json.loads(MULTITRACK.read_text("utf-8")),
        Path("/media/multitrack.mkv"),
        fingerprint=SourceFingerprint(size=0, mtime=0.0),
    )
    draft = draft_tracks(source, by_id(preset_id))
    got = [(t.source_stream, t.action, t.encoder, t.bitrate) for t in draft.audio]
    assert got == expected
    assert all(t.mixdown in (None, "stereo") for t in draft.audio)
