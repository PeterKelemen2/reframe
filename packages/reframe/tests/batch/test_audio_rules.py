"""C-12 codec-rule stage (03 §Audio defaults part 2 and 3; decision 0018, 0019)."""

from __future__ import annotations

from typing import Any

import pytest

from reframe.batch import (
    apply_codec_rules,
    channels_match,
    language_matches,
    passthru_codec,
    render_track_name,
    requested_mixdown,
)
from reframe.command import planned_audio
from reframe.definitions import channels_mixdown, load_definitions
from reframe.models import (
    AudioCodecRule,
    AudioDefaults,
    AudioOutputTrack,
    AudioRuleExtras,
    AudioStream,
    BitrateInfo,
    BitrateSource,
    Container,
    Disposition,
    ExtraAudioOutput,
    Mixdown,
    PassthruPolicy,
    RuleMixdown,
    SourceChannels,
    TrackDecision,
)

DEFS = load_definitions()

_LAYOUTS = {1: "mono", 2: "stereo", 6: "5.1(side)", 8: "7.1"}


def stream(
    codec: str,
    channels: int,
    kbps: float | None = None,
    *,
    language: str | None = "eng",
    index: int = 1,
    **fields: Any,
) -> AudioStream:
    """A source audio track. ``kbps`` ``None`` = unknown bit rate."""
    bitrate = (
        BitrateInfo(value=round(kbps * 1000), source=BitrateSource.STREAM)
        if kbps is not None
        else BitrateInfo()
    )
    fields.setdefault("channel_layout", _LAYOUTS.get(channels))
    return AudioStream(
        index=index, codec=codec, channels=channels, language=language, bitrate=bitrate, **fields
    )


def rules(*items: AudioCodecRule, passthru: PassthruPolicy | None = None) -> AudioDefaults:
    """Defaults with these rules and a catch-all last (AAC, up to 5.1, 256 kb/s) if needed."""
    codec_rules = list(items)
    if not codec_rules or not codec_rules[-1].is_catch_all:
        codec_rules.append(AudioCodecRule(codec="aac", mixdown="up_to_5.1", max_bitrate=256))
    return AudioDefaults(codec_rules=codec_rules, passthru=passthru or PassthruPolicy())


def run(
    source: AudioStream,
    defaults: AudioDefaults,
    container: Container = "mkv",
    **kwargs: Any,
) -> tuple[AudioOutputTrack, TrackDecision]:
    outputs, decision = apply_codec_rules(source, defaults, container, **kwargs)
    assert outputs == decision.outputs
    assert len(outputs) >= 1
    return outputs[0], decision


def summary(track: AudioOutputTrack) -> tuple[str, str | None, str | None, int | None]:
    return (track.action, track.encoder, track.mixdown, track.bitrate)


# --------------------------------------------------------------------------- 03's example

#: The four rules of 03 §Audio defaults, exactly as written there.
EXAMPLE_RULES = AudioDefaults(
    codec_rules=[
        AudioCodecRule(
            languages=["hu"], source_channels="5.1_or_more", codec="ac3", mixdown="5.1",
            max_bitrate=320, if_fits="passthru",
        ),
        AudioCodecRule(
            languages=["en"], source_channels="5.1_or_more", codec="ac3", mixdown="5.1",
            max_bitrate=384, if_fits="passthru",
        ),
        AudioCodecRule(
            languages=None, source_channels="stereo_or_less", codec="aac", mixdown="stereo",
            max_bitrate=160, if_fits="passthru",
        ),
        AudioCodecRule(
            languages=None, source_channels="any", codec="libopus", mixdown="up_to_5.1",
            max_bitrate=256, if_fits="reencode",
        ),
    ]
)  # fmt: skip

#: The four source tracks of 03's example, exactly as written there.
EXAMPLE = [
    # (source, rule, (action, encoder, mixdown, bitrate), reason, measure)
    (
        stream("dts", 6, 2104, language="hun", profile="DTS-HD MA",
               display_codec="DTS-HD MA", lossless=True),
        1,
        ("encode", "ac3", "5.1", 320),
        "Lossless source → encode at the max",
        False,
    ),
    (
        stream("ac3", 6, 224, language="hun", display_codec="AC-3"),
        1,
        ("passthru", "ac3", None, None),
        "AC-3, 5.1, 224 ≤ 320: passthru",
        False,
    ),
    (
        # 03 gives no bit rate: unknown, so the preview offers Measure.
        stream("truehd", 8, None, profile="Dolby TrueHD + Dolby Atmos",
               display_codec="TrueHD Atmos", lossless=True),
        2,
        ("encode", "ac3", "5.1", 384),
        "Downmix 7.1 → 5.1. Lossless source → encode at the max",
        True,
    ),
    (
        stream("ac3", 2, 192, display_codec="AC-3"),
        3,
        ("passthru", "aac", None, None),
        "Rule 2 needs 5.1 or more. Rule 3 matches, and the source fits (a lossy source is"
        " kept above the max)",
        False,
    ),
]  # fmt: skip


@pytest.mark.parametrize(
    ("source", "rule", "expected", "reason", "measure"),
    EXAMPLE,
    ids=["hun DTS-HD MA 5.1", "hun AC-3 5.1 224", "eng TrueHD Atmos 7.1", "eng AC-3 2.0 192"],
)
def test_example_of_03_row_by_row(
    source: AudioStream, rule: int, expected: tuple[Any, ...], reason: str, measure: bool
) -> None:
    """C-12 "Done when": Hungarian 5.1 → 320, English 5.1 → 384, AC-3 224 passthru, stereo
    passthru (decision 0023)."""
    track, decision = run(source, EXAMPLE_RULES)
    assert decision.rule == rule
    assert summary(track) == expected
    assert decision.reason == reason
    assert decision.source_stream == source.index
    assert decision.notes == []
    assert decision.measure is measure


# --------------------------------------------------------------------------- max bitrate rules

AC3_51_448 = AudioCodecRule(codec="ac3", mixdown="5.1", max_bitrate=448)
NO_DTS = PassthruPolicy(allowed=["ac3", "eac3", "aac"])


@pytest.mark.parametrize(
    ("source", "defaults", "expected", "reason", "measure"),
    [
        # Row 1. The source fits → passthru: a lossy source at any bit rate …
        (
            stream("eac3", 6, 384, display_codec="E-AC-3"),
            rules(AC3_51_448),
            ("passthru", "ac3", None, None),
            "E-AC-3, 5.1, 384 ≤ 448: passthru",
            False,
        ),
        (
            stream("ac3", 6, 640, display_codec="AC-3"),
            rules(AC3_51_448),
            ("passthru", "ac3", None, None),
            "AC-3, 5.1, 640 > 448: passthru (a lossy source is kept above the max)",
            False,
        ),
        (
            stream("aac", 2, None, display_codec="AAC-LC"),
            rules(AudioCodecRule(codec="aac", mixdown="stereo", max_bitrate=160)),
            ("passthru", "aac", None, None),
            "AAC, 2.0: passthru",
            False,
        ),
        # … a lossless source at or below the max …
        (
            stream("flac", 2, 133.718, display_codec="FLAC", lossless=True),
            rules(AudioCodecRule(codec="aac", mixdown="stereo", max_bitrate=160)),
            ("passthru", "aac", None, None),
            "FLAC, 2.0, 133.7 ≤ 160: passthru",
            False,
        ),
        # … or re-encode, if the rule says so (with the encoding rules).
        (
            stream("ac3", 6, 384, display_codec="AC-3"),
            rules(AC3_51_448.model_copy(update={"if_fits": "reencode"})),
            ("encode", "ac3", "5.1", 384),
            "384 ≤ 448, but the rule says re-encode → encode at 384 kb/s, the smallest"
            " allowed value ≥ 384",
            False,
        ),
        (
            stream("ac3", 6, 640, display_codec="AC-3"),
            rules(AC3_51_448.model_copy(update={"if_fits": "reencode"})),
            ("encode", "ac3", "5.1", 448),
            "The rule says re-encode, 640 > 448 → encode at the max",
            False,
        ),
        # Row 2. Lossless above the max or unknown → encode at the max …
        (
            stream("truehd", 6, 3912, display_codec="TrueHD", lossless=True),
            rules(AC3_51_448),
            ("encode", "ac3", "5.1", 448),
            "Lossless source → encode at the max",
            False,
        ),
        (
            stream("flac", 2, None, display_codec="FLAC", lossless=True),
            rules(AC3_51_448),
            ("encode", "ac3", None, 448),
            "Lossless source → encode at the max",
            True,
        ),
        # … and a source that does not fit, above the max.
        (
            stream("dts", 6, 1509, display_codec="DTS"),
            rules(AC3_51_448, passthru=NO_DTS),
            ("encode", "ac3", "5.1", 448),
            "DTS passthru is not allowed, 1509 > 448 → encode at the max",
            False,
        ),
        (
            stream("pcm_s16le", 2, 1536, display_codec="PCM", lossless=False),
            rules(AudioCodecRule(codec="aac", mixdown="stereo", max_bitrate=1000)),
            ("encode", "aac", "stereo", 512),
            "PCM cannot be passed through, 1536 > 1000 → encode at the max",
            False,
        ),
        # Row 3. At or below the max, but another codec …
        (
            stream("pcm_s16le", 2, 1536, display_codec="PCM", lossless=False),
            rules(AudioCodecRule(codec="aac", mixdown="stereo", max_bitrate=2000)),
            ("encode", "aac", "stereo", 512),
            "2000 kb/s",  # checked below: the snap note
            False,
        ),
        (
            stream("vorbis", 2, 200, display_codec="Vorbis"),
            rules(AudioCodecRule(codec="ac3", mixdown="stereo", max_bitrate=320)),
            ("encode", "ac3", "stereo", 224),
            "200 ≤ 320, but Vorbis cannot be passed through → encode at 224 kb/s, the smallest"
            " allowed value ≥ 200",
            False,
        ),
        # … or too many channels: the smallest allowed value at or above the source.
        (
            stream("ac3", 6, 384, display_codec="AC-3"),
            rules(AudioCodecRule(codec="aac", mixdown="stereo", max_bitrate=512)),
            ("encode", "aac", "stereo", 384),
            "Downmix 5.1 → Stereo. 384 ≤ 512, but 5.1 is more than Stereo → encode at 384"
            " kb/s, the smallest allowed value ≥ 384",
            False,
        ),
        # Row 4. Bit rate unknown, and the source does not fit → as above the max; Measure.
        (
            stream("vorbis", 2, None, display_codec="Vorbis"),
            rules(AudioCodecRule(codec="aac", mixdown="stereo", max_bitrate=160)),
            ("encode", "aac", "stereo", 160),
            "Vorbis cannot be passed through. Bitrate unknown: treated as above the max;"
            " Measure",
            True,
        ),
        (
            stream("aac", 2, None, display_codec="AAC-LC"),
            rules(AudioCodecRule(codec="aac", mixdown="stereo", max_bitrate=160,
                                 if_fits="reencode")),
            ("encode", "aac", "stereo", 160),
            "The rule says re-encode. Bitrate unknown: treated as above the max; Measure",
            True,
        ),
    ],
    ids=[
        "fits, lossy",
        "fits, lossy above the max",
        "fits, lossy bitrate unknown",
        "fits, lossless at or below the max",
        "fits, re-encode",
        "fits, re-encode above the max",
        "lossless above the max",
        "lossless, bitrate unknown",
        "does not fit, above the max",
        "does not fit, above the max and the encoder range",
        "another codec, above the encoder range",
        "another codec, snapped up",
        "too many channels",
        "does not fit, bitrate unknown",
        "re-encode, bitrate unknown",
    ],
)  # fmt: skip
def test_max_bitrate_rules(
    source: AudioStream,
    defaults: AudioDefaults,
    expected: tuple[Any, ...],
    reason: str,
    measure: bool,
) -> None:
    """Every row of 03's "Max bitrate rules" table."""
    track, decision = run(source, defaults)
    assert summary(track) == expected
    if reason == "2000 kb/s":
        assert (
            decision.reason == "1536 ≤ 2000, but PCM cannot be passed through → encode at the max"
        )
        assert decision.notes == ["AAC Stereo goes up to 512 kb/s: 2000 → 512 kb/s"]
    else:
        assert decision.reason == reason
    assert decision.measure is measure


def test_never_bigger_than_the_source() -> None:
    """A lossless source with a known bit rate below the max fits like any other (0019)."""
    flac = stream("flac", 2, 133.718, display_codec="FLAC", lossless=True, language="jpn")
    track, decision = run(flac, rules(AudioCodecRule(codec="aac", max_bitrate=160)))
    assert summary(track) == ("passthru", "aac", None, None)
    assert decision.reason == "FLAC, 2.0, 133.7 ≤ 160: passthru"
    # A free-range encoder rounds the source up to the next kb/s.
    aac = stream("aac", 2, 128.453, display_codec="AAC-LC")
    policy = PassthruPolicy(allowed=["ac3"])
    track, decision = run(aac, rules(AudioCodecRule(codec="aac", max_bitrate=160), passthru=policy))
    assert track.bitrate == 129
    assert decision.reason == (
        "128.5 ≤ 160, but AAC passthru is not allowed → encode at 129 kb/s, the smallest allowed"
        " value ≥ 128.5"
    )


# --------------------------------------------------------------------------- snapping


@pytest.mark.parametrize(
    ("rule", "source", "bitrate", "note"),
    [
        (
            AudioCodecRule(codec="ac3", mixdown="5.1", max_bitrate=300),
            stream("dts", 6, 1509, display_codec="DTS"),
            256,
            "300 kb/s is not an allowed AC-3 5.1 bit rate: 300 → 256 kb/s",
        ),
        (
            AudioCodecRule(codec="ac3", mixdown="5.1", max_bitrate=128),
            stream("dts", 6, 1509, display_codec="DTS"),
            224,
            "AC-3 5.1 needs at least 224 kb/s: 128 → 224 kb/s",
        ),
        (
            AudioCodecRule(codec="eac3", mixdown="stereo", max_bitrate=7000),
            stream("truehd", 2, None, display_codec="TrueHD", lossless=True),
            6144,
            "E-AC-3 Stereo goes up to 6144 kb/s: 7000 → 6144 kb/s",
        ),
    ],
)
def test_the_max_snaps_with_a_note(
    rule: AudioCodecRule, source: AudioStream, bitrate: int, note: str
) -> None:
    defaults = rules(rule, passthru=PassthruPolicy(allowed=[]))
    track, decision = run(source, defaults)
    assert track.bitrate == bitrate
    assert decision.notes == [note]


def test_the_source_bitrate_snaps_up_but_not_above_the_max() -> None:
    policy = PassthruPolicy(allowed=["ac3"])
    # MP3 200 kb/s, MP3 passthru off: the next AC-3 step is 224.
    track, decision = run(
        stream("mp3", 2, 200, display_codec="MP3"),
        rules(AudioCodecRule(codec="ac3", mixdown="stereo", max_bitrate=320), passthru=policy),
    )
    assert track.bitrate == 224
    assert decision.notes == ["200 kb/s is not an allowed AC-3 Stereo bit rate: 200 → 224 kb/s"]
    # 290 ≤ 300, but the next step (320) is above the max: the snapped max (256) wins.
    track, decision = run(
        stream("mp3", 2, 290, display_codec="MP3"),
        rules(AudioCodecRule(codec="ac3", mixdown="stereo", max_bitrate=300), passthru=policy),
    )
    assert track.bitrate == 256
    assert decision.reason == "290 ≤ 300, but MP3 passthru is not allowed → encode at the max"
    # Below the encoder's minimum: the minimum, with a note.
    track, decision = run(
        stream("mp3", 2, 64, display_codec="MP3"),
        rules(AudioCodecRule(codec="ac3", mixdown="stereo", max_bitrate=320), passthru=policy),
    )
    assert track.bitrate == 96
    assert decision.notes == ["AC-3 Stereo needs at least 96 kb/s: 64 → 96 kb/s"]


def test_no_max_uses_the_encoder_default() -> None:
    """A rule without a max (meant for lossless encoders) encodes a lossy codec at the
    encoder's default for the layout, still never above the source."""
    no_passthru = PassthruPolicy(allowed=[])
    track, decision = run(
        stream("dts", 6, 1509, display_codec="DTS"),
        rules(AudioCodecRule(codec="aac", max_bitrate=None), passthru=no_passthru),
    )
    assert track.bitrate == 384  # AAC 5.1 default
    assert decision.reason == "DTS passthru is not allowed, 1509 > 384 → encode at the default"
    track, decision = run(
        stream("ac3", 2, 128, display_codec="AC-3"),
        rules(AudioCodecRule(codec="aac", max_bitrate=None), passthru=no_passthru),
    )
    assert track.bitrate == 128


#: (source, (action, encoder, mixdown, bitrate), reason, measure) for a lossy rule without a
#: max: the encoder's default for the layout is the max (0019 item 5), and a lossless source
#: fits only with a known bit rate at or below it (0023).
NO_MAX_LOSSLESS = [
    (
        stream("flac", 2, 160, display_codec="FLAC", lossless=True),
        ("passthru", "aac", None, None),
        "FLAC, 2.0, 160 ≤ 160 (the default): passthru",
        False,
    ),
    (
        stream("flac", 2, 900, display_codec="FLAC", lossless=True),
        ("encode", "aac", None, 160),
        "Lossless source → encode at the default",
        False,
    ),
    (
        stream("flac", 2, None, display_codec="FLAC", lossless=True),
        ("encode", "aac", None, 160),
        "Lossless source → encode at the default",
        True,
    ),
    (
        stream("truehd", 6, 3912, display_codec="TrueHD", lossless=True),
        ("encode", "aac", None, 384),
        "Lossless source → encode at the default",
        False,
    ),
    (
        stream("truehd", 8, None, display_codec="TrueHD", lossless=True),
        ("encode", "aac", "5.1", 384),
        "Downmix 7.1 → 5.1. Lossless source → encode at the default",
        True,
    ),
]


@pytest.mark.parametrize(("source", "expected", "reason", "measure"), NO_MAX_LOSSLESS)
def test_no_max_is_the_default_for_a_lossless_source(
    source: AudioStream,
    expected: tuple[str, str | None, str | None, int | None],
    reason: str,
    measure: bool,
) -> None:
    """A lossy rule without a max does not pass every lossless source through: the
    encoder's default for the output layout is the max it is compared with."""
    rule = AudioCodecRule(codec="aac", mixdown="up_to_5.1", max_bitrate=None)
    track, decision = run(source, rules(rule))
    assert summary(track) == expected
    assert decision.reason == reason
    assert decision.measure is measure


def test_no_max_keeps_a_lossy_source_and_a_passthru_rule_unlimited() -> None:
    """Unchanged by the default: a lossy source fits at any bit rate (0023), and a
    ``passthru`` rule without a max passes anything that fits (0019 consequences)."""
    aac = AudioCodecRule(codec="aac", mixdown="up_to_5.1", max_bitrate=None)
    track, decision = run(stream("ac3", 6, 640, display_codec="AC-3"), rules(aac))
    assert (track.action, decision.reason) == ("passthru", "AC-3, 5.1: passthru")
    keep = AudioCodecRule(codec="passthru", mixdown="keep", max_bitrate=None)
    truehd = stream("truehd", 8, 3912, display_codec="TrueHD", lossless=True)
    track, decision = run(truehd, rules(keep))
    assert (track.action, decision.reason) == ("passthru", "TrueHD, 7.1: passthru")
    # A lossless rule encoder (FLAC) has no default bit rate: no max stays no max.
    flac = AudioCodecRule(codec="flac", mixdown="keep", max_bitrate=None)
    assert run(truehd, rules(flac))[0].action == "passthru"


# --------------------------------------------------------------------------- passthru


@pytest.mark.parametrize(
    ("codec", "profile", "expected"),
    [
        ("ac3", None, "ac3"),
        ("eac3", "Dolby Digital Plus + Dolby Atmos", "eac3"),
        ("dts", "DTS", "dts"),
        ("dts", None, "dts"),
        ("dts", "DTS-ES", "dts"),
        ("dts", "DTS-HD MA", "dtshd"),
        ("dts", "DTS-HD HRA", "dtshd"),
        ("dts", "DTS-HD MA + DTS:X", "dtshd"),
        ("dts", "DTS Express", None),
        ("truehd", "Dolby TrueHD + Dolby Atmos", "truehd"),
        ("aac", "LC", "aac"),
        ("mp3", None, "mp3"),
        ("flac", None, "flac"),
        ("opus", None, "opus"),
        ("pcm_s24le", None, None),
    ],
)
def test_passthru_codec(codec: str, profile: str | None, expected: str | None) -> None:
    assert passthru_codec(stream(codec, 2, 100, profile=profile), DEFS) == expected


def test_passthru_policy_and_container() -> None:
    dts_hd = stream("dts", 6, 2104, profile="DTS-HD MA", display_codec="DTS-HD MA", lossless=False)
    passthru_rule = AudioCodecRule(codec="passthru", mixdown="keep", max_bitrate=None)
    defaults = rules(passthru_rule)
    # Allowed, and the container holds it: passthru (no max: the bit rate does not matter).
    track, decision = run(dts_hd, defaults)
    assert summary(track) == ("passthru", "aac", None, None)
    assert decision.reason == "DTS-HD, 5.1: passthru"
    # MP4 holds DTS (C-6, testdata/README.md "Containers").
    assert run(dts_hd, defaults, "mp4")[0].action == "passthru"
    # WebM does not: the fallback encoder.
    track, decision = run(dts_hd, defaults, "webm")
    assert summary(track) == ("encode", "aac", None, 384)
    assert decision.reason == (
        "WebM cannot hold DTS-HD MA → fallback encoder AAC. 2104 > 384 → encode at the default"
    )
    assert decision.notes == ["WebM cannot hold AAC"]
    # DTS-HD not allowed: the fallback encoder from the policy.
    policy = PassthruPolicy(allowed=["ac3", "dts"], fallback_encoder="ac3")
    track, decision = run(dts_hd, rules(passthru_rule, passthru=policy))
    assert summary(track) == ("encode", "ac3", None, 640)
    assert decision.reason == (
        "DTS-HD passthru is not allowed → fallback encoder AC-3. 2104 > 640 → encode at the default"
    )
    # A passthru rule with a max: a lossy source passes at any bit rate (decision 0023) …
    capped = AudioCodecRule(codec="passthru", mixdown="keep", max_bitrate=640)
    track, decision = run(stream("ac3", 6, None, display_codec="AC-3"), rules(capped))
    assert summary(track) == ("passthru", "aac", None, None)
    assert decision.reason == "AC-3, 5.1: passthru"
    assert not decision.measure
    # … a lossless one with an unknown bit rate is encoded with the fallback at the max.
    track, decision = run(stream("truehd", 6, None, lossless=True), rules(capped))
    assert summary(track) == ("encode", "aac", None, 640)
    assert decision.reason == "Fallback encoder AAC. Lossless source → encode at the max"
    assert decision.measure


def test_truehd_passthru_into_mp4() -> None:
    """MP4 can hold TrueHD (with ``-strict -2``, C-7's ``copy_args``): passthru is allowed."""
    truehd = stream("truehd", 8, 3912, display_codec="TrueHD Atmos", lossless=True)
    keep = AudioCodecRule(codec="passthru", mixdown="keep", max_bitrate=None)
    assert run(truehd, rules(keep), "mp4")[0].action == "passthru"
    assert run(truehd, rules(keep), "webm")[0].action == "encode"


# --------------------------------------------------------------------------- mixdown

MIXDOWN_TABLE: list[tuple[RuleMixdown, int, str | None]] = [
    ("keep", 8, None),
    ("up_to_5.1", 8, "5.1"),
    ("up_to_5.1", 6, None),
    ("up_to_5.1", 2, None),
    ("5.1", 8, "5.1"),
    ("5.1", 6, "5.1"),
    ("5.1", 5, None),
    ("stereo", 6, "stereo"),
    ("stereo", 2, "stereo"),
    ("stereo", 1, None),
    ("dpl2", 6, "dpl2"),
    ("dpl2", 2, None),
    ("mono", 2, "mono"),
    ("mono", 1, "mono"),
    ("stereo", 0, "stereo"),
    ("keep", 0, None),
]


@pytest.mark.parametrize(("mixdown", "channels", "expected"), MIXDOWN_TABLE)
def test_requested_mixdown(mixdown: RuleMixdown, channels: int, expected: str | None) -> None:
    assert requested_mixdown(mixdown, channels, DEFS) == expected


def test_mixdown_in_the_output() -> None:
    no_passthru = PassthruPolicy(allowed=[])
    truehd = stream("truehd", 8, None, display_codec="TrueHD", lossless=True)
    # keep: the encoder keeps 7.1 when it can …
    track, _ = run(truehd, rules(AudioCodecRule(codec="libopus", mixdown="keep", max_bitrate=512)))
    assert (track.mixdown, track.bitrate) == (None, 512)
    # … and makes its largest layout when it cannot (AC-3 has no 7.1).
    track, decision = run(
        truehd, rules(AudioCodecRule(codec="ac3", mixdown="keep", max_bitrate=640))
    )
    assert (track.mixdown, track.bitrate) == ("5.1", 640)
    assert decision.notes == ["AC-3 cannot make 7.1: 5.1"]
    assert decision.reason == "Downmix 7.1 → 5.1. Lossless source → encode at the max"
    # MP3 has no 5.1: stereo.
    track, decision = run(
        stream("ac3", 6, 640),
        rules(
            AudioCodecRule(codec="libmp3lame", mixdown="5.1", max_bitrate=320),
            passthru=no_passthru,
        ),
    )
    assert (track.mixdown, track.bitrate) == ("stereo", 320)
    assert decision.notes == ["MP3 cannot make 5.1: Stereo"]
    # dpl2 downmixes 5.1 with matrix encoding.
    track, decision = run(
        stream("dts", 6, 1509, display_codec="DTS"),
        rules(AudioCodecRule(codec="aac", mixdown="dpl2", max_bitrate=160), passthru=no_passthru),
    )
    assert (track.mixdown, track.bitrate) == ("dpl2", 160)
    assert decision.reason == (
        "Downmix 5.1 → Dolby Pro Logic II. DTS passthru is not allowed, 1509 > 160 → encode at"
        " the max"
    )
    # mono.
    track, decision = run(
        stream("ac3", 2, 192), rules(AudioCodecRule(codec="aac", mixdown="mono", max_bitrate=96))
    )
    assert (track.mixdown, track.bitrate) == ("mono", 96)
    assert decision.reason == (
        "Downmix 2.0 → Mono. 2.0 is more than Mono, 192 > 96 → encode at the max"
    )


def test_no_upmix() -> None:
    """Decision 0019: a stereo source with a 5.1 rule stays stereo (FFmpeg's upmix only adds
    silent channels, testdata/README.md "Audio codec rules")."""
    track, decision = run(
        stream("pcm_s16le", 2, 1536, display_codec="PCM", lossless=True),
        rules(AudioCodecRule(codec="ac3", mixdown="5.1", max_bitrate=448)),
    )
    assert (track.mixdown, track.bitrate) == (None, 448)
    assert decision.notes == ["2.0 source: no upmix to 5.1"]
    # Its bit rate table is the source layout's: AC-3 stereo.
    track, _ = run(
        stream("pcm_s16le", 2, 1536, display_codec="PCM", lossless=True),
        rules(AudioCodecRule(codec="ac3", mixdown="5.1", max_bitrate=1000)),
    )
    assert track.bitrate == 640


def test_channels_within_the_mixdown() -> None:
    """Passthru needs the source's channels within the mixdown: 7.1 E-AC-3 does not fit an
    up-to-5.1 rule; a stereo AC-3 fits a 5.1 rule (no upmix is needed for passthru)."""
    rule = AudioCodecRule(codec="eac3", mixdown="up_to_5.1", max_bitrate=1536)
    track, decision = run(stream("eac3", 8, 1024, display_codec="E-AC-3"), rules(rule))
    assert summary(track) == ("encode", "eac3", "5.1", 1152)
    assert decision.reason == (
        "Downmix 7.1 → 5.1. 1024 ≤ 1536, but 7.1 is more than 5.1 → encode at 1152 kb/s, the"
        " smallest allowed value ≥ 1024"
    )
    track, _ = run(
        stream("ac3", 2, 192), rules(AudioCodecRule(codec="ac3", mixdown="5.1", max_bitrate=448))
    )
    assert track.action == "passthru"


# --------------------------------------------------------------------------- matching


@pytest.mark.parametrize(
    ("condition", "channels", "expected"),
    [
        ("any", 0, True),
        ("mono", 1, True),
        ("mono", 2, False),
        ("stereo_or_less", 2, True),
        ("stereo_or_less", 3, False),
        ("5.1_or_more", 5, False),
        ("5.1_or_more", 6, True),
        ("7.1_or_more", 6, False),
        ("7.1_or_more", 8, True),
        ("mono", 0, False),
    ],
)
def test_channels_match(condition: SourceChannels, channels: int, expected: bool) -> None:
    assert channels_match(condition, channels) is expected


@pytest.mark.parametrize(
    ("rule", "language", "ietf", "expected"),
    [
        (None, None, None, True),
        (["hu"], "hun", None, True),
        (["hu", "en"], "eng", None, True),
        (["hu"], "eng", None, False),
        (["pt"], "por", "pt-BR", True),
        (["pt-BR"], "por", None, False),
        (["pt-BR"], "por", "pt-BR", True),
        (["de"], "ger", None, True),
        (["hu"], None, None, False),
        (["und"], None, None, True),
    ],
)
def test_language_matches(
    rule: list[str] | None, language: str | None, ietf: str | None, expected: bool
) -> None:
    source = stream("ac3", 2, 192, language=language, language_ietf=ietf)
    assert language_matches(rule, source) is expected


def test_first_match_wins_and_language_misses_are_not_explained() -> None:
    defaults = rules(
        AudioCodecRule(languages=["hu"], codec="ac3", mixdown="5.1", max_bitrate=320),
        AudioCodecRule(languages=["en"], codec="ac3", mixdown="5.1", max_bitrate=384),
        AudioCodecRule(languages=["en"], codec="ac3", mixdown="5.1", max_bitrate=448),
    )
    _, decision = run(stream("dts", 6, 1509), defaults)
    assert (decision.rule, decision.reason) == (
        2,
        "DTS, 5.1, 1509 > 384: passthru (a lossy source is kept above the max)",
    )
    _, decision = run(stream("dts", 6, 1509, language="ger"), defaults)
    assert decision.rule == 4  # the catch-all


# --------------------------------------------------------------------------- extras


def test_extras_go_to_the_output_and_block_passthru() -> None:
    extras = AudioRuleExtras(samplerate=48000, gain=-3.0, drc=2.0, loudness="ebu_r128")
    rule = AudioCodecRule(codec="aac", mixdown="stereo", max_bitrate=160, extras=extras)
    track, decision = run(
        stream("aac", 2, 128, display_codec="AAC-LC", sample_rate=48000), rules(rule)
    )
    assert summary(track) == ("encode", "aac", "stereo", 128)
    assert (track.samplerate, track.gain, track.drc, track.loudness) == (
        48000,
        -3.0,
        2.0,
        "ebu_r128",
    )
    assert decision.reason == (
        "128 ≤ 160, but the rule changes the gain → encode at 128 kb/s, the smallest allowed"
        " value ≥ 128"
    )


@pytest.mark.parametrize(
    ("extras", "why"),
    [
        (AudioRuleExtras(drc=1.0), "the rule applies DRC"),
        (AudioRuleExtras(loudness="streaming"), "the rule normalises the loudness"),
        (AudioRuleExtras(samplerate=44100), "the rule resamples to 44100 Hz"),
    ],
)
def test_each_extra_needs_a_decode(extras: AudioRuleExtras, why: str) -> None:
    rule = AudioCodecRule(codec="aac", mixdown="stereo", max_bitrate=160, extras=extras)
    track, decision = run(stream("aac", 2, 128, sample_rate=48000), rules(rule))
    assert track.action == "encode"
    assert f"but {why} →" in decision.reason
    # The source's own sample rate is no change.
    same = AudioRuleExtras(samplerate=48000)
    rule = AudioCodecRule(codec="aac", mixdown="stereo", max_bitrate=160, extras=same)
    assert run(stream("aac", 2, 128, sample_rate=48000), rules(rule))[0].action == "passthru"


def test_sample_rate_snaps_to_the_encoder() -> None:
    extras = AudioRuleExtras(samplerate=44100)
    rule = AudioCodecRule(codec="libopus", mixdown="stereo", max_bitrate=128, extras=extras)
    track, decision = run(stream("flac", 2, None, lossless=True), rules(rule))
    assert track.samplerate == 48000
    assert decision.notes == ["Opus has no 44100 Hz: 48000 Hz"]


@pytest.mark.parametrize(
    ("encoder", "source_rate", "expected", "notes"),
    [
        # The source's own rate stays "same as source" when the encoder takes it …
        ("aac", 44100, None, []),
        ("ac3", None, None, []),
        # … and becomes the snapped rate (C-6's ``snap_samplerate``) when it does not: the
        # rate the command builder writes with ``-ar`` (an AC-3 ``-ar 22050`` fails).
        ("libopus", 44100, 48000, ["Opus has no 44100 Hz (the source's rate): 48000 Hz"]),
        ("ac3", 22050, 32000, ["AC-3 has no 22050 Hz (the source's rate): 32000 Hz"]),
    ],
)
def test_the_source_sample_rate_snaps_to_the_encoder(
    encoder: str, source_rate: int | None, expected: int | None, notes: list[str]
) -> None:
    """Decision 0024: a source rate the encoder cannot write is snapped, with a note."""
    rule = AudioCodecRule(codec=encoder, mixdown="stereo", max_bitrate=128)
    source = stream("flac", 2, None, lossless=True, sample_rate=source_rate)
    track, decision = run(source, rules(rule))
    assert track.samplerate == expected
    assert decision.notes == notes
    # The rate written is the shared helper's answer.
    enc = DEFS.audio_encoders[encoder]
    assert (track.samplerate or source_rate) == enc.snap_samplerate(None, source_rate)


# --------------------------------------------------------------------------- shared helpers

_RULE_MIXDOWNS: list[RuleMixdown] = ["keep", "up_to_5.1", "5.1", "stereo", "dpl2", "mono"]

#: One encoder of each kind of layouts, bit rates and sample rates: eac3 has ac3's, and
#: libfdk_aac has aac's.
_ENCODER_KINDS = ["aac", "ac3", "flac", "libmp3lame", "libopus"]


@pytest.mark.parametrize("encoder", _ENCODER_KINDS)
@pytest.mark.parametrize("channels", [0, 1, 2, 3, 6, 7, 8])
@pytest.mark.parametrize("mixdown", _RULE_MIXDOWNS)
def test_the_output_agrees_with_the_shared_helpers(
    encoder: str, channels: int, mixdown: RuleMixdown
) -> None:
    """Decision 0024: the layout, bit rate and sample rate C-12 writes are C-6's
    ``snap_mixdown``, ``channels_mixdown``, ``AudioBitrateDef.snap`` and ``snap_samplerate``,
    the helpers that C-7 and C-8 use."""
    enc = DEFS.audio_encoders[encoder]
    rule = AudioCodecRule(codec=encoder, mixdown=mixdown, max_bitrate=700)
    source = stream("pcm_s16le", channels, None, lossless=True, sample_rate=44100)
    track, _ = run(source, rules(rule, passthru=PassthruPolicy(allowed=[])))
    wanted = requested_mixdown(mixdown, channels, DEFS)
    assert track.mixdown == enc.snap_mixdown(wanted, channels, DEFS.mixdowns)
    # Never an upmix of a known source.
    if track.mixdown is not None and channels > 0:
        assert DEFS.mixdowns[track.mixdown].channels <= channels
    # The rule's no-upmix rule is the helper's; only ``up_to_5.1`` keeps a 5.1 source's
    # own layout (decision 0019 item 3).
    target: Mixdown | None = (
        None if mixdown == "keep" else "5.1" if mixdown == "up_to_5.1" else mixdown
    )
    if mixdown != "up_to_5.1" or channels != 6:
        assert track.mixdown == enc.snap_mixdown(target, channels, DEFS.mixdowns)
    if enc.bitrate is None:
        assert track.bitrate is None
    else:
        key = track.mixdown if track.mixdown is not None else channels_mixdown(channels)
        assert track.bitrate == enc.bitrate.snap(700, key, "down")
    assert (track.samplerate or 44100) == enc.snap_samplerate(None, 44100)


#: (source channels, source layout, max, (mixdown, bitrate), reason, notes) for an Opus
#: "keep" rule on a lossless source: libopus refuses some layouts, and the command builder
#: (C-7's ``planned_audio``) downmixes them to one it takes, with the bitrate table of the
#: written channels.
OPUS_LAYOUTS = [
    (
        3, "2.1", 13, (None, 13),
        "Downmix 2.1 → 2.0. Lossless source → encode at the max",
        ["Opus cannot take 2.1: 2.0"],
    ),
    (
        3, "3.0(back)", 13, (None, 13),
        "Downmix 3.0 → 2.0. Lossless source → encode at the max",
        ["Opus cannot take 3.0(back): 2.0"],
    ),
    (
        8, "7.1(wide)", 37, (None, 37),
        "Downmix 7.1 → 5.1. Lossless source → encode at the max",
        ["Opus cannot take 7.1(wide): 5.1"],
    ),
    (
        6, "6.0", 600, (None, 600),
        "Downmix 6.0 → 5.0. Lossless source → encode at the max",
        ["Opus cannot take 6.0: 5.0"],
    ),
    # A lossless relabel is no downmix: 5.1(side) is written as 5.1.
    (
        6, "5.1(side)", 600, (None, 600),
        "Lossless source → encode at the max",
        [],
    ),
]  # fmt: skip


@pytest.mark.parametrize(
    ("channels", "layout", "max_bitrate", "expected", "reason", "notes"), OPUS_LAYOUTS
)
def test_the_bitrate_table_is_the_written_layout(
    channels: int,
    layout: str,
    max_bitrate: int,
    expected: tuple[str | None, int],
    reason: str,
    notes: list[str],
) -> None:
    rule = AudioCodecRule(codec="libopus", mixdown="keep", max_bitrate=max_bitrate)
    rule = rule.model_copy(update={"if_fits": "reencode"})
    source = stream("pcm_s16le", channels, None, lossless=True, channel_layout=layout)
    track, decision = run(source, rules(rule))
    assert (track.mixdown, track.bitrate) == expected
    assert decision.reason == reason
    assert decision.notes == notes
    planned = planned_audio(track, source, "mkv")
    assert (planned.bitrate, planned.mixdown) == (track.bitrate, track.mixdown)


def test_an_encoder_without_a_small_enough_layout_keeps_the_source() -> None:
    """``snap_mixdown`` never upmixes, also when the encoder has nothing that small (the
    note names the kept source layout)."""
    aac = DEFS.audio_encoders["aac"].model_copy(update={"mixdowns": ["stereo", "5.1"]})
    defs = DEFS.model_copy(update={"audio_encoders": {**DEFS.audio_encoders, "aac": aac}})
    rule = AudioCodecRule(codec="aac", mixdown="mono", max_bitrate=96)
    mono = stream("pcm_s16le", 1, None, lossless=True)
    track, decision = run(mono, rules(rule), definitions=defs)
    assert (track.mixdown, track.bitrate) == (None, 96)
    assert decision.notes == ["AAC cannot make Mono: 1.0"]
    # An unknown channel count gets the encoder's smallest layout.
    unknown = stream("pcm_s16le", 0, None, lossless=True)
    track, decision = run(unknown, rules(rule), definitions=defs)
    assert track.mixdown == "stereo"
    assert decision.notes == ["AAC cannot make Mono: Stereo"]


def test_name_template() -> None:
    extras = AudioRuleExtras(name_template="{lang_native} {channels}")
    rule = AudioCodecRule(
        languages=["hu"], codec="ac3", mixdown="5.1", max_bitrate=320, extras=extras
    )
    track, _ = run(stream("dts", 6, 1509, language="hun", title="DTS 5.1"), rules(rule))
    assert track.metadata.name == "Magyar 5.1"
    full = AudioRuleExtras(name_template="{lang_name} {channels} {codec}< {bitrate} kb/s>")
    rule = AudioCodecRule(codec="libopus", mixdown="stereo", max_bitrate=128, extras=full)
    track, _ = run(stream("truehd", 8, None, language="jpn", lossless=True), rules(rule))
    assert track.metadata.name == "Japanese 2.0 Opus 128 kb/s"
    # Passthru: the source codec and layout; the empty bit rate drops its group.
    rule = AudioCodecRule(codec="aac", max_bitrate=640, extras=full)
    track, _ = run(stream("ac3", 6, 448, display_codec="AC-3"), rules(rule))
    assert (track.action, track.metadata.name) == ("passthru", "English 5.1 AC-3")
    assert render_track_name(
        "{title} / {source_codec:upper}", {"title": "Main", "source_codec": "dts"}
    ) == ("Main / DTS")


def test_metadata_from_the_source() -> None:
    flags = Disposition(
        default=True,
        forced=True,
        comment=True,
        hearing_impaired=True,
        visual_impaired=True,
        original=True,
        dub=True,
    )
    track, _ = run(
        stream("ac3", 2, 192, language="ger", title="Kommentar", disposition=flags),
        rules(AudioCodecRule(codec="aac", max_bitrate=160)),
    )
    m = track.metadata
    assert (m.language, m.name) == ("de", "Kommentar")
    assert (
        m.default,
        m.forced,
        m.commentary,
        m.hearing_impaired,
        m.visual_impaired,
        m.original,
    ) == (True, True, True, True, True, True)
    # No language, no title.
    track, _ = run(stream("ac3", 2, 192, language=None), rules())
    assert (track.metadata.language, track.metadata.name) == (None, None)


def test_extra_outputs() -> None:
    extras = AudioRuleExtras(
        name_template="{lang_name} {channels} {codec}",
        extra_outputs=[
            ExtraAudioOutput(codec="aac", mixdown="stereo", bitrate=160),
            ExtraAudioOutput(codec="passthru", mixdown="keep"),
        ],
    )
    rule = AudioCodecRule(
        codec="ac3", mixdown="5.1", max_bitrate=640, if_fits="reencode", extras=extras
    )
    source = stream("dts", 6, 1509, display_codec="DTS", disposition=Disposition(default=True))
    outputs, decision = apply_codec_rules(source, rules(rule), "mkv")
    assert [summary(t) for t in outputs] == [
        ("encode", "ac3", "5.1", 640),
        ("encode", "aac", "stereo", 160),
        ("passthru", "aac", None, None),
    ]
    assert [t.metadata.name for t in outputs] == [
        "English 5.1 AC-3",
        "English 2.0 AAC",
        "English 5.1 DTS",
    ]
    assert [t.metadata.default for t in outputs] == [True, False, False]
    assert {t.source_stream for t in outputs} == {1}
    assert decision.reason == "The rule says re-encode, 1509 > 640 → encode at the max"
    assert decision.notes == [
        "Extra output 1: AAC Stereo · 160 kb/s (Downmix 5.1 → Stereo. The rule says re-encode,"
        " 1509 > 160 → encode at the max)",
        "Extra output 2: Passthru (DTS, 5.1: passthru)",
    ]
    # An extra output is always encoded, never above the source.
    extras = AudioRuleExtras(extra_outputs=[ExtraAudioOutput(codec="aac", bitrate=256)])
    rule = AudioCodecRule(codec="ac3", mixdown="5.1", max_bitrate=640, extras=extras)
    outputs, _ = apply_codec_rules(stream("aac", 2, 128), rules(rule), "mkv")
    assert [summary(t) for t in outputs] == [
        ("passthru", "ac3", None, None),
        ("encode", "aac", "stereo", 128),
    ]


def test_first_track_of_language_only() -> None:
    """M2: ``first_of_language`` comes from the draft (first in source order)."""
    first_only = AudioRuleExtras(first_track_of_language_only=True)
    defaults = rules(
        AudioCodecRule(
            languages=["en"], codec="ac3", mixdown="5.1", max_bitrate=448, extras=first_only
        ),
        AudioCodecRule(codec="aac", mixdown="stereo", max_bitrate=96),
    )
    source = stream("dts", 6, 1509)
    _, decision = run(source, defaults)
    assert decision.rule == 1
    _, decision = run(source, defaults, first_of_language=False)
    assert decision.rule == 2
    assert decision.reason == (
        "Rule 1 is only for the first track of a language. Rule 2 matches. Downmix 5.1 → Stereo."
        " 5.1 is more than Stereo, 1509 > 96 → encode at the max"
    )


def test_no_rule_matches() -> None:
    """Only when the catch-all is limited to the first track of a language: data, no output."""
    first_only = AudioRuleExtras(first_track_of_language_only=True)
    defaults = AudioDefaults(codec_rules=[AudioCodecRule(codec="aac", extras=first_only)])
    outputs, decision = apply_codec_rules(
        stream("ac3", 2, 192), defaults, "mkv", first_of_language=False
    )
    assert outputs == []
    assert decision.rule is None
    assert decision.outputs == []
    assert decision.reason == (
        "Rule 1 is only for the first track of a language. No codec rule matches: the track is"
        " not encoded"
    )


# --------------------------------------------------------------------------- odd inputs


def test_encoder_problems_are_notes() -> None:
    no_passthru = PassthruPolicy(allowed=[])
    track, decision = run(
        stream("dts", 6, 1509),
        rules(AudioCodecRule(codec="nosuch", max_bitrate=300), passthru=no_passthru),
    )
    assert summary(track) == ("encode", "nosuch", None, 300)
    assert decision.reason == "Encode to nosuch"
    assert decision.notes == ["Unknown audio encoder 'nosuch': its bit rates are not checked"]
    # AC-3 cannot go into WebM: validation reports it, the draft still names it.
    track, decision = run(stream("dts", 6, 1509), rules(AC3_51_448), "webm")
    assert summary(track) == ("encode", "ac3", "5.1", 448)
    assert decision.notes == ["WebM cannot hold AC-3"]


def test_lossless_encoder() -> None:
    flac = AudioCodecRule(codec="flac", mixdown="keep", max_bitrate=None, if_fits="reencode")
    track, decision = run(stream("truehd", 8, 3912, lossless=True), rules(flac))
    assert summary(track) == ("encode", "flac", None, None)
    assert decision.reason == "The rule says re-encode: encode to FLAC (lossless)"
    # DTS-HD not allowed: FLAC.
    flac = flac.model_copy(update={"if_fits": "passthru"})
    track, decision = run(
        stream("dts", 6, 2104, profile="DTS-HD MA", display_codec="DTS-HD MA", lossless=True),
        rules(flac, passthru=PassthruPolicy(allowed=["ac3"])),
    )
    assert summary(track) == ("encode", "flac", None, None)
    assert decision.reason == "DTS-HD passthru is not allowed: encode to FLAC (lossless)"


def test_unknown_channels_and_codec() -> None:
    source = AudioStream(index=3, channels=0)
    track, decision = run(
        source, rules(AudioCodecRule(codec="aac", mixdown="stereo", max_bitrate=128))
    )
    assert summary(track) == ("encode", "aac", "stereo", 128)
    assert decision.reason == (
        "Unknown codec cannot be passed through. Bitrate unknown: treated as above the max; Measure"
    )
    # Unknown channels: the rule's layout (the catch-all of a new preset: up to 5.1).
    track, _ = run(source, rules())
    assert (track.mixdown, track.bitrate) == ("5.1", 256)
