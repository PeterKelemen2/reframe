"""The re-probe check after a metadata change, on changed copies of recorded probes."""

from __future__ import annotations

from pathlib import Path

from reframe.command import build_plan
from reframe.definitions import load_definitions
from reframe.metadata import remux_job
from reframe.models import (
    AudioOutputTrack,
    EncodePlan,
    ExternalSubtitle,
    HeaderEdit,
    InfoHeaderEdit,
    JobSettings,
    MediaSource,
    OutputSettings,
    PlanStep,
    SourceRef,
    SubtitleOutputTrack,
    TrackHeaderEdit,
    TrackMetadata,
)
from reframe.queue.verify import check_output, expected_streams, planned_title

from .conftest import all_caps, recorded, tool_set

DEFS = load_definitions()
SOURCE = Path("/media/Show.S01E01.mkv")
TOOLS = tool_set(Path("/usr/bin/ffmpeg"), mkvpropedit=Path("/usr/bin/mkvpropedit"))


def in_place() -> tuple[JobSettings, MediaSource]:
    source = recorded("multitrack.mkv", SOURCE)
    job = JobSettings(source=SourceRef(path=SOURCE))
    return remux_job(job, source), source


def plan_of(job: JobSettings, source: MediaSource) -> EncodePlan:
    return build_plan(job, source, all_caps(), TOOLS, definitions=DEFS)


def edited(source: MediaSource, job: JobSettings) -> MediaSource:
    """What the file looks like when mkvpropedit did everything the job asks."""
    out = source.model_copy(deep=True)
    for stream, track in zip(out.audio, job.audio, strict=True):
        meta = track.metadata
        stream.language = {"hu": "hun", "pt-BR": "por"}.get(meta.language or "", stream.language)
        stream.language_ietf = meta.language if meta.language in ("hu", "pt-BR") else None
        stream.title = meta.name or None
        d = stream.disposition
        d.default, d.forced, d.comment = meta.default, meta.forced, meta.commentary
        d.hearing_impaired, d.visual_impaired = meta.hearing_impaired, meta.visual_impaired
        d.original = meta.original
    return out


def test_an_in_place_edit_that_wrote_everything_passes() -> None:
    job, source = in_place()
    job.audio[0].metadata.language = "hu"
    job.audio[1].metadata.language = "pt-BR"
    job.audio[1].metadata.name = "Brazilian"
    job.audio[2].metadata.original = True
    plan = plan_of(job, source)
    assert plan.job_type == "metadata_edit"
    assert check_output(job, source, edited(source, job), DEFS, plan=plan) == []


def test_each_difference_is_named() -> None:
    job, source = in_place()
    job.audio[1].metadata.language = "pt-BR"
    job.audio[1].metadata.name = "Brazilian"
    job.audio[2].metadata.original = True
    job.tags.title = "New title"
    plan = plan_of(job, source)
    # Nothing was written: the file is the source as it was.
    assert check_output(job, source, source, DEFS, plan=plan) == [
        "audio track 2: language por expected, eng found",
        "audio track 2: BCP 47 language pt-BR expected, en found",
        "audio track 2: name 'Brazilian' expected, 'English Stereo' found",
        "audio track 3: the original flag should be set",
        "title 'New title' expected, 'Reframe multi-track fixture' found",
    ]
    # Without a plan (or a plan without mkvpropedit) only the layout and ISO codes count.
    assert check_output(job, source, source, DEFS) == [
        "audio track 2: language por expected, eng found"
    ]


def test_flags_that_should_not_be_set() -> None:
    job, source = in_place()
    job.subtitles[1].metadata.hearing_impaired = False
    plan = plan_of(job, source)
    assert check_output(job, source, source, DEFS, plan=plan) == [
        "subtitle track 2: the hearing impaired flag should not be set"
    ]


def test_a_layout_difference_is_not_repeated_per_track() -> None:
    job, source = in_place()
    job.audio[0].metadata.name = "X"
    plan = plan_of(job, source)
    fewer = source.model_copy(deep=True)
    fewer.audio.pop()
    assert check_output(job, source, fewer, DEFS, plan=plan) == ["3 audio tracks expected, 2 found"]


def test_fixup_checks_ietf_only_where_it_was_written() -> None:
    source = recorded("multitrack.mkv", SOURCE)
    job = JobSettings(
        source=SourceRef(path=SOURCE),
        output=OutputSettings(path=Path("/out/x.mkv")),
        audio=[
            AudioOutputTrack(source_stream=a.index, metadata=TrackMetadata(
                language=lang, default=a.disposition.default, commentary=a.disposition.comment))
            for a, lang in zip(source.audio, ["pt-BR", "de", None], strict=True)
        ],
    )  # fmt: skip
    job.video.metadata = TrackMetadata(default=True)
    plan = plan_of(job, source)
    assert [s.kind for s in plan.steps] == ["encode", "header_edit", "finalize"]
    output = source.model_copy(deep=True)
    output.subtitles = []
    output.audio[0].language = "por"
    output.audio[1].language = "ger"
    assert check_output(job, source, output, DEFS, plan=plan) == [
        "audio track 1: BCP 47 language pt-BR expected, pt found"
    ]
    output.audio[0].language_ietf = "pt-BR"
    assert check_output(job, source, output, DEFS, plan=plan) == []
    # MediaInfo derives BCP 47 from the legacy code: "de" for "ger" is the same language.
    output.audio[1].language_ietf = "de"
    assert check_output(job, source, output, DEFS, plan=plan) == []
    # Without mkvpropedit the step is not planned and por is what is expected.
    no_tool = build_plan(job, source, all_caps(), tool_set(Path("/usr/bin/ffmpeg")))
    output.audio[0].language_ietf = None
    assert check_output(job, source, output, DEFS, plan=no_tool) == []


def test_expected_titles_of_external_and_burned_subtitles() -> None:
    source = recorded("multitrack.mkv", SOURCE)
    job = JobSettings(
        source=SourceRef(path=SOURCE),
        subtitles=[
            SubtitleOutputTrack(source=ExternalSubtitle(path=Path("/m/x.srt"), name="Ext",
                                                        language="hu")),
            SubtitleOutputTrack(source=4, metadata=TrackMetadata(name="")),
            SubtitleOutputTrack(source=5, action="burn"),
        ],
    )  # fmt: skip
    subs = [
        e for e in expected_streams(job, source, DEFS.containers["mkv"]) if e.kind == "subtitle"
    ]
    assert [(e.language, e.bcp47, e.title) for e in subs] == [
        ("hun", "hu", "Ext"), ("eng", "eng", None),
    ]  # fmt: skip


def test_planned_title() -> None:
    def plan(edit: HeaderEdit) -> EncodePlan:
        step = PlanStep(kind="header_edit", tool=None, header_edit=edit)
        other = PlanStep(kind="encode", tool="ffmpeg", argv=["--edit", "info"])
        return EncodePlan(
            job_type="metadata_edit", steps=[other, step], output_tmp=Path("/f.mkv"),
            output_final=Path("/f.mkv"), expected_duration=0, display="",
        )  # fmt: skip

    track = TrackHeaderEdit(track_type="audio", number=1, name="x")
    assert planned_title(plan(HeaderEdit(path=Path("/f.mkv"), tracks=[track]))) == (False, None)
    titled = HeaderEdit(path=Path("/f.mkv"), info=InfoHeaderEdit(title="T"))
    assert planned_title(plan(titled)) == (True, "T")
    removed = HeaderEdit(path=Path("/f.mkv"), info=InfoHeaderEdit(title=None))
    assert planned_title(plan(removed)) == (True, None)
