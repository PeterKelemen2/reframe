"""The ``metadata_edit`` job type, its blockers and its mkvpropedit plan (pure; the real tools
are tested in ``tests/metadata/test_metadata_edit_real.py``)."""

from __future__ import annotations

from pathlib import Path

import pytest

from reframe.command import build_plan, in_place_blockers, is_matroska_source, job_type
from reframe.command.mkvpropedit import (
    FixupTrack,
    InfoEdit,
    TrackEdit,
    edit_args,
    fixup_edits,
    in_place_edits,
    language_pair,
    track_selector,
)
from reframe.definitions import load_definitions
from reframe.metadata import remux_job
from reframe.models import (
    ChapterRange,
    ChapterSettings,
    ContainerInfo,
    ExternalSubtitle,
    JobSettings,
    MediaSource,
    SubtitleOutputTrack,
    TagSettings,
    TimeRange,
    TrackHeaderEdit,
    TrackMetadata,
)

from .conftest import caps, draft, recorded, tools

DEFS = load_definitions()


def in_place() -> tuple[JobSettings, MediaSource]:
    src = recorded("multitrack.mkv")
    return remux_job(draft(src), src, edit_in_place=True), src


def test_a_remux_job_of_an_mkv_edited_in_place_is_a_metadata_edit() -> None:
    job, src = in_place()
    job.audio[0].metadata.language = "hu"
    job.subtitles[1].metadata.forced = True
    assert job_type(job, src) == (
        "metadata_edit",
        "Metadata edit: only the track metadata changes, so mkvpropedit edits multitrack.mkv "
        "in place, in seconds.",
    )
    assert in_place_blockers(job, src) == []


def test_without_edit_in_place_the_same_job_is_a_remux() -> None:
    job, src = in_place()
    job.output.edit_in_place = False
    job.output.path = Path("/out/multitrack.mkv")
    assert job_type(job, src)[0] == "remux"
    assert job_type(job, src)[1].startswith("Remux: ")


@pytest.mark.parametrize(
    ("change", "kind", "why"),
    [
        (lambda j, s: setattr(j.audio[0], "action", "encode"), "encode",
         "audio track 1 (AC-3) is encoded"),
        (lambda j, s: setattr(j.video, "passthrough", False), "encode", "the video is encoded"),
        (lambda j, s: setattr(j.output, "container", "mp4"), "remux",
         "the output container is MP4, not MKV"),
        (lambda j, s: setattr(j, "range", TimeRange(start=1.0)), "remux",
         "only a part of the source is kept (a range is set)"),
        (lambda j, s: j.audio.pop(1), "remux",
         "the audio tracks are not the source's audio tracks in source order"),
        (lambda j, s: j.audio.reverse(), "remux",
         "the audio tracks are not the source's audio tracks in source order"),
        (lambda j, s: j.subtitles.pop(), "remux",
         "the subtitle tracks are not the source's subtitle tracks in source order"),
        (lambda j, s: setattr(j.subtitles[0], "action", "convert"), "encode",
         "subtitle track 1 is converted"),
        (lambda j, s: j.subtitles.append(SubtitleOutputTrack(
            source=ExternalSubtitle(path=Path("/media/x.srt")))), "remux",
         "a subtitle file is added"),
        (lambda j, s: setattr(j.output, "passthru_metadata", False), "remux",
         "the source's tags are not kept"),
        (lambda j, s: setattr(j, "tags", TagSettings(genre="Drama", plot="P")), "remux",
         "tags other than the title are set (genre, plot)"),
        (lambda j, s: setattr(s.container, "format_name", "mov,mp4,m4a,3gp,3g2,mj2"), "remux",
         "the source is not an MKV file"),
    ],
)  # fmt: skip
def test_why_a_job_is_not_a_metadata_edit(change: object, kind: str, why: str) -> None:
    job, src = in_place()
    change(job, src)  # type: ignore[operator]
    reason = job_type(job, src)
    assert reason[0] == kind
    assert reason[1].endswith(f" It cannot be edited in place: {why}.")
    assert in_place_blockers(job, src)[0] == why


def test_chapter_changes_are_not_a_metadata_edit() -> None:
    src = recorded("chapters.mkv")
    job = remux_job(draft(src), src, edit_in_place=True)
    assert in_place_blockers(job, src) == []
    assert job_type(job, src)[0] == "metadata_edit"
    job.chapters = ChapterSettings(enabled=False)
    assert in_place_blockers(job, src) == ["the chapters are removed"]
    job.chapters = ChapterSettings(names=["A"])
    assert in_place_blockers(job, src) == ["the chapters are renamed"]
    job.range = ChapterRange(start=1, end=1)
    assert len(in_place_blockers(job, src)) == 2
    plain, plain_src = in_place()
    plain.chapters = ChapterSettings(generate_every=5.0)
    assert in_place_blockers(plain, plain_src) == ["chapters are generated"]


def test_a_second_video_track_and_webm_are_blockers() -> None:
    job, src = in_place()
    src.video.append(src.video[0].model_copy(update={"index": 9}))
    assert in_place_blockers(job, src) == ["only the first of the source's 2 video tracks is kept"]
    webm = recorded("multitrack.mkv", path=Path("/media/clip.webm"))
    assert not is_matroska_source(webm)
    assert is_matroska_source(recorded("multitrack.mkv"))
    assert not is_matroska_source(
        webm.model_copy(update={"container": ContainerInfo(format_name=None)})
    )


def test_an_audio_codec_the_container_cannot_copy_blocks() -> None:
    job, src = in_place()
    src.audio[0].codec = "pcm_bluray"
    assert in_place_blockers(job, src) == [
        "audio track 1 (AC-3) cannot be copied into Matroska (MKV)"
    ]
    job, src = in_place()
    src.subtitles[0].codec = "mov_text"
    assert in_place_blockers(job, src) == ["subtitle track 1 cannot be copied into Matroska (MKV)"]


def test_track_edit_arguments() -> None:
    assert track_selector("a", 2) == "track:a2"
    assert language_pair("pt-BR") == ("por", "pt-BR")
    assert language_pair(None) == ("und", "und")
    edit = TrackEdit(
        "track:a1", ("hun", "hu"), "Magyar", flags=(("flag-default", True), ("flag-forced", False))
    )
    assert edit.args() == [
        "--edit", "track:a1", "--set", "language=hun", "--set", "language-ietf=hu",
        "--set", "name=Magyar", "--set", "flag-default=1", "--set", "flag-forced=0",
    ]  # fmt: skip
    assert TrackEdit("track:s1", delete_name=True).args() == [
        "--edit", "track:s1", "--delete", "name",
    ]  # fmt: skip
    assert InfoEdit(None).args() == ["--edit", "info", "--delete", "title"]
    assert InfoEdit("T").args() == ["--edit", "info", "--set", "title=T"]
    assert edit_args([TrackEdit("track:v1"), InfoEdit("T")]) == [
        "--edit",
        "info",
        "--set",
        "title=T",
    ]


def test_in_place_edits_write_only_what_differs() -> None:
    job, src = in_place()
    assert in_place_edits(job, src, DEFS) == []
    job.video.metadata.name = "Main"
    job.audio[0].metadata.language = "ja"  # the same as the source's jpn: nothing to write
    job.audio[1].metadata.language = "en-GB"
    job.audio[2].metadata.name = ""
    job.audio[2].metadata.commentary = False
    job.subtitles[0].metadata.name = "English"  # unchanged
    job.subtitles[2].metadata = TrackMetadata()  # every flag off, keep language and name
    edits = in_place_edits(job, src, DEFS)
    assert edit_args(edits) == [
        "--edit", "track:v1", "--set", "name=Main",
        "--edit", "track:a2", "--set", "language=eng", "--set", "language-ietf=en-GB",
        "--edit", "track:a3", "--delete", "name", "--set", "flag-commentary=0",
        "--edit", "track:s3", "--set", "flag-forced=0",
    ]  # fmt: skip


def test_in_place_title_is_rendered_and_compared() -> None:
    job, src = in_place()
    assert src.container.title == "Reframe multi-track fixture"
    job.tags.title = "Reframe multi-track fixture"
    assert in_place_edits(job, src, DEFS) == []
    job.tags.title = "  "
    assert in_place_edits(job, src, DEFS) == [InfoEdit(None)]
    job.tags.title = "{x}"
    assert in_place_edits(job, src, DEFS, render_title=lambda t: "New") == [InfoEdit("New")]


def test_name_delete_only_when_the_source_has_one() -> None:
    job, src = in_place()
    job.video.metadata.name = ""  # the source video has no title: nothing to delete
    assert in_place_edits(job, src, DEFS) == []


def test_ietf_of_the_source_counts() -> None:
    job, src = in_place()
    src.audio[1].language_ietf = "en-US"
    job.audio[1].metadata.language = "en"
    assert edit_args(in_place_edits(job, src, DEFS)) == [
        "--edit", "track:a2", "--set", "language=eng", "--set", "language-ietf=en",
    ]  # fmt: skip


def test_fixup_writes_ietf_and_the_flags_the_muxer_cannot() -> None:
    mkv = DEFS.containers["mkv"]
    tracks = [
        FixupTrack("a", 1, "pt-BR", TrackMetadata()),
        FixupTrack("a", 2, "de", TrackMetadata(original=True)),
        FixupTrack("s", 1, None, TrackMetadata()),
    ]
    assert [e.args() for e in fixup_edits(tracks, mkv, DEFS)] == [
        ["--edit", "track:a1", "--set", "language=por", "--set", "language-ietf=pt-BR"]
    ]
    custom = mkv.model_copy(update={"flags": ["default"], "mkvpropedit_flags": ["original"]})
    assert [e.args() for e in fixup_edits(tracks, custom, DEFS)] == [
        ["--edit", "track:a1", "--set", "language=por", "--set", "language-ietf=pt-BR"],
        ["--edit", "track:a2", "--set", "flag-original=1"],
    ]


def test_metadata_edit_plan_edits_the_source() -> None:
    job, src = in_place()
    job.audio[0].metadata.language = "pt-BR"
    plan = build_plan(job, src, caps(), tools())
    assert plan.job_type == "metadata_edit"
    assert plan.output_tmp == plan.output_final == src.ref.path
    assert plan.files == []
    assert plan.temp_files == []
    [step] = plan.steps
    assert step.kind == "header_edit"
    assert step.tool is None
    assert step.header_edit is not None
    assert step.header_edit.path == src.ref.path
    assert step.description == "Edit the metadata of 1 track of multitrack.mkv in place"
    assert plan.display.startswith(f"mkvpropedit {src.ref.path} --edit track:a1")


def test_metadata_edit_plan_needs_no_output_path() -> None:
    job, src = in_place()
    job.output.path = None
    job.tags.title = "T"
    plan = build_plan(job, src, caps(), tools())
    assert plan.steps[0].description == "Edit the title of multitrack.mkv in place"
    job.audio[1].metadata.name = "Two"
    job.audio[2].metadata.name = "Three"
    plan = build_plan(job, src, caps(), tools())
    assert plan.steps[0].description == (
        "Edit the metadata of 2 tracks and the title of multitrack.mkv in place"
    )


def test_fixup_step_with_flags_has_both_in_its_description(monkeypatch: pytest.MonkeyPatch) -> None:
    defs = DEFS.model_copy(deep=True)
    mkv = defs.containers["mkv"]
    defs.containers["mkv"] = mkv.model_copy(
        update={
            "flags": [f for f in mkv.flags if f != "original"],
            "mkvpropedit_flags": ["original"],
        }
    )
    src = recorded("multitrack.mkv")
    job = draft(src, video={"encoder": "libx264"})
    job.audio[0].metadata = TrackMetadata(language="pt-BR", original=True)
    plan = build_plan(job, src, caps(), tools(), definitions=defs)
    fixup = next(s for s in plan.steps if s.kind == "header_edit")
    assert fixup.description == (
        "Write the BCP 47 languages (Matroska LanguageIETF) and the track flags FFmpeg cannot write"
    )
    assert fixup.header_edit is not None
    assert fixup.header_edit.tracks == [
        TrackHeaderEdit(
            track_type="audio", number=1, language="por", language_ietf="pt-BR",
            flags={"original": True},
        )
    ]  # fmt: skip
    job.audio[0].metadata = TrackMetadata(original=True)
    plan = build_plan(job, src, caps(), tools(), definitions=defs)
    fixup = next(s for s in plan.steps if s.kind == "header_edit")
    assert fixup.description == "Write the track flags FFmpeg cannot write"
