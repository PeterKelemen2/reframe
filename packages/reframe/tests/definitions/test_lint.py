"""The definitions linter: the packaged data passes, and each broken rule is reported."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest

from reframe.definitions import Definitions, load_definitions
from reframe.definitions.loader import load_raw
from reframe_testing.definitions_lint import lint_definitions


def test_the_packaged_definitions_are_clean() -> None:
    assert lint_definitions(load_definitions()) == []


def test_every_option_has_help_and_a_mapping() -> None:
    for encoder in load_definitions().video_encoders.values():
        for option in encoder.options:
            assert len(option.help) >= 10, (encoder.id, option.key)
            assert option.mapping.kind in ("x26x_param", "ffmpeg_arg", "private_opt")


def _lint_mutated(mutate: Callable[[dict[str, Any]], None]) -> list[str]:
    raw = load_raw()
    mutate(raw)
    return lint_definitions(Definitions.model_validate(raw))


def _option(raw: dict[str, Any], encoder: str, key: str) -> dict[str, Any]:
    options: list[dict[str, Any]] = raw["video_encoders"][encoder]["options"]
    return next(o for o in options if o["key"] == key)


def _has(problems: list[str], *needles: str) -> bool:
    return any(all(n in p for n in needles) for p in problems)


def test_missing_help_is_reported() -> None:
    problems = _lint_mutated(lambda raw: _option(raw, "libx264", "bframes").update(help=""))
    assert _has(problems, "libx264.options.bframes", "help")


def test_bad_mappings_are_reported() -> None:
    def mutate(raw: dict[str, Any]) -> None:
        _option(raw, "hevc_nvenc", "bf")["mapping"] = {"kind": "ffmpeg_arg", "arg": "bf"}
        _option(raw, "hevc_nvenc", "spatial-aq")["mapping"] = {"kind": "private_opt", "name": "-x"}
        raw["video_encoders"]["libx264"]["params_arg"] = None

    problems = _lint_mutated(mutate)
    assert _has(problems, "hevc_nvenc.options.bf", "dash")
    assert _has(problems, "hevc_nvenc.options.spatial-aq", "without the dash")
    assert _has(problems, "libx264.options.bframes", "without params_arg")


@pytest.mark.parametrize(
    ("changes", "needle"),
    [
        ({"min": 10, "max": 5}, "min < max"),
        ({"step": 0}, "min < max and a positive step"),
        ({"step": 0.5}, "integer min, max and step"),
        ({"min": None}, "needs min, max and step"),
        ({"choices": [{"value": "1", "label": "x"}]}, "only enums have choices"),
    ],
)
def test_inconsistent_ranges_are_reported(changes: dict[str, Any], needle: str) -> None:
    problems = _lint_mutated(lambda raw: _option(raw, "libx264", "bframes").update(changes))
    assert _has(problems, "libx264.options.bframes", needle), problems


def test_defaults_outside_the_range_are_reported() -> None:
    def mutate(raw: dict[str, Any]) -> None:
        _option(raw, "libx264", "bframes")["default"]["values"]["medium"] = 99
        _option(raw, "libx264", "keyint")["default"] = {"kind": "fixed", "value": "x"}
        _option(raw, "libx264", "me")["default"]["values"]["slow"] = "warp"
        _option(raw, "libx264", "mbtree")["default"]["values"]["slow"] = 1
        _option(raw, "libx264", "ref")["default"]["values"]["ludicrous"] = 3
        _option(raw, "libx264", "ref")["default"]["tunes"] = ["noir"]

    problems = _lint_mutated(mutate)
    assert _has(problems, "bframes", "outside")
    assert _has(problems, "keyint", "not a number")
    assert _has(problems, "options.me", "not a choice")
    assert _has(problems, "mbtree", "not a bool")
    assert _has(problems, "options.ref", "unknown preset 'ludicrous'")
    assert _has(problems, "options.ref", "unknown tune 'noir'")


def test_enum_problems_are_reported() -> None:
    def mutate(raw: dict[str, Any]) -> None:
        _option(raw, "libx264", "me")["choices"] = []
        _option(raw, "libx264", "trellis")["choices"] = [
            {"value": "0", "label": "a"},
            {"value": "0", "label": "b"},
        ]
        _option(raw, "libx264", "b-adapt")["choices"][0]["label"] = ""

    problems = _lint_mutated(mutate)
    assert _has(problems, "options.me", "needs choices")
    assert _has(problems, "options.trellis", "duplicate choices")
    assert _has(problems, "options.b-adapt", "needs a label")


def test_duplicate_keys_and_composite_parts_are_reported() -> None:
    def mutate(raw: dict[str, Any]) -> None:
        options = raw["video_encoders"]["libx264"]["options"]
        options.append(dict(_option(raw, "libx264", "ref")))
        _option(raw, "libx264", "deblock-beta")["mapping"]["part"] = 3

    problems = _lint_mutated(mutate)
    assert _has(problems, "options.ref", "duplicate key")
    assert _has(problems, "parts of 'deblock'")


def test_bad_conditions_are_reported() -> None:
    def mutate(raw: dict[str, Any]) -> None:
        _option(raw, "libx264", "aq-strength")["requires"] = [
            {"field": "option:nope", "value": 1},
            {"field": "colour", "value": 1},
            {"field": "rate_control", "value": "crf"},
            {"field": "bit_depth", "value": 12},
            {"field": "option:aq-mode", "value": "9"},
            {"field": "preset", "op": "eq", "value": ["a", "b"]},
        ]

    problems = _lint_mutated(mutate)
    for needle in (
        "unknown option 'nope'",
        "unknown condition field",
        "'quality' or 'bitrate'",
        "8 or 10",
        "requires aq-mode",
        "eq takes one value",
    ):
        assert _has(problems, "aq-strength", needle), needle


def test_a_fallback_chain_ending_in_hardware_is_reported() -> None:
    def mutate(raw: dict[str, Any]) -> None:
        raw["video_encoders"]["hevc_nvenc"]["fallback"] = ["hevc_qsv", "hevc_amf"]
        raw["video_encoders"]["h264_qsv"]["fallback"] = ["h264_qsv", "libx265", "nope"]
        raw["video_encoders"]["av1_amf"]["fallback"] = []
        raw["video_encoders"]["libx264"]["fallback"] = ["libx265"]
        raw["video_encoders"]["hevc_vaapi"]["fallback"] = ["libx265", "libx265"]

    problems = _lint_mutated(mutate)
    assert _has(problems, "hevc_nvenc.fallback", "must end in a software encoder")
    assert _has(problems, "h264_qsv.fallback", "itself")
    assert _has(problems, "h264_qsv.fallback", "libx265 is hevc")
    assert _has(problems, "h264_qsv.fallback", "unknown encoder 'nope'")
    assert _has(problems, "av1_amf.fallback", "needs a fallback chain")
    assert _has(problems, "libx264.fallback", "needs no fallback")
    assert _has(problems, "hevc_vaapi.fallback", "duplicate")


def test_identity_problems_are_reported() -> None:
    def mutate(raw: dict[str, Any]) -> None:
        enc = raw["video_encoders"]["libx264"]
        enc["handbrake_key"] = "x265"
        enc["pix_fmts"] = {"10": "yuv420p10le"}
        raw["video_encoders"]["libx265"]["label"] = ""
        raw["video_encoders"]["libsvtav1"]["id"] = "other"

    problems = _lint_mutated(mutate)
    assert _has(problems, "handbrake_key 'x265' also used")
    assert _has(problems, "libx264", "no 8-bit")
    assert _has(problems, "libx265", "must not be empty")
    assert _has(problems, "libsvtav1", "differs from the table key")


def test_quality_mode_problems_are_reported() -> None:
    def mutate(raw: dict[str, Any]) -> None:
        q = raw["video_encoders"]["libx264"]["rate_control"]["quality"]
        q.update(default=99, args=["-crf", "{nope}"], scale=[[0, 0], [30, 40], [20, 51]])
        q["recommended"] = [
            {"max_height": 1080, "low": 30, "high": 99},
            {"max_height": 720, "low": 1, "high": 2},
        ]
        q2 = raw["video_encoders"]["libx265"]["rate_control"]["quality"]
        q2.update(min=60, step=0, scale=[[0, 0]], params={"crf": "{value}"})
        raw["video_encoders"]["libx265"]["params_arg"] = None
        q3 = raw["video_encoders"]["libsvtav1"]["rate_control"]["quality"]
        q3.update(scale=[[10, 0], [50, 51]])

    problems = _lint_mutated(mutate)
    w = "libx264.rate_control.quality"
    for needle in (
        "off the step grid",
        "do not use {value}",
        "unknown placeholders",
        "both increase",
        "outside the range",
        "max_height must increase",
    ):
        assert _has(problems, w, needle), needle
    w2 = "libx265.rate_control.quality"
    for needle in (
        "min must be below max",
        "step must be positive",
        "at least two points",
        "params need a params_arg",
    ):
        assert _has(problems, w2, needle), needle
    assert _has(problems, "libsvtav1.rate_control.quality.scale", "cover the range")


def test_bitrate_mode_problems_are_reported() -> None:
    def mutate(raw: dict[str, Any]) -> None:
        b = raw["video_encoders"]["libx264"]["rate_control"]["bitrate"]
        b.update(args=["-b:v", "{rate}k"], min_kbps=0)
        b["two_pass"].update(args=["-passlogfile", "{passlog}", "{x}"])
        b2 = raw["video_encoders"]["hevc_nvenc"]["rate_control"]["bitrate"]
        b2["two_pass"].update(full_args=[])
        raw["video_encoders"]["libx265"]["params_arg"] = None
        raw["video_encoders"]["libvpx-vp9"]["rate_control"] = {}

    problems = _lint_mutated(mutate)
    w = "libx264.rate_control.bitrate"
    for needle in (
        "min_kbps",
        "do not use {kbps}",
        "unknown placeholders ['rate']",
        "unknown placeholders ['x']",
        "every run",
    ):
        assert _has(problems, w, needle), needle
    assert _has(problems, "hevc_nvenc.rate_control.bitrate.two_pass", "turn it on")
    assert _has(problems, "libx265.rate_control.bitrate.two_pass", "params_arg")
    assert _has(problems, "libvpx-vp9.rate_control", "quality or a bitrate")


def test_choice_setting_problems_are_reported() -> None:
    def mutate(raw: dict[str, Any]) -> None:
        enc = raw["video_encoders"]["libx265"]
        enc["presets"]["default"] = "warp"
        enc["profiles"]["default_by_depth"] = {"8": "main10", "10": "nope"}
        enc["tunes"]["choices"].append(dict(enc["tunes"]["choices"][0]))
        enc["levels"]["choices"][0]["bit_depths"] = [12]
        enc["levels"]["choices"][1]["label"] = ""
        raw["video_encoders"]["libx264"]["profiles"]["choices"] = [
            {"value": "high", "label": "High", "bit_depths": [8]}
        ]
        raw["video_encoders"]["libvpx-vp9"]["tunes"]["choices"] = []
        raw["video_encoders"]["libsvtav1"]["fast_decode"] = {"tune": None}

    problems = _lint_mutated(mutate)
    assert _has(problems, "libx265.presets", "'warp' is not a choice")
    assert _has(problems, "libx265.profiles", "8-bit 'main10' is not valid")
    assert _has(problems, "libx265.profiles", "10-bit 'nope' is not a choice")
    assert _has(problems, "libx265.tunes", "duplicate values")
    assert _has(problems, "libx265.levels", "unknown bit depth")
    assert _has(problems, "libx265.levels", "has no label")
    assert _has(problems, "libx264.profiles", "no profile for 10-bit")
    assert _has(problems, "libvpx-vp9.tunes", "no choices")
    assert _has(problems, "libsvtav1.fast_decode", "needs a tune")


@pytest.mark.parametrize(
    ("encoder", "values"),
    [
        ("libsvtav1", ["0", "1", "2"]),  # SVT-AV1 listed slowest first
        ("libx264", ["medium", "fast"]),
        ("hevc_nvenc", ["p2", "p1"]),
        ("h264_amf", ["quality", "speed"]),
    ],
)
def test_presets_not_fastest_first_are_reported(encoder: str, values: list[str]) -> None:
    def mutate(raw: dict[str, Any]) -> None:
        presets = raw["video_encoders"][encoder]["presets"]
        presets["choices"] = [{"value": v, "label": v} for v in values]
        presets["default"] = values[0]

    assert _has(_lint_mutated(mutate), f"{encoder}.presets", "fastest first")


def test_a_preset_of_unknown_speed_is_reported() -> None:
    def mutate(raw: dict[str, Any]) -> None:
        raw["video_encoders"]["libx265"]["presets"]["choices"].append(
            {"value": "warp", "label": "Warp"}
        )

    assert _has(_lint_mutated(mutate), "libx265.presets", "speed of preset 'warp'")


def test_hardware_setup_problems_are_reported() -> None:
    def mutate(raw: dict[str, Any]) -> None:
        setup = raw["video_encoders"]["h264_vaapi"]["hardware_setup"]
        setup["init_args"] = ["-init_hw_device", "vaapi=va:{device}"]
        setup["filter_tail"] = ["format={pix_fmt}", "hwupload"]
        raw["video_encoders"]["libx264"]["hardware_setup"] = {"init_args": ["-x"]}

    problems = _lint_mutated(mutate)
    assert _has(problems, "h264_vaapi.hardware_setup", "unknown placeholders ['device', 'pix_fmt']")
    assert _has(problems, "libx264.hardware_setup", "software encoder")


def test_derived_value_problems_are_reported() -> None:
    def mutate(raw: dict[str, Any]) -> None:
        derived = raw["video_encoders"]["av1_nvenc"]["rate_control"]["quality"]["derived"]
        derived["qp_p"]["factor"] = 0
        derived["qp_b"].update(min=10, max=5)

    problems = _lint_mutated(mutate)
    assert _has(problems, "av1_nvenc.rate_control.quality.derived.qp_p", "factor")
    assert _has(problems, "av1_nvenc.rate_control.quality.derived.qp_b", "min must not")


def test_audio_problems_are_reported() -> None:
    def mutate(raw: dict[str, Any]) -> None:
        ac3 = raw["audio_encoders"]["ac3"]
        ac3["bitrate"]["by_mixdown"]["stereo"] = {"min": 100, "max": 640, "default": 50}
        ac3["bitrate"]["by_mixdown"]["mono"]["max"] = 650
        ac3["mixdowns"] = [*ac3["mixdowns"], "7.1"]
        raw["audio_encoders"]["flac"]["bitrate"] = {"by_mixdown": {}}
        del raw["audio_encoders"]["libopus"]["bitrate"]
        raw["audio_encoders"]["aac"]["samplerates"] = [48000, 44100]
        raw["audio_encoders"]["libmp3lame"]["quality"].update(min=9, max=0)
        raw["audio_encoders"]["libmp3lame"]["quality"]["arg"] = "q:a"
        raw["audio_encoders"]["eac3"]["bitrate"]["allowed"] = [64, 32]
        raw["audio_encoders"]["libfdk_aac"]["mixdowns"] = []
        del raw["mixdowns"]["dpl2"]
        del raw["passthru_codecs"]["dtshd"]

    problems = _lint_mutated(mutate)
    assert _has(problems, "ac3.bitrate.stereo", "min <= default")
    assert _has(problems, "ac3.bitrate.mono", "650 is not an allowed value")
    assert _has(problems, "ac3", "more channels than max_channels")
    assert _has(problems, "ac3.bitrate", "exactly the mixdowns")
    assert _has(problems, "flac", "lossless encoder has no bitrate")
    assert _has(problems, "libopus", "needs bitrates")
    assert _has(problems, "aac", "sorted and unique")
    assert _has(problems, "libmp3lame.quality", "min < max")
    assert _has(problems, "libmp3lame.quality", "dash")
    assert _has(problems, "eac3.bitrate.allowed", "sorted")
    assert _has(problems, "libfdk_aac", "needs mixdowns")
    assert _has(problems, "mixdowns: dpl2")
    assert _has(problems, "unknown mixdown dpl2")
    assert _has(problems, "passthru_codecs: dtshd")


def test_container_problems_are_reported() -> None:
    def mutate(raw: dict[str, Any]) -> None:
        mp4 = raw["containers"]["mp4"]
        mp4["extensions"] = ["mp4"]
        mp4["video"]["encode"] = ["h264", "theora"]
        mp4["audio"]["encode"] = ["aac", "vorbis"]
        mp4["subtitles"]["encode"] = ["pgs"]
        mp4["audio"]["copy_args"] = {"vorbis": ["-strict", "-2"]}
        raw["containers"]["webm"]["flags"] = ["forced"]
        raw["containers"]["webm"]["subtitles"] = {"copy": [], "encode": []}
        raw["containers"]["webm"]["audio"]["copy_except"] = ["aac"]
        raw["containers"]["webm"]["video"]["copy_except"] = ["vp9", "vp9"]
        raw["containers"]["webm"]["codec_tags"] = {"hevc": "hvc1", "vp9": ""}
        del raw["containers"]["mkv"]
        del raw["track_flags"]["original"]

    problems = _lint_mutated(mutate)
    for needle in (
        "containers.mp4: extensions",
        "unknown codecs ['theora']",
        "unknown codecs ['vorbis']",
        "unknown formats ['pgs']",
        "text_subtitle_target",
        "vorbis is not copyable",
        "webm: every muxer writes the default flag",
        "webm.subtitles: holds nothing",
        "webm.audio.copy_except: only needed with copy = ['*']",
        "webm.video.copy_except: duplicate entries",
        "webm.video: ['vp9'] both copyable and denied",
        "webm.codec_tags: the container cannot hold hevc",
        "webm.codec_tags: empty tag for vp9",
        "containers: mkv is not defined",
        "track_flags: original",
    ):
        assert _has(problems, needle), needle


def test_an_encoder_no_container_can_hold_is_reported() -> None:
    def mutate(raw: dict[str, Any]) -> None:
        for container in raw["containers"].values():
            container["video"]["encode"] = [c for c in container["video"]["encode"] if c != "vp9"]

    assert _has(_lint_mutated(mutate), "libvpx-vp9", "no container can hold vp9")


def _impl(raw: dict[str, Any], filter_id: str, impl_id: str) -> dict[str, Any]:
    impls: list[dict[str, Any]] = raw["filters"][filter_id]["implementations"]
    return next(i for i in impls if i["id"] == impl_id)


def test_filter_problems_are_reported() -> None:
    def mutate(raw: dict[str, Any]) -> None:
        raw["filters"]["denoise"]["help"]["what"] = ""
        nlmeans = _impl(raw, "denoise", "nlmeans")
        nlmeans["default_preset"] = "nope"
        presets = nlmeans["presets"]
        presets[0]["tune_chains"].pop("film")
        presets[1]["chain"] = "nlmeans={strength}"
        presets[2]["chain"] = "hqdn3d=1"
        presets[3]["custom"] = True
        presets[4]["label"] = ""
        presets[4]["chain"] = None
        presets.append(dict(presets[0]))
        nlmeans["tunes"].append({"id": "film", "label": "again"})
        hqdn3d = _impl(raw, "denoise", "hqdn3d")
        hqdn3d["presets"][0]["tune_chains"] = {"tiny": "hqdn3d"}
        hqdn3d["label"] = ""
        cas = _impl(raw, "sharpen", "cas")
        cas["presets"] = [p for p in cas["presets"] if p.get("custom")]
        raw["filters"]["deinterlace"]["implementations"].append(
            dict(_impl(raw, "deinterlace", "yadif"))
        )
        del raw["filters"]["grayscale"]
        raw["filter_order"] = [*raw["filter_order"], "crop", "blur"]
        _impl(raw, "deinterlace", "bwdif")["presets"][0]["chain"] = " "

    problems = _lint_mutated(mutate)
    for needle in (
        "filters.denoise.help: what",
        "denoise.nlmeans: default_preset 'nope'",
        "needs a chain for every tune of nlmeans",
        "unknown placeholders ['strength']",
        "chain uses ['hqdn3d'], not in nlmeans",
        "custom must be true exactly",
        "needs a label",
        "has no chain",
        "denoise.nlmeans: duplicate preset ids",
        "denoise.nlmeans: duplicate tune ids",
        "denoise.hqdn3d.presets.ultralight: unknown tunes ['tiny']",
        "denoise.hqdn3d: needs a label",
        "sharpen.cas: needs at least one preset that is not custom",
        "filters.deinterlace: needs implementations with unique ids",
        "filters: grayscale is not defined",
        "filter_order",
        "empty chain",
    ):
        assert _has(problems, needle), needle


def test_only_audio_encoders_missing_from_gpl_builds_fall_back() -> None:
    audio = load_definitions().audio_encoders
    assert audio["libfdk_aac"].fallback == ["aac"]
    assert audio["aac"].in_gpl_builds
    for encoder in audio.values():
        if encoder.in_gpl_builds:
            assert encoder.fallback == [], encoder.id


def test_audio_fallback_problems_are_reported() -> None:
    def mutate(raw: dict[str, Any]) -> None:
        audio = raw["audio_encoders"]
        audio["libfdk_aac"]["fallback"] = ["libfdk_aac", "nope", "aac", "aac"]
        audio["ac3"]["fallback"] = ["libfdk_aac"]
        audio["eac3"]["in_gpl_builds"] = False

    problems = _lint_mutated(mutate)
    assert _has(problems, "libfdk_aac.fallback", "itself")
    assert _has(problems, "libfdk_aac.fallback", "unknown audio encoder 'nope'")
    assert _has(problems, "libfdk_aac.fallback", "duplicate")
    assert _has(problems, "ac3.fallback", "must end in an encoder of every GPL build")
    assert _has(problems, "eac3.fallback", "needs a fallback chain")
