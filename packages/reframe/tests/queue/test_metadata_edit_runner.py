"""The runner's checks before an in-place metadata edit (decision 0034: the one exception to
"a job never writes its source", and nothing else): ``reframe.queue.runner._in_place_refusal``,
and that an in-place outcome hands the queue no plan to clean up."""

from __future__ import annotations

import shutil
from collections.abc import Callable
from pathlib import Path

import pytest

from reframe.command import build_plan
from reframe.metadata import remux_job
from reframe.models import EncodePlan, JobSettings, JobState, MediaSource, PlanFile, SourceRef
from reframe.queue import files
from reframe.queue.runner import _in_place_refusal

from .conftest import Harness, all_caps, recorded, tool_set


@pytest.fixture
def copy(tmp_path: Path, fixture_media: Callable[[str], Path]) -> Path:
    path = tmp_path / "media" / "Show.mkv"
    path.parent.mkdir()
    shutil.copyfile(fixture_media("multitrack"), path)
    return path


def plan_for(path: Path) -> tuple[EncodePlan, MediaSource]:
    source = recorded("multitrack.mkv", path)
    job = remux_job(JobSettings(source=SourceRef(path=path)), source)
    job.audio[0].metadata.name = "Renamed"
    tools = tool_set(Path("/usr/bin/ffmpeg"), mkvpropedit=Path("/usr/bin/mkvpropedit"))
    plan = build_plan(job, source, all_caps(), tools)
    assert plan.job_type == "metadata_edit"
    return plan, source


@pytest.mark.needs_ffmpeg
def test_a_plan_that_edits_only_its_source_is_accepted(copy: Path) -> None:
    plan, source = plan_for(copy)
    assert _in_place_refusal(plan, copy, source) is None
    # Another spelling of the same file is the same file.
    assert _in_place_refusal(plan, copy.parent / ".." / "media" / "Show.mkv", source) is None


@pytest.mark.needs_ffmpeg
@pytest.mark.parametrize(
    "change",
    [
        lambda p, d: p.files.append(PlanFile(path=d / "x.txt", content="")),
        lambda p, d: p.temp_files.append(d / "x.log"),
        lambda p, d: setattr(p, "output_tmp", d / "Show.part.mkv"),
        lambda p, d: setattr(p, "output_final", d / "Other.mkv"),
        lambda p, d: setattr(p.steps[0], "tool", "ffmpeg"),
        lambda p, d: setattr(p.steps[0], "kind", "encode"),
        lambda p, d: p.steps[0].argv.__setitem__(0, str(d / "Other.mkv")),
        lambda p, d: setattr(p.steps[0], "argv", []),
    ],
)
def test_anything_else_is_refused(copy: Path, change: Callable[[EncodePlan, Path], None]) -> None:
    plan, source = plan_for(copy)
    change(plan, copy.parent)
    refusal = _in_place_refusal(plan, copy, source)
    assert refusal is not None
    assert refusal[0] == "queue.writes_source"


@pytest.mark.needs_ffmpeg
def test_a_source_that_cannot_be_written_is_refused(
    copy: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plan, source = plan_for(copy)
    monkeypatch.setattr(files, "writable_file", lambda path: False)
    assert _in_place_refusal(plan, copy, source) == (
        "inplace.source_not_writable",
        "Show.mkv cannot be written (read-only, or no permission), so its metadata cannot be "
        "edited in place. Nothing was changed.",
    )


@pytest.mark.needs_ffmpeg
def test_tracks_that_do_not_match_the_probe_are_refused(copy: Path) -> None:
    plan, source = plan_for(copy)
    source.subtitles.pop()
    assert _in_place_refusal(plan, copy, source) == (
        "inplace.tracks_mismatch",
        "Show.mkv has 1 video, 3 audio, 3 subtitle tracks, but its probe shows 1 video, "
        "3 audio, 2 subtitle streams: the tracks to edit cannot be told apart. Nothing was "
        "changed.",
    )


def test_a_file_that_is_not_matroska_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "Show.mkv"
    path.write_bytes(b"not matroska")
    plan, source = plan_for(path)
    refusal = _in_place_refusal(plan, path, source)
    assert refusal is not None
    assert refusal[0] == "inplace.tracks_mismatch"
    assert "cannot be read (not an EBML file)" in refusal[1]


def test_an_empty_plan_needs_no_checks(tmp_path: Path) -> None:
    path = tmp_path / "Show.mkv"
    path.write_bytes(b"")
    plan, source = plan_for(path)
    plan.steps = []
    assert _in_place_refusal(plan, path, source) is None


def test_writable_file(tmp_path: Path) -> None:
    path = tmp_path / "f"
    assert not files.writable_file(path)
    path.write_bytes(b"")
    assert files.writable_file(path)
    assert not files.writable_file(tmp_path)


@pytest.mark.anyio
async def test_a_refused_in_place_job_fails_and_cleans_nothing(harness: Harness) -> None:
    """Through the queue with the recorded probe: the source is not a real Matroska file, so
    the track check refuses the edit; the source stays, nothing is removed."""
    h = harness
    h.tools.tools = tool_set(h.fake.ffmpeg, mkvpropedit=h.fake.ffmpeg)
    job = remux_job(JobSettings(source=SourceRef(path=h.source_path)), h.sources.source)
    job.audio[0].metadata.name = "Renamed"
    before = h.source_path.read_bytes()
    ended = await h.run_one(job)
    assert ended.state is JobState.FAILED
    assert ended.error is not None
    assert ended.error.startswith("The Matroska track headers of Movie.Source.mkv cannot be read")
    assert [i.code for i in ended.issues][-1] == "inplace.tracks_mismatch"
    assert h.source_path.read_bytes() == before
    assert h.fake.invocations() == []  # mkvpropedit never ran
    assert "Clean-up" not in h.log_text(ended.id)
