"""Audio and subtitle output tracks, track metadata, chapters, tags, job type."""

from __future__ import annotations

import itertools
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from reframe.command import PlanError, PlannedAudio, job_type, planned_audio
from reframe.command.audio import ENCODER_LAYOUTS, LOUDNESS, audio_output, layout_channels
from reframe.command.metadata import (
    ChapterPlan,
    OutputTrack,
    chapter_plan,
    chapter_range,
    container_language,
    dispositions,
    ffmetadata,
    needs_ietf,
    render_tag,
    tag_args,
)
from reframe.command.subtitles import plan_subtitles
from reframe.definitions import channels_mixdown, load_definitions
from reframe.models import (
    ArgTemplate,
    AudioOutputTrack,
    AudioStream,
    Chapter,
    ChapterRange,
    ChapterSettings,
    ExternalSubtitle,
    NamingOptions,
    SubtitleOutputTrack,
    TagSettings,
    TrackMetadata,
    ValueRef,
)

from .conftest import draft, recorded

DEFS = load_definitions()
MKV, MP4, WEBM = DEFS.containers["mkv"], DEFS.containers["mp4"], DEFS.containers["webm"]


def audio(**kwargs: Any) -> AudioStream:
    return AudioStream.model_validate({"index": 1, "codec": "ac3", "channels": 6, **kwargs})


def planned(encoder: str, stream: AudioStream, **track: Any) -> PlannedAudio:
    output = AudioOutputTrack.model_validate({"encoder": encoder, **track})
    return planned_audio(output, stream, "mkv", definitions=DEFS)


@pytest.mark.parametrize(
    ("encoder", "channels", "mixdown", "expected", "table"),
    [
        # A layout the encoder cannot make: its largest layout below.
        ("ac3", 8, "7.1", "5.1", "5.1"),
        ("libmp3lame", 6, "5.1", "stereo", "stereo"),
        ("ac3", 8, None, "5.1", "5.1"),
        # Never an upmix: the source layout stays.
        ("ac3", 6, "7.1", None, "5.1"),
        ("aac", 2, "5.1", None, "stereo"),
        ("libopus", 1, "stereo", None, "mono"),
        ("aac", 5, "5.1", None, "5.1"),
        ("aac", 2, "dpl2", None, "stereo"),
        ("aac", 6, "dpl2", "dpl2", "dpl2"),
        # A layout the encoder makes, from at least as many channels; keep.
        ("aac", 8, "5.1", "5.1", "5.1"),
        ("libopus", 8, "7.1", "7.1", "7.1"),
        ("aac", 8, None, None, "7.1"),
        ("aac", 3, None, None, "5.1"),
        # Unknown channels: the request stands, snapped to the encoder; keep = stereo table.
        ("ac3", 0, "7.1", "5.1", "5.1"),
        ("aac", 0, None, None, "stereo"),
    ],
)  # fmt: skip
def test_mixdown_is_snapped(
    encoder: str, channels: int, mixdown: str | None, expected: str | None, table: str
) -> None:
    got = planned(encoder, audio(channels=channels), mixdown=mixdown)
    assert (got.mixdown, got.bitrate_mixdown) == (expected, table)


@pytest.mark.parametrize(
    ("encoder", "channels", "settings", "expected"),
    [
        ("ac3", 6, {"bitrate": 700}, 640),  # above the max
        ("ac3", 6, {"bitrate": 100}, 224),  # below the 5.1 minimum
        ("ac3", 2, {"bitrate": 150}, 128),  # between two steps: down, as HandBrake
        ("ac3", 8, {"mixdown": "7.1", "bitrate": 700}, 640),  # in the 5.1 table
        ("libmp3lame", 6, {"bitrate": 330}, 320),
        ("aac", 2, {"mixdown": "5.1", "bitrate": 700}, 512),  # stereo table: no upmix
        ("libopus", 2, {"bitrate": 600}, 512),
        # No bitrate, no quality: the default of the effective mixdown.
        ("aac", 2, {"mixdown": "5.1"}, 160),
        ("ac3", 8, {"mixdown": "7.1"}, 640),
        ("libopus", 6, {}, 320),
        ("aac", 0, {}, 160),
        # A VBR quality instead; an encoder without one gets its default bitrate.
        ("libmp3lame", 2, {"quality": 4.5}, None),
        ("ac3", 2, {"quality": 3}, 224),
        ("flac", 6, {"bitrate": 700}, None),  # lossless: no bitrate
    ],
)  # fmt: skip
def test_bitrate_is_snapped_for_the_effective_mixdown(
    encoder: str, channels: int, settings: dict[str, Any], expected: int | None
) -> None:
    assert planned(encoder, audio(channels=channels), **settings).bitrate == expected


@pytest.mark.parametrize(
    ("encoder", "rate", "source_rate", "expected"),
    [
        ("ac3", 96000, 48000, 48000),  # ac3 refuses 96 kHz
        ("libopus", 44100, 48000, 48000),  # libopus refuses 44.1 kHz
        ("libopus", None, 44100, 48000),
        ("ac3", None, 22050, 32000),
        ("aac", None, 44100, 44100),
        ("libopus", 20000, None, 24000),  # a tie: the higher rate
        ("aac", None, None, None),
    ],
)  # fmt: skip
def test_samplerate_is_snapped(
    encoder: str, rate: int | None, source_rate: int | None, expected: int | None
) -> None:
    got = planned(encoder, audio(sample_rate=source_rate), samplerate=rate)
    assert got.samplerate == expected


def test_planned_audio_copies_and_containers() -> None:
    passthru = AudioOutputTrack(action="passthru", bitrate=700, mixdown="7.1", samplerate=96000)
    assert planned_audio(passthru, audio(), "mkv") == PlannedAudio(copy=True)  # never snapped
    passthru.encoder = "libopus"
    fallback = planned_audio(passthru, audio(sample_rate=44100), WEBM, definitions=DEFS)
    assert fallback == PlannedAudio(
        copy=False, encoder="libopus", fallback=True, mixdown=None, bitrate_mixdown="5.1",
        bitrate=700, samplerate=48000,
    )  # fmt: skip
    assert planned_audio(passthru, audio(sample_rate=44100), "webm") == fallback
    with pytest.raises(PlanError, match="unknown container"):
        planned_audio(passthru, audio(), "avi")  # type: ignore[arg-type]


def test_bitrate_without_a_table_for_the_layout() -> None:
    """Not the case for any defined encoder (the linter checks it): the track's bitrate is
    written as it is, and no default."""
    aac = DEFS.audio_encoders["aac"]
    assert aac.bitrate is not None
    stereo_only = aac.model_copy(
        update={
            "mixdowns": ["stereo"],
            "bitrate": aac.bitrate.model_copy(
                update={"by_mixdown": {"stereo": aac.bitrate.by_mixdown["stereo"]}}
            ),
        }
    )
    defs = DEFS.model_copy(update={"audio_encoders": {**DEFS.audio_encoders, "aac": stereo_only}})
    eight = audio(channels=8, channel_layout="7.1")
    given = planned_audio(AudioOutputTrack(bitrate=900), eight, "mkv", definitions=defs)
    assert given.bitrate == 900
    assert planned_audio(AudioOutputTrack(), eight, "mkv", definitions=defs).bitrate is None


_LAYOUTS = [
    (0, None), (1, "mono"), (2, "stereo"), (3, "2.1"), (3, "3.0(back)"), (5, "5.0"),
    (5, "5.0(side)"), (6, "5.1(side)"), (6, "6.0"), (8, "7.1"), (8, "7.1(wide)"),
]  # fmt: skip
_BITRATES = [None, 1, 150, 700, 10_000]
_RATES = [None, 8000, 22050, 44100, 96000]


def _argv_value(args: list[Any], option: str) -> str | None:
    texts = [str(a) for a in args]
    return texts[texts.index(option) + 1] if option in texts else None


def _check_written(
    track: AudioOutputTrack, stream: AudioStream, got: PlannedAudio, args: list[Any],
    written_filter: Any,
) -> None:  # fmt: skip
    encoder = DEFS.audio_encoders[str(track.encoder)]
    channels = stream.channels
    # The arguments are the planned values.
    assert _argv_value(args, "-b:a:0") == (f"{got.bitrate}k" if got.bitrate else None)
    assert _argv_value(args, "-ar:a:0") == str(got.samplerate)
    target = got.mixdown or got.bitrate_mixdown
    assert target is not None
    if got.layout is None:
        assert written_filter is None
    else:
        assert str(written_filter).endswith(f"out_chlayout={got.layout}")
    written = layout_channels(got.layout)
    out_channels = len(written) if written is not None else channels
    # The layout: one the encoder makes, never more channels than the source.
    if got.mixdown is not None:
        assert got.mixdown in encoder.mixdowns
        assert channels == 0 or DEFS.mixdowns[got.mixdown].channels <= channels
        assert got.mixdown != "dpl2" or channels == 0 or channels > 2
        assert got.layout in (None, DEFS.mixdowns[got.mixdown].layout)
    else:
        assert channels <= encoder.max_channels
        assert out_channels <= channels
        assert got.bitrate_mixdown == channels_mixdown(out_channels)
        accepted = ENCODER_LAYOUTS.get(encoder.id)
        if accepted is not None and stream.channel_layout is not None:
            assert (got.layout or stream.channel_layout) in accepted
        elif got.layout is not None:  # only a lossless relabel
            assert sorted(layout_channels(stream.channel_layout) or ()) != sorted(written or ())
            assert len(written or ()) == channels
    # The bitrate: in the table of the effective layout, on a step when there are steps.
    if encoder.bitrate is not None and got.bitrate is not None:
        limits = encoder.bitrate.by_mixdown[target]
        assert limits.min <= got.bitrate <= limits.max
        assert encoder.bitrate.allowed is None or got.bitrate in encoder.bitrate.allowed
    # The sample rate: one the encoder lists.
    assert got.samplerate in encoder.samplerates
    # A value the encoder can do is written as it is.
    if track.samplerate in encoder.samplerates:
        assert got.samplerate == track.samplerate
    if encoder.bitrate is not None and track.bitrate is not None:
        limits = encoder.bitrate.by_mixdown[target]
        steps = encoder.bitrate.allowed
        if limits.min <= track.bitrate <= limits.max and (steps is None or track.bitrate in steps):
            assert got.bitrate == track.bitrate
    wanted = track.mixdown
    if wanted in encoder.mixdowns and channels >= DEFS.mixdowns[wanted].channels:
        assert got.mixdown == (None if wanted == "dpl2" and channels <= 2 else wanted)


def test_every_written_value_is_one_the_encoder_can_do() -> None:
    """Every encoder, source layout, requested mixdown, bitrate and sample rate: the
    arguments say what :func:`planned_audio` says, and that is a layout, bitrate and sample
    rate the encoder can do, never an upmix."""
    combinations = itertools.product(
        DEFS.audio_encoders.values(), _LAYOUTS, [None, *DEFS.mixdowns], _BITRATES, _RATES
    )
    checked = 0
    for encoder, (channels, layout), mixdown, bitrate, rate in combinations:
        stream = audio(channels=channels, channel_layout=layout, sample_rate=48000)
        track = AudioOutputTrack.model_validate(
            {"encoder": encoder.id, "mixdown": mixdown, "bitrate": bitrate, "samplerate": rate}
        )
        got = planned_audio(track, stream, MKV, definitions=DEFS)
        out = audio_output(0, track, stream, MKV, DEFS)
        _check_written(track, stream, got, out.args, out.filter)
        checked += 1
    assert checked == len(DEFS.audio_encoders) * len(_LAYOUTS) * 6 * 5 * 5


def test_passthru_copies_or_falls_back() -> None:
    out = audio_output(0, AudioOutputTrack(action="passthru"), audio(codec="truehd"), MP4, DEFS)
    assert out.copy
    assert out.args == ["-c:a:0", "copy"]
    assert out.global_args == ["-strict", "-2"]
    # The default fallback is AAC, which WebM cannot hold.
    with pytest.raises(PlanError, match="cannot be written into WebM"):
        audio_output(2, AudioOutputTrack(action="passthru", encoder=None), audio(codec="dts"),
                     WEBM, DEFS)  # fmt: skip
    aac = audio_output(1, AudioOutputTrack(action="passthru", encoder=None),
                       audio(codec="vorbis"), MP4, DEFS)  # fmt: skip
    assert aac.fallback
    assert aac.args[:2] == ["-c:a:1", "aac"]


def test_encode_arguments() -> None:
    with pytest.raises(PlanError, match="unknown audio encoder"):
        audio_output(0, AudioOutputTrack(encoder="vorbis"), audio(), MKV, DEFS)
    out = audio_output(0, AudioOutputTrack(encoder="libopus"), audio(sample_rate=44100), MKV, DEFS)
    assert out.args == ["-c:a:0", "libopus", "-b:a:0", "320k", "-ar:a:0", "48000"]
    assert out.drc == 0.0
    vbr = audio_output(3, AudioOutputTrack(encoder="libmp3lame", quality=4.5), audio(codec="aac"),
                       MKV, DEFS)  # fmt: skip
    assert vbr.args == ["-c:a:3", "libmp3lame", "-q:a:3", "4.5"]
    assert vbr.drc is None
    flac = audio_output(0, AudioOutputTrack(encoder="flac", gain=-1.0), audio(), MKV, DEFS)
    assert flac.args == ["-c:a:0", "flac"]
    assert flac.filter == "volume=-1dB"
    stereo = audio_output(0, AudioOutputTrack(mixdown="stereo"),
                          audio(channels=2, channel_layout="stereo"), MKV, DEFS)  # fmt: skip
    assert stereo.filter is None


@pytest.mark.parametrize(
    ("encoder", "channels", "layout", "mixdown", "expected"),
    [
        ("aac", 6, "5.1", None, None),
        ("ac3", 8, "7.1", None, "aresample=out_chlayout=5.1"),
        ("libmp3lame", 6, "5.1(side)", None, "aresample=out_chlayout=stereo"),
        ("aac", 2, None, None, None),
        ("aac", 2, "stereo", "dpl2", None),  # nothing to matrix-encode: the same PCM
        ("aac", 6, "5.1(side)", "dpl2", "aresample=matrix_encoding=dplii:out_chlayout=stereo"),
        ("aac", 6, None, "5.1", "aresample=out_chlayout=5.1"),
        ("aac", 6, "5.1(side)", "mono", "aresample=out_chlayout=mono"),
        ("ac3", 8, "7.1", "7.1", "aresample=out_chlayout=5.1"),  # AC-3 has no 7.1
        ("ac3", 6, "5.1(side)", "7.1", "aresample=out_chlayout=5.1"),  # no upmix: relabel
        ("aac", 2, "stereo", "5.1", None),  # no upmix
        ("libopus", 6, "5.1", "5.1", None),
    ],
)  # fmt: skip
def test_output_layout(
    encoder: str, channels: int, layout: str | None, mixdown: str | None, expected: str | None
) -> None:
    track = AudioOutputTrack.model_validate({"encoder": encoder, "mixdown": mixdown})
    stream = audio(channels=channels, channel_layout=layout)
    assert audio_output(0, track, stream, MKV, DEFS).filter == expected


@pytest.mark.parametrize(
    ("layout", "channels", "written", "table"),
    [
        # Accepted as they are (the Vorbis channel orders of mapping family -1).
        *[(name, n, None, channels_mixdown(n)) for name, n in
          (("mono", 1), ("stereo", 2), ("3.0", 3), ("quad", 4), ("5.0", 5), ("5.1", 6),
           ("6.1", 7), ("7.1", 8))],
        # Side → back: a lossless relabel to an accepted layout.
        ("5.1(side)", 6, "5.1", "5.1"),
        ("5.0(side)", 5, "5.0", "5.1"),
        ("quad(side)", 4, "quad", "5.1"),
        ("6 channels (FL+FR+FC+LFE+SL+SR)", 6, "5.1", "5.1"),
        # Else the largest accepted layout made of the source's channels: a downmix.
        ("2.1", 3, "stereo", "stereo"),
        ("3.0(back)", 3, "stereo", "stereo"),
        ("4.0", 4, "3.0", "5.1"),
        ("3.1", 4, "3.0", "5.1"),
        ("4.1", 5, "3.0", "5.1"),
        ("6.0", 6, "5.0", "5.1"),
        ("6.0(front)", 6, "quad", "5.1"),
        ("hexagonal", 6, "5.0", "5.1"),
        ("6.1(back)", 7, "5.1", "5.1"),
        ("6.1(front)", 7, "quad", "5.1"),
        ("7.0", 7, "5.0", "5.1"),
        ("7.0(front)", 7, "5.0", "5.1"),
        ("7.1(wide)", 8, "5.1", "5.1"),
        ("7.1(wide-side)", 8, "5.1", "5.1"),
        ("octagonal", 8, "5.0", "5.1"),
        ("5.1.2", 8, "5.1", "5.1"),
        # Not known: left to FFmpeg.
        (None, 6, None, "5.1"),
        ("downmix", 2, None, "stereo"),
    ],
)  # fmt: skip
def test_opus_gets_a_layout_it_accepts(
    layout: str | None, channels: int, written: str | None, table: str
) -> None:
    """libopus lists no layouts, so FFmpeg does not convert for it, and it refuses all but
    the eight of :data:`ENCODER_LAYOUTS`."""
    stream = audio(channels=channels, channel_layout=layout)
    got = planned("libopus", stream)
    assert (got.mixdown, got.layout, got.bitrate_mixdown) == (None, written, table)
    out = audio_output(0, AudioOutputTrack(encoder="libopus"), stream, MKV, DEFS)
    assert out.filter == (f"aresample=out_chlayout={written}" if written else None)


@pytest.mark.parametrize(
    ("encoder", "layout", "channels", "written"),
    [
        ("aac", "5.1(side)", 6, "5.1"),  # a lossless relabel (the same PCM)
        ("aac", "6.0", 6, None),  # not 5.1: a remix would lose the back centre
        ("aac", "7.1(wide)", 8, None),  # not 7.1: a remix would lose the centre pair
        ("flac", "7.1(wide-side)", 8, None),
        ("flac", "6.1(back)", 7, None),
        ("ac3", "6.0", 6, None),  # FFmpeg converts for ac3 itself (it lists its layouts)
    ],
)  # fmt: skip
def test_other_encoders_keep_a_layout_or_relabel_losslessly(
    encoder: str, layout: str, channels: int, written: str | None
) -> None:
    got = planned(encoder, audio(channels=channels, channel_layout=layout))
    assert (got.mixdown, got.layout) == (None, written)


def test_layout_channels() -> None:
    assert layout_channels("5.1(side)") == ("FL", "FR", "FC", "LFE", "SL", "SR")
    assert layout_channels("3 channels (FL+FR+LFE)") == ("FL", "FR", "LFE")
    assert layout_channels("unknown") is None
    assert layout_channels(None) is None


def test_loudnorm_template() -> None:
    out = audio_output(
        1, AudioOutputTrack(mixdown="mono", loudness="streaming"), audio(), MKV, DEFS
    )
    assert out.analyse_filter == (
        "aresample=out_chlayout=mono,loudnorm=I=-16:TP=-1:LRA=20:print_format=json"
    )
    assert isinstance(out.filter, ArgTemplate)
    assert out.filter.parts[0] == "aresample=out_chlayout=mono,loudnorm=I=-16:TP=-1:LRA=20"
    refs = [p.ref for p in out.filter.parts if isinstance(p, ValueRef)]
    assert refs == ["a1.input_i", "a1.input_tp", "a1.input_lra", "a1.input_thresh",
                    "a1.target_offset"]  # fmt: skip
    assert LOUDNESS["ebu_r128"].targets() == "I=-23:TP=-1:LRA=20"


def test_subtitle_plan_errors() -> None:
    src = recorded("multitrack.mkv")
    burn = SubtitleOutputTrack(source=4, action="burn")
    with pytest.raises(PlanError, match="only one"):
        plan_subtitles([burn, burn], src, MKV, start=0, first_input=1, passthrough=False)
    with pytest.raises(PlanError, match="passed through"):
        plan_subtitles([burn], src, MKV, start=0, first_input=1, passthrough=True)
    with pytest.raises(PlanError, match="no subtitle stream 9"):
        plan_subtitles([SubtitleOutputTrack(source=9)], src, MKV, start=0, first_input=1,
                       passthrough=False)  # fmt: skip
    with pytest.raises(PlanError, match="needs a target"):
        plan_subtitles([SubtitleOutputTrack(source=4, action="convert")], src, MKV, start=0,
                       first_input=1, passthrough=False)  # fmt: skip
    with pytest.raises(PlanError, match="mov_text cannot be written"):
        plan_subtitles([SubtitleOutputTrack(source=4, action="convert", convert_to="mov_text")],
                       src, MKV, start=0, first_input=1, passthrough=False)  # fmt: skip
    ext = ExternalSubtitle(path=Path("/m/a.idx"))
    with pytest.raises(PlanError, match="unknown subtitle file type"):
        plan_subtitles([SubtitleOutputTrack(source=ext)], src, MKV, start=0, first_input=1,
                       passthrough=False)  # fmt: skip
    pgs = recorded("pgs")
    with pytest.raises(PlanError, match="cannot go into MP4"):
        plan_subtitles([SubtitleOutputTrack(source=2)], pgs, MP4, start=0, first_input=1,
                       passthrough=False)  # fmt: skip
    with pytest.raises(PlanError, match="bitmap subtitles to text"):
        plan_subtitles([SubtitleOutputTrack(source=2, action="convert", convert_to="srt")], pgs,
                       MKV, start=0, first_input=1, passthrough=False)  # fmt: skip


def test_subtitle_conversions_and_externals() -> None:
    src = recorded("multitrack.mkv")
    tracks = [
        SubtitleOutputTrack(source=4, action="convert", convert_to="ass"),
        SubtitleOutputTrack(source=ExternalSubtitle(path=Path("/m/a.vtt"), offset_ms=-500)),
        SubtitleOutputTrack(source=ExternalSubtitle(path=Path("/m/b.ass"), charset="cp1250")),
    ]
    plan = plan_subtitles(tracks, src, MKV, start=2.0, first_input=1, passthrough=False)
    assert [(o.map, o.codec, o.ass) for o in plan.outputs] == [
        ("0:4", "ass", True), ("1:0", "copy", False), ("2:0", "ass", True),
    ]  # fmt: skip
    assert plan.copies_ass
    assert [i.args for i in plan.inputs] == [
        ["-itsoffset", "-0.5", "-ss", "2", "-i", str(Path("/m/a.vtt"))],
        ["-ss", "2", "-sub_charenc", "cp1250", "-i", str(Path("/m/b.ass"))],
    ]
    webm = plan_subtitles(tracks[1:2], src, WEBM, start=0, first_input=1, passthrough=False)
    assert webm.outputs[0].codec == "copy"
    assert not webm.copies_ass


def test_languages_and_ietf() -> None:
    assert container_language("de", MKV) == "ger"
    assert container_language("de", MP4) == "deu"
    assert container_language(None, MP4) == "und"
    assert [needs_ietf(v) for v in ("pt-BR", "yue", "zh-Hant", "de", "ger", "und", None)] == [
        True, True, True, False, False, False, False,
    ]  # fmt: skip


def test_dispositions_follow_the_container() -> None:
    flags = TrackMetadata(default=True, commentary=True, original=True, hearing_impaired=True)
    assert dispositions(flags, MKV, DEFS) == "default+comment+hearing_impaired+original"
    assert dispositions(flags, MP4, DEFS) == "default+comment+hearing_impaired"
    assert dispositions(flags, WEBM, DEFS) == "default"
    assert dispositions(TrackMetadata(), MKV, DEFS) == "0"


def test_output_track_title() -> None:
    meta = TrackMetadata
    assert OutputTrack("a", 0, meta(), "en", "Src").title == "Src"
    assert OutputTrack("a", 0, meta(name=""), "en", "Src").title is None
    assert OutputTrack("a", 0, meta(name="New", language="hu"), "en", "Src").language == "hu"


def test_ffmetadata_escaping() -> None:
    text = ffmetadata([(0.0, 1.5, "A = b; c # d \\ e\nf"), (1.5, 3.0, "")])
    assert text == (
        ";FFMETADATA1\n[CHAPTER]\nTIMEBASE=1/1000\nSTART=0\nEND=1500\n"
        "title=A \\= b\\; c \\# d \\\\ e\\\nf\n"
        "[CHAPTER]\nTIMEBASE=1/1000\nSTART=1500\nEND=3000\n"
    )


def test_chapter_plans() -> None:
    src = recorded("chapters.mkv")
    job = draft(src)
    path = Path("/out/x.part.chapters.txt")

    def plan(**kwargs: Any) -> Any:
        return chapter_plan(job, src, MKV, start=kwargs.pop("start", 0.0),
                            duration=kwargs.pop("duration", None), expected_duration=5.0,
                            file_path=path)  # fmt: skip

    assert plan().map_from == 0
    assert plan(start=1.2, duration=2.0).map_from == 0  # no chapter edge on the range edges
    # A range edge on a chapter edge: FFmpeg's copy would keep an empty chapter there, so
    # the source's chapters are written, cut to the range, as FFMETADATA.
    for start, duration in ((1.0, 3.0), (1.0, None), (0.0, 2.5), (1.0004, 2.9995)):
        edges = plan(start=start, duration=duration)
        assert edges.map_from == ChapterPlan.FROM_FILE
        assert edges.file is not None
        assert ("Opening" in edges.file.content) == (start == 0)
    cut = plan(start=1.0, duration=3.0).file
    assert cut is not None
    assert cut.content == ffmetadata([(0.0, 1.5, "Part One"), (1.5, 3.0, "Part Two")])
    job.chapters = ChapterSettings(enabled=False)
    assert plan().map_from is None
    job.chapters = ChapterSettings(names=["A", "B"])
    renamed = plan(start=0.5, duration=3.0)
    assert renamed.file is not None
    assert "title=A" in renamed.file.content
    assert "START=500\nEND=2000\ntitle=B" in renamed.file.content
    assert "Credits" not in renamed.file.content
    job.chapters = ChapterSettings(names=["A"])
    assert plan(start=10.0, duration=1.0).map_from is None
    no_chapters = MKV.model_copy(update={"chapters": False})
    assert chapter_plan(job, src, no_chapters, start=0, duration=None, expected_duration=5,
                        file_path=path).map_from is None  # fmt: skip
    none = recorded("multitrack.mkv")
    plain_job = draft(none)
    assert chapter_plan(plain_job, none, MKV, start=0, duration=None, expected_duration=4,
                        file_path=path).map_from is None  # fmt: skip
    plain_job.chapters = ChapterSettings(generate_every=1 / 60, names=["First"])
    generated = chapter_plan(plain_job, none, MKV, start=0, duration=None, expected_duration=4.1,
                             file_path=path)  # fmt: skip
    assert generated.file is not None
    assert generated.file.content.count("[CHAPTER]") == 4
    assert "title=First" in generated.file.content
    assert "END=4100\ntitle=Chapter 4" in generated.file.content


def test_chapter_range_bounds() -> None:
    chapters = recorded("chapters.mkv")  # 4 chapters: 0-1, 1-2.5, 2.5-4, 4-5 s
    assert chapter_range(chapters, ChapterRange(start=2, end=3)) == (1.0, 4.0)
    # An end after the last chapter is clamped to it.
    assert chapter_range(chapters, ChapterRange(start=4, end=5)) == (4.0, 5.0)
    assert chapter_range(chapters, ChapterRange(start=2, end=99)) == (1.0, 5.0)
    # A start after the last chapter, an end before the start, no chapters: not plannable.
    with pytest.raises(PlanError, match="chapters 5 to 6 are not in the source"):
        chapter_range(chapters, ChapterRange(start=5, end=6))
    with pytest.raises(PlanError, match="chapters 3 to 2 are not in the source"):
        chapter_range(chapters, ChapterRange(start=3, end=2))
    with pytest.raises(PlanError, match="0 chapters"):
        chapter_range(recorded("multitrack.mkv"), ChapterRange(start=1, end=1))
    assert Chapter(index=0, start=0, end=1)  # the model accepts what chapter_range reads


def test_render_tag() -> None:
    src = recorded("multitrack.mkv", path=Path("/media/The.Movie.2024.1080p.mkv"))
    job = draft(src)
    options = NamingOptions(word_separator="space")

    def tag(text: str, now: datetime | None = None) -> str:
        return render_tag(text, job, src, options=options, output_size=(1920, 800), now=now,
                          definitions=DEFS)  # fmt: skip

    assert tag("Plain text, no variables {{x}}") == "Plain text, no variables {x}"
    assert tag("{name} ({year}) {resolution}") == "The Movie (2024) 1080p"
    assert tag("{date:%Y}<, {date:%m}>") == ""
    assert tag("{date:%Y}", datetime(2026, 1, 2, tzinfo=UTC)) == "2026"
    assert tag("broken {name") == "broken {name"
    assert tag("A / B") == "A / B"


def test_tag_args() -> None:
    tags = TagSettings(title="T", plot="", genre=None)
    assert tag_args(tags, passthru=True, render_value=str.upper) == [
        "-map_metadata", "0", "-metadata", "title=T", "-metadata", "synopsis=",
    ]  # fmt: skip
    assert tag_args(TagSettings(), passthru=False, render_value=str) == ["-map_metadata:g", "-1"]


def test_job_type_reasons() -> None:
    src = recorded("multitrack.mkv")
    job = draft(src, video={"encoder": "libx265"})
    assert job_type(job, src) == ("encode", "Encode: the video is encoded with x265.")
    job.video.encoder = "my_encoder"
    assert job_type(job, src)[1] == "Encode: the video is encoded with my_encoder."
    job = draft(src, audio="passthru")
    job.video.passthrough = True
    assert job_type(job, src)[0] == "remux"
    job.audio[1].action = "encode"
    assert job_type(job, src)[1] == (
        "Encode: video passthrough, but audio track 2 (AAC-LC) is encoded."
    )
    job = draft(src, audio="passthru", container="webm")
    job.video.passthrough = True
    assert job_type(job, src)[1] == (
        "Encode: video passthrough, but audio track 1 (AC-3) cannot be copied into WebM, "
        "so it is encoded."
    )
    job = draft(src, audio="passthru")
    job.video.passthrough = True
    job.audio[0].source_stream = 42
    assert "audio track 1 cannot be copied" in job_type(job, src)[1]
    job = draft(src, audio="passthru")
    job.video.passthrough = True
    job.subtitles[1].action = "burn"
    assert job_type(job, src)[1].endswith("subtitle track 2 is burned in.")
    job.subtitles[1].action = "convert"
    assert job_type(job, src)[1].endswith("subtitle track 2 is converted.")
