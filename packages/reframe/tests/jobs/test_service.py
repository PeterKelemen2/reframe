"""``Reframe.jobs``: draft, validate, plan and name, with stub services (no processes). The
sources are recorded probes (``testdata/probes``) at paths under ``tmp_path``, so the output
paths are real, writable folders and validation reads the real file system.
"""

from __future__ import annotations

import asyncio
import time
from datetime import UTC, datetime
from pathlib import Path

import pytest

from reframe.batch import draft_tracks
from reframe.jobs import (
    JobService,
    find_media_files,
    is_partial_output,
    job_from_preset,
    output_size,
    video_metadata,
)
from reframe.models import (
    AudioCodecRule,
    EncodePlan,
    JobDraft,
    NamingOptions,
    Severity,
    TrackDraft,
    TrackFlags,
    ValidationIssue,
)
from reframe.probe import ProbeError

from .conftest import Stubs, caps, checking, media_file, preset, recorded

pytestmark = pytest.mark.anyio

NOW = datetime(2026, 10, 14, 12, 0, tzinfo=UTC)


def service(stubs: Stubs, **kw: object) -> JobService:
    return JobService(
        sources=stubs,
        presets=stubs,
        tools=stubs,
        capabilities=stubs,
        settings=lambda: stubs.settings,
        clock=lambda: NOW,
        **kw,  # type: ignore[arg-type]
    )


def codes(issues: list[ValidationIssue]) -> list[str]:
    return [issue.code for issue in issues]


def errors(issues: list[ValidationIssue]) -> list[str]:
    return [issue.code for issue in issues if issue.severity is Severity.ERROR]


@pytest.fixture
def movie(tmp_path: Path) -> tuple[Stubs, Path]:
    """The TrueHD Atmos recording as ``<tmp>/Movie.2016.1080p.BluRay-GRP/movie.mkv``."""
    folder = tmp_path / "Movie.2016.1080p.BluRay-GRP"
    folder.mkdir()
    file = folder / "movie.mkv"
    file.write_bytes(b"x")
    return Stubs({file: recorded("truehd-atmos", file)}), file


async def test_draft_with_the_default_preset(movie: tuple[Stubs, Path]) -> None:
    stubs, file = movie
    draft = await service(stubs).draft(file)
    assert isinstance(draft, JobDraft)
    job = draft.job
    default = preset("h265-mkv-1080p")
    source = stubs.sources[file]
    # From the preset: output options, dimensions, filters, video, chapters, tags.
    assert (job.preset_id, job.preset_name) == ("h265-mkv-1080p", "H.265 MKV 1080p")
    assert job.output.container == "mkv"
    assert job.dimensions == default.dimensions
    assert job.filters == default.filters
    assert job.video.model_dump(exclude={"metadata"}) == default.video.model_dump(
        exclude={"metadata"}
    )
    assert job.chapters.enabled == default.chapters.enabled
    assert job.tags == default.tags
    # Tracks: every audio track through the rules, every subtitle copied.
    tracks = draft_tracks(source, default)
    assert job.audio == tracks.audio
    assert job.subtitles == tracks.subtitles
    assert draft.decisions == tracks.decisions
    assert len(draft.decisions) == len(source.audio)
    # The video track: source metadata and the default flag.
    assert job.video.metadata.default is True
    assert job.video.metadata == video_metadata(source.video[0])
    # The name: the folder name wins over "movie", next to the source.
    assert draft.naming.source == "folder"
    assert job.output.path == file.parent / "Movie.mkv"
    assert draft.naming.path == job.output.path
    assert job.output.naming.mode == "template"
    assert errors(draft.issues) == []
    assert "dimensions.crop_not_detected" in codes(draft.issues)


async def test_draft_with_another_preset_by_name_and_id(movie: tuple[Stubs, Path]) -> None:
    stubs, file = movie
    jobs = service(stubs)
    by_name = await jobs.draft(file, "fast 1080p30")
    by_id = await jobs.draft(file, "fast-1080p30")
    by_model = await jobs.draft(file, preset("fast-1080p30"))
    assert isinstance(by_name, JobDraft)
    assert isinstance(by_id, JobDraft)
    assert isinstance(by_model, JobDraft)
    assert by_name.job == by_id.job == by_model.job
    job = by_name.job
    assert job.preset_name == "Fast 1080p30"
    assert job.video.encoder == "libx264"
    assert job.output.container == "mp4"
    assert job.output.path == file.parent / "Movie.mp4"


async def test_unknown_preset_is_an_error_issue(movie: tuple[Stubs, Path]) -> None:
    stubs, file = movie
    draft = await service(stubs).draft(file, "No Such Preset")
    assert isinstance(draft, JobDraft)
    assert errors(draft.issues)[0] == "preset.not_found"
    assert draft.job.preset_id == "h265-mkv-1080p"


async def test_a_required_language_without_a_track_keeps_the_draft_out_of_the_queue(
    movie: tuple[Stubs, Path],
) -> None:
    """The track-stage error ("no listed language: take none") is a draft error; the
    subtitle decisions come with the draft too."""
    stubs, file = movie
    chosen = preset("h265-mkv-1080p").model_copy(deep=True)
    chosen.audio_defaults.selection.languages = ["fre"]
    chosen.audio_defaults.selection.no_match = "none"
    draft = await service(stubs).draft(file, chosen)
    assert isinstance(draft, JobDraft)
    assert "defaults.no_listed_language" in errors(draft.issues)
    assert draft.job.audio == []
    source = stubs.sources[file]
    assert len(draft.subtitle_decisions) == len(source.subtitles)


async def test_a_user_default_preset_is_used(movie: tuple[Stubs, Path]) -> None:
    stubs, file = movie
    stubs.default_id = "h264-mkv-1080p"
    draft = await service(stubs).draft(file)
    assert isinstance(draft, JobDraft)
    assert draft.job.video.encoder == "libx264"


async def test_naming_options_of_the_preset_win_over_settings(
    movie: tuple[Stubs, Path],
) -> None:
    stubs, file = movie
    stubs.settings.output.naming = NamingOptions(movie_template="{name}.settings")
    custom = preset("h265-mkv-1080p").model_copy(
        update={"id": "mine", "naming": NamingOptions(movie_template="{name} ({year})")}
    )
    from_settings = await service(stubs).draft(file)
    from_preset = await service(stubs).draft(file, custom)
    assert isinstance(from_settings, JobDraft)
    assert isinstance(from_preset, JobDraft)
    assert from_settings.job.output.path == file.parent / "Movie.settings.mkv"
    assert from_preset.job.output.path == file.parent / "Movie (2016).mkv"


async def test_output_size_feeds_the_template(movie: tuple[Stubs, Path]) -> None:
    stubs, file = movie
    stubs.settings.output.naming = NamingOptions(movie_template="{main_title}.{resolution}")
    draft = await service(stubs).draft(file, "h265-mkv-720p")
    assert isinstance(draft, JobDraft)
    size = output_size(draft.job, stubs.sources[file])
    assert size is not None
    assert size[1] <= 720
    assert draft.job.output.path == file.parent / "Movie.720p.mkv"


async def test_output_option_is_a_manual_name(movie: tuple[Stubs, Path], tmp_path: Path) -> None:
    stubs, file = movie
    jobs = service(stubs)
    out = tmp_path / "out" / "Custom name.mkv"
    out.parent.mkdir()
    draft = await jobs.draft(file, output=out)
    assert isinstance(draft, JobDraft)
    assert draft.job.output.path == out
    assert draft.job.output.naming.mode == "manual"
    assert draft.job.output.naming.manual_name == "Custom name.mkv"
    assert draft.naming.template_kind == "manual"
    assert draft.naming.relative_path == "Custom name.mkv"

    # Without an extension, the container's extension is added.
    bare = await jobs.draft(file, output=tmp_path / "out" / "bare")
    assert isinstance(bare, JobDraft)
    assert bare.job.output.path == tmp_path / "out" / "bare.mkv"

    # Another extension is kept, and validation warns about it.
    other = await jobs.draft(file, output=tmp_path / "out" / "file.mp4")
    assert isinstance(other, JobDraft)
    assert other.job.output.path == tmp_path / "out" / "file.mp4"
    assert "output.extension_mismatch" in codes(other.issues)


async def test_output_option_folder_gets_the_template_name(
    movie: tuple[Stubs, Path], tmp_path: Path
) -> None:
    stubs, file = movie
    folder = tmp_path / "encodes"
    folder.mkdir()
    draft = await service(stubs).draft(file, output=folder)
    assert isinstance(draft, JobDraft)
    assert draft.job.output.path == folder / "Movie.mkv"
    assert draft.job.output.naming.mode == "template"
    assert any(str(folder) in note for note in draft.notes)


async def test_a_name_that_is_the_source_gets_the_next_free_name(tmp_path: Path) -> None:
    folder = tmp_path / "media"
    folder.mkdir()
    file = folder / "multitrack.mkv"
    file.write_bytes(b"x")
    (folder / "multitrack (1).mkv").write_bytes(b"x")
    stubs = Stubs({file: recorded("multitrack", file)})
    draft = await service(stubs).draft(file)
    assert isinstance(draft, JobDraft)
    assert draft.naming.path == file  # the name is the source itself
    assert draft.job.output.path == folder / "multitrack (2).mkv"
    assert "source file itself" in draft.notes[0]
    assert "output.same_as_source" not in codes(draft.issues)


async def test_output_option_equal_to_the_source_is_an_error(tmp_path: Path) -> None:
    file = tmp_path / "multitrack.mkv"
    file.write_bytes(b"x")
    stubs = Stubs({file: recorded("multitrack", file)})
    draft = await service(stubs).draft(file, output=file)
    assert isinstance(draft, JobDraft)
    assert "output.same_as_source" in errors(draft.issues)


async def test_probe_error_is_returned(tmp_path: Path) -> None:
    outcome = await service(Stubs()).draft(tmp_path / "missing.mkv")
    assert isinstance(outcome, ProbeError)


async def test_draft_from_a_media_source_does_not_probe(movie: tuple[Stubs, Path]) -> None:
    stubs, file = movie
    draft = await service(stubs).draft(stubs.sources[file])
    assert isinstance(draft, JobDraft)
    assert stubs.probes == 0


@pytest.mark.parametrize(
    "probe", ["multitrack", "hdr10", "pgs", "dts-hd-ma", "phone-rotated", "vfr", "dv-p8"]
)
async def test_recorded_probes_draft_without_errors(tmp_path: Path, probe: str) -> None:
    file = tmp_path / "Show.S01E01.Title" / "source.mkv"
    file.parent.mkdir()
    file.write_bytes(b"x")
    stubs = Stubs({file: recorded(probe, file)})
    draft = await service(stubs).draft(file)
    assert isinstance(draft, JobDraft)
    assert errors(draft.issues) == []
    assert draft.job.video.metadata.default is True
    assert draft.job.output.path is not None
    assert len(draft.job.subtitles) == len(stubs.sources[file].subtitles)


async def test_a_source_without_video_has_an_error(tmp_path: Path) -> None:
    file = tmp_path / "song.mka"
    file.write_bytes(b"x")
    stubs = Stubs({file: recorded("cover-art", file)})  # audio with cover art, no video
    draft = await service(stubs).draft(file)
    assert isinstance(draft, JobDraft)
    assert errors(draft.issues) == ["source.no_video"]
    assert draft.job.video.metadata == preset("h265-mkv-1080p").video.metadata


def test_video_metadata_keeps_the_source_flags_and_sets_default(tmp_path: Path) -> None:
    source = recorded("multitrack", tmp_path / "x.mkv")
    stream = source.video[0].model_copy(deep=True)
    stream.language = "hun"
    stream.title = "Main"
    stream.disposition.default = False
    stream.disposition.original = True
    meta = video_metadata(stream)
    assert meta.language == "hu"
    assert meta.name == "Main"
    flags = TrackFlags.model_validate(meta.model_dump(include=set(TrackFlags.model_fields)))
    assert flags == TrackFlags(default=True, original=True)


def test_generated_chapter_names(tmp_path: Path) -> None:
    source = recorded("chapters", tmp_path / "x.mkv")
    assert source.chapters
    template = preset("h265-mkv-1080p").model_copy(update={"chapter_name_policy": "generated"})
    job, _decisions, notes = job_from_preset(source, template)
    assert job.chapters.names == [f"Chapter {i}" for i in range(1, len(source.chapters) + 1)]
    assert notes


async def test_unavailable_encoder_names_the_closest_one(movie: tuple[Stubs, Path]) -> None:
    stubs, file = movie
    stubs.snapshot = caps(
        unavailable={
            "hevc_nvenc": "NVIDIA driver not found",
            "hevc_qsv": "No Intel QSV device",
            "hevc_amf": "No AMD GPU",
        }
    )
    draft = await service(stubs).draft(file, "H.265 NVENC 1080p")
    assert isinstance(draft, JobDraft)
    issue = next(i for i in draft.issues if i.code == "encoder.unavailable")
    assert issue.severity is Severity.ERROR
    assert "NVIDIA driver not found" in issue.message
    assert issue.fixes[0].label.startswith("Use hevc_vaapi (closest match")
    plan = await service(stubs).plan(draft.job)
    assert isinstance(plan, list)
    assert "encoder.unavailable" in errors(plan)


async def test_validate_waits_for_detection(movie: tuple[Stubs, Path]) -> None:
    stubs, file = movie
    stubs.snapshot = checking()
    stubs.final = caps()
    draft = await service(stubs).draft(file)
    assert isinstance(draft, JobDraft)
    assert stubs.waits == 1
    assert "encoder.checking" not in codes(draft.issues)


async def test_validate_wait_is_bounded(movie: tuple[Stubs, Path]) -> None:
    stubs, file = movie
    stubs.snapshot = checking()
    stubs.gate = asyncio.Event()  # never set: a detection that does not end
    jobs = service(stubs, detection_wait=0.05)
    started = time.monotonic()
    draft = await jobs.draft(file)
    assert time.monotonic() - started < 5
    assert isinstance(draft, JobDraft)
    assert "encoder.checking" in codes(draft.issues)
    timeout = next(i for i in draft.issues if i.code == "encoder.detection_timeout")
    assert timeout.severity is Severity.INFO
    assert "0.05 s" in timeout.message
    assert errors(draft.issues) == []


async def test_no_wait_when_detection_is_not_running(movie: tuple[Stubs, Path]) -> None:
    stubs, file = movie
    snap = caps()
    # Hardware tests off: libplacebo stays untested, detection is over.
    stubs.snapshot = snap.model_copy(update={"untested_filters": ["libplacebo"]})
    await service(stubs).draft(file)
    assert stubs.waits == 0


async def test_detection_wait_default_is_read_at_creation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import reframe.jobs as jobs_module

    monkeypatch.setattr(jobs_module, "DETECTION_WAIT", 1.5)
    assert service(Stubs()).detection_wait == 1.5


async def test_plan_of_a_drafted_job(movie: tuple[Stubs, Path]) -> None:
    stubs, file = movie
    jobs = service(stubs)
    draft = await jobs.draft(file)
    assert isinstance(draft, JobDraft)
    plan = await jobs.plan(draft.job)  # probes the source again (the stub)
    assert isinstance(plan, EncodePlan)
    assert plan.output_final == file.parent / "Movie.mkv"
    assert plan.output_tmp == file.parent / "Movie.part.mkv"
    assert "libx265" in plan.display
    assert stubs.probes == 2


async def test_validate_and_plan_report_a_source_that_cannot_be_probed(
    movie: tuple[Stubs, Path],
) -> None:
    stubs, file = movie
    jobs = service(stubs)
    draft = await jobs.draft(file)
    assert isinstance(draft, JobDraft)
    del stubs.sources[file]
    assert errors(await jobs.validate(draft.job)) == ["source.probe_failed"]
    plan = await jobs.plan(draft.job)
    assert isinstance(plan, list)
    assert errors(plan) == ["source.probe_failed"]


async def test_plan_turns_a_builder_refusal_into_an_issue(
    movie: tuple[Stubs, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    import reframe.jobs as jobs_module
    from reframe.command import PlanError

    stubs, file = movie
    jobs = service(stubs)
    draft = await jobs.draft(file)
    assert isinstance(draft, JobDraft)

    def refuse(*_args: object, **_kw: object) -> EncodePlan:
        raise PlanError("no")

    monkeypatch.setattr(jobs_module, "build_plan", refuse)
    plan = await jobs.plan(draft.job, stubs.sources[file])
    assert isinstance(plan, list)
    assert errors(plan) == ["plan.failed"]


async def test_validate_uses_the_jobs_preset_naming(movie: tuple[Stubs, Path]) -> None:
    stubs, file = movie
    bad = preset("h265-mkv-1080p").model_copy(
        update={"id": "bad", "naming": NamingOptions(movie_template="{nme}")}
    )
    stubs.presets["bad"] = bad
    draft = await service(stubs).draft(file, bad)
    assert isinstance(draft, JobDraft)
    again = await service(stubs).validate(draft.job)
    assert "naming.unknown_variable" in codes(draft.issues)
    assert "naming.unknown_variable" in codes(again)


async def test_name_without_probing(tmp_path: Path) -> None:
    stubs = Stubs()
    folder = (
        tmp_path / "Hacksaw.Ridge.2016.HYBRID.2160p.UHD.BluRay.REMUX.TrueHD.7.1.Atmos-HenDerson"
    )
    result = await service(stubs).name(folder / "hacksawridge.2160p.remux-henderson.mkv")
    assert result.source == "folder"
    assert result.relative_path == "Hacksaw.Ridge.mkv"
    assert stubs.probes == 0
    templated = await service(stubs).name(
        folder / "hacksawridge.2160p.remux-henderson.mkv", template="{name} ({year})"
    )
    assert templated.relative_path == "Hacksaw.Ridge (2016).mkv"
    mp4 = await service(stubs).name(folder / "x.mkv", preset=preset("fast-1080p30"))
    assert mp4.extension == "mp4"


def test_find_media_files(tmp_path: Path) -> None:
    season = tmp_path / "Season 01"
    season.mkdir()
    for name in ("E10.mkv", "E2.mkv", "E1.MKV", ".hidden.mkv", "notes.txt", "E3.part.mkv"):
        (season / name).write_bytes(b"x")
    sub = season / "Extras"
    sub.mkdir()
    (sub / "extra.mp4").write_bytes(b"x")
    (tmp_path / "empty").mkdir()
    single = tmp_path / "single.avi"
    single.write_bytes(b"x")

    found = find_media_files(
        [season, single, season / "E2.mkv", tmp_path / "nope", tmp_path / "empty"]
    )
    assert [f.name for f in found.files] == ["E1.MKV", "E2.mkv", "E10.mkv", "single.avi"]
    assert found.missing == [tmp_path / "nope"]
    assert found.empty == [tmp_path / "empty"]
    deep = find_media_files([season], recursive=True)
    assert [f.name for f in deep.files] == ["E1.MKV", "E2.mkv", "E10.mkv", "extra.mp4"]
    # A file named explicitly is taken whatever its extension; ffprobe decides.
    assert find_media_files([season / "notes.txt"]).files == [season / "notes.txt"]


def test_partial_outputs() -> None:
    assert is_partial_output(Path("Movie.part.mkv"))
    assert is_partial_output(Path("Show S01E01 (1).part.mp4"))
    assert not is_partial_output(Path("Party.mkv"))
    assert not is_partial_output(Path("The.Part.Two.mkv"))


def test_output_size_of_a_deinterlaced_job_matches_the_builder(tmp_path: Path) -> None:
    """Deinterlace runs before the crop, so a deinterlacing job's crop is on the progressive
    grid: a 2-line manual crop stays 2 lines."""
    from reframe.command import build_plan
    from reframe.models import CropRect, CropSettings, FilterConfig, SameAsSource

    from .conftest import toolset

    source = recorded("interlaced", tmp_path / "interlaced.mkv")
    stream = source.video[0]
    job, _decisions, _notes = job_from_preset(source, preset("h265-mkv-1080p"))
    job.dimensions.crop = CropSettings(mode="manual", rect=CropRect(top=2))
    job.dimensions.size = SameAsSource()
    job.filters.root["deinterlace"] = FilterConfig()
    job.output.path = tmp_path / "out.mkv"
    assert output_size(job, source) == (stream.width, stream.height - 2)
    plan = build_plan(job, source, caps(), toolset())
    assert f"scale={stream.width}:{stream.height - 2}" in plan.display or (
        f"crop={stream.width}:{stream.height - 2}" in plan.display
    )
    # Without deinterlacing, the crop snaps to the field grid (4 lines for 4:2:0).
    del job.filters.root["deinterlace"]
    assert output_size(job, source) != (stream.width, stream.height - 2)


@pytest.mark.anyio
async def test_a_codec_the_container_cannot_hold_is_one_issue(tmp_path: Path) -> None:
    file = media_file(tmp_path / "Movie.2016.1080p.BluRay-GRP", "movie.mkv")
    stubs = Stubs({file: recorded("multitrack", file)})
    webm = preset("vp9-mkv-1080p").model_copy(deep=True)
    webm.output.container = "webm"
    webm.audio_defaults.codec_rules = [AudioCodecRule(codec="aac")]
    jobs = JobService(
        sources=stubs,
        presets=stubs,
        tools=stubs,
        capabilities=stubs,
        settings=lambda: stubs.settings,
    )
    draft = await jobs.draft(file, webm)
    assert isinstance(draft, JobDraft)
    codes = [issue.code for issue in draft.issues]
    assert "container.codec_unsupported" in codes
    assert "defaults.codec_not_in_container" not in codes
    # The pure engine without validation still reports it.
    explained = await jobs.explain(file, webm)
    assert isinstance(explained, TrackDraft)
    assert "defaults.codec_not_in_container" in [i.code for i in explained.issues]
