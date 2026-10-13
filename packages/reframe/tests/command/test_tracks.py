"""Audio and subtitle output tracks, track metadata, chapters, tags, job type."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from reframe.command import PlanError, job_type
from reframe.command.audio import (
    LOUDNESS,
    audio_output,
    closest_samplerate,
    effective_mixdown,
)
from reframe.command.metadata import (
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
from reframe.definitions import load_definitions
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


# --------------------------------------------------------------------------- audio


def test_effective_mixdown() -> None:
    aac, ac3, mp3 = (DEFS.audio_encoders[e] for e in ("aac", "ac3", "libmp3lame"))
    track = AudioOutputTrack()
    assert effective_mixdown(track, audio(channels=8), aac) == "7.1"
    assert effective_mixdown(track, audio(channels=8), ac3) == "5.1"
    assert effective_mixdown(track, audio(channels=6), mp3) == "stereo"
    assert effective_mixdown(track, audio(channels=3), aac) == "5.1"
    assert effective_mixdown(track, audio(channels=1), aac) == "mono"
    assert effective_mixdown(track, audio(channels=0), aac) == "stereo"
    assert effective_mixdown(AudioOutputTrack(mixdown="dpl2"), audio(), aac) == "dpl2"
    no_layouts = aac.model_copy(update={"mixdowns": []})
    assert effective_mixdown(track, audio(channels=8), no_layouts) == "7.1"
    mono_only = aac.model_copy(update={"mixdowns": ["mono"]})
    assert effective_mixdown(track, audio(channels=2), mono_only) == "mono"
    nothing = aac.model_copy(update={"mixdowns": ["dpl2"]})
    assert effective_mixdown(track, audio(channels=2), nothing) == "stereo"


def test_closest_samplerate() -> None:
    assert closest_samplerate(44100, [8000, 12000, 16000, 24000, 48000]) == 48000
    assert closest_samplerate(44100, [32000, 44100, 48000]) == 44100
    assert closest_samplerate(20000, [16000, 24000]) == 24000
    assert closest_samplerate(96000, []) == 96000


def test_passthru_copies_or_falls_back() -> None:
    out = audio_output(0, AudioOutputTrack(action="passthru"), audio(codec="truehd"), MP4, DEFS)
    assert out.copy
    assert out.args == ["-c:a:0", "copy"]
    assert out.global_args == ["-strict", "-2"]
    # The default fallback is AAC, which WebM cannot hold (validation reports it).
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
        ("libopus", 6, "5.1(side)", None, "aresample=out_chlayout=5.1"),
        ("aac", 6, "5.1", None, None),
        ("ac3", 8, "7.1", None, "aresample=out_chlayout=5.1"),
        ("libmp3lame", 6, "5.1(side)", None, "aresample=out_chlayout=stereo"),
        ("aac", 5, "5.0", None, None),
        ("libopus", 3, "2.1", None, None),
        ("aac", 2, None, None, None),
        ("aac", 2, "stereo", "dpl2", "aresample=matrix_encoding=dplii:out_chlayout=stereo"),
        ("aac", 6, None, "5.1", "aresample=out_chlayout=5.1"),
        ("aac", 6, "5.1(side)", "mono", "aresample=out_chlayout=mono"),
    ],
)  # fmt: skip
def test_output_layout(
    encoder: str, channels: int, layout: str | None, mixdown: str | None, expected: str | None
) -> None:
    track = AudioOutputTrack.model_validate({"encoder": encoder, "mixdown": mixdown})
    stream = audio(channels=channels, channel_layout=layout)
    assert audio_output(0, track, stream, MKV, DEFS).filter == expected


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


# --------------------------------------------------------------------------- subtitles


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
        ["-itsoffset", "-0.5", "-ss", "2", "-i", "/m/a.vtt"],
        ["-ss", "2", "-sub_charenc", "cp1250", "-i", "/m/b.ass"],
    ]
    webm = plan_subtitles(tracks[1:2], src, WEBM, start=0, first_input=1, passthrough=False)
    assert webm.outputs[0].codec == "copy"
    assert not webm.copies_ass


# --------------------------------------------------------------------------- metadata


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
    chapters = recorded("chapters.mkv")
    assert chapter_range(chapters, ChapterRange(start=2, end=3)) == (1.0, 4.0)
    with pytest.raises(PlanError, match="not in the source"):
        chapter_range(chapters, ChapterRange(start=4, end=5))
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


# --------------------------------------------------------------------------- job type


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
