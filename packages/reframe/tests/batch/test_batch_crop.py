"""Crop detection for each file of a group before it is queued, on letterboxed copies of the
``letterbox`` fixture and the real FFmpeg."""

from __future__ import annotations

import asyncio
import shutil
from collections.abc import AsyncIterator, Callable
from pathlib import Path
from typing import Any

import pytest

from reframe.batch import service as batch_service
from reframe.mediatask import TaskFailed
from reframe.models import (
    CropRect,
    CropSettings,
    EncodePlan,
    JobSettings,
    JobState,
    JobTemplate,
    NamingOptions,
    Resolution,
)
from reframe.preview.crop import detect_crop
from reframe.service import Reframe
from reframe.tools import CancelToken

pytestmark = [pytest.mark.anyio, pytest.mark.needs_ffmpeg]

Media = Callable[[str], Path]
#: The letterbox fixture's bars (its first half; the automatic crop takes them).
LETTERBOX = CropRect(top=22, bottom=24)


@pytest.fixture
async def app(tmp_path: Path) -> AsyncIterator[Reframe]:
    async with await Reframe.create(
        tmp_path / "config", tmp_path / "data", cache_dir=tmp_path / "cache"
    ) as reframe:
        yield reframe


def episodes(fixture_media: Media, tmp_path: Path, count: int = 3) -> list[Path]:
    source = fixture_media("letterbox")
    folder = tmp_path / "media"
    folder.mkdir()
    files = []
    for n in range(1, count + 1):
        file = folder / f"Show.S01E{n:02d}.mkv"
        shutil.copy2(source, file)
        files.append(file)
    return files


def template(mode: str = "auto") -> JobTemplate:
    return JobTemplate.model_validate(
        {
            "dimensions": {"crop": {"mode": mode}, "size": {"mode": "source"}},
            "video": {"encoder": "libx264", "preset": "ultrafast"},
        }
    )


def crops(rows: list[Resolution]) -> list[CropSettings]:
    return [row.job.dimensions.crop for row in rows if row.job is not None]


def codes(row: Resolution) -> list[str]:
    return [issue.code for issue in row.issues]


async def test_each_file_gets_the_crop_detected_in_it(
    app: Reframe, fixture_media: Media, tmp_path: Path
) -> None:
    files = episodes(fixture_media, tmp_path)
    plain = await app.batch.resolve(template(), files)
    assert crops(plain.rows) == [CropSettings(mode="auto")] * 3
    assert all("dimensions.crop_not_detected" in codes(row) for row in plain.rows)

    told: list[tuple[str, int, int]] = []
    resolution = await app.batch.resolve(
        template(),
        files,
        detect_crop=True,
        progress=lambda path, n, total: told.append((path.name, n, total)),
    )
    assert told == [(f"Show.S01E0{n}.mkv", n, 3) for n in (1, 2, 3)]
    assert crops(resolution.rows) == [CropSettings(mode="auto", rect=LETTERBOX)] * 3
    for row in resolution.rows:
        assert row.status == "ok", row.issues
        assert "dimensions.crop_not_detected" not in codes(row)
        assert (
            "Crop: detected in this file (automatic): top 22, bottom 24, left 0, right 0."
            in row.notes
        )
    # The conservative crop keeps what is black on every frame: the pillarbox half has no bars
    # at the top and the letterbox half none at the sides.
    careful = await app.batch.resolve(template("conservative"), files[:1], detect_crop=True)
    assert crops(careful.rows) == [CropSettings(mode="conservative", rect=CropRect())]


async def test_a_detection_is_kept_and_a_manual_or_no_crop_is_not_measured(
    app: Reframe, fixture_media: Media, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    files = episodes(fixture_media, tmp_path, 2)
    calls: list[Path] = []

    async def counted(task: Any, media: Any, path: Path, *, count: int | None) -> Any:
        calls.append(path)
        return await detect_crop(task, media, path, count=count)

    monkeypatch.setattr(batch_service, "detect_crop", counted)
    first = await app.batch.resolve(template(), files, detect_crop=True)
    second = await app.batch.resolve(template(), files, detect_crop=True)
    assert calls == files
    assert crops(second.rows) == crops(first.rows)
    manual = template().model_copy(deep=True)
    manual.dimensions.crop = CropSettings(mode="manual", rect=CropRect(top=2))
    manual.crop_policy = "fixed"
    await app.batch.resolve(manual, files, detect_crop=True)
    await app.batch.resolve(template("none"), files, detect_crop=True)
    assert calls == files


async def test_a_failed_detection_is_a_warning_and_the_file_stays_uncropped(
    app: Reframe, fixture_media: Media, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    files = episodes(fixture_media, tmp_path, 1)

    async def failing(task: Any, media: Any, path: Path, *, count: int | None) -> Any:
        raise TaskFailed("Crop detection failed on every frame: 0.200 s: exit code 1.")

    monkeypatch.setattr(batch_service, "detect_crop", failing)
    (row,) = (await app.batch.resolve(template(), files, detect_crop=True)).rows
    assert row.status == "warning"
    assert row.job is not None
    assert row.job.dimensions.crop == CropSettings(mode="auto")
    (issue,) = [i for i in row.issues if i.code == "batch.crop_not_detected"]
    assert issue.message == (
        "The crop of this file could not be detected, so it is not cropped: Crop detection "
        "failed on every frame: 0.200 s: exit code 1."
    )


async def test_a_cancelled_detection_stops_the_resolution(
    app: Reframe, fixture_media: Media, tmp_path: Path
) -> None:
    files = episodes(fixture_media, tmp_path, 2)
    token = CancelToken()
    token.cancel()
    with pytest.raises(asyncio.CancelledError):
        await app.batch.resolve(template(), files, detect_crop=True, cancel=token)


async def test_an_earlier_run_named_after_the_detected_crop_is_left_out(
    app: Reframe, fixture_media: Media, tmp_path: Path
) -> None:
    """The crop changes ``{height}``: the earlier outputs are found by the names that the
    detected crop gives, in a whole batch and in a group's run (the web's *Add group to
    queue*)."""
    files = episodes(fixture_media, tmp_path)
    named = template().model_copy(deep=True)
    named.naming = NamingOptions(episode_template="{main_title} {height}p")
    _, (first,) = await app.batch.resolve_batch(named, files, detect_crop=True)
    jobs = [row.job for row in first.rows if row.job is not None]
    outputs = [job.output.path for job in jobs]
    assert [path.name for path in outputs if path is not None] == [
        f"Show.S01E0{n} 134p.mkv" for n in (1, 2, 3)
    ]
    ids = [(await app.queue.add(job)).id for job in jobs]
    app.queue.start(job_ids=ids)
    assert [job.state for job in await app.queue.wait(ids)] == [JobState.DONE] * 3

    def already_encoded(rows: list[Resolution]) -> None:
        assert [row.path for row in rows] == files
        for row in rows:
            (issue,) = [i for i in row.issues if i.code == "batch.output_is_source"]
            assert "left out as already encoded" in issue.message

    every = sorted(files[0].parent.iterdir())
    grouping, resolutions = await app.batch.resolve_batch(named, every, detect_crop=True)
    left_out = [issue for issue in grouping.issues if issue.code == "batch.already_encoded"]
    assert len(left_out) == 3
    already_encoded([row for resolution in resolutions for row in resolution.rows])

    (group,) = (await app.batch.group(every)).groups
    members = [member.path for member in group.members]
    _, runs = await app.batch.resolve_batch(named, members, detect_crop=True)
    already_encoded([row for run in runs for row in run.rows])


async def test_a_whole_batch_is_measured_and_queued_cropped(
    app: Reframe, fixture_media: Media, tmp_path: Path
) -> None:
    files = episodes(fixture_media, tmp_path)
    told: list[int] = []
    grouping, (resolution,) = await app.batch.resolve_batch(
        template(), files, detect_crop=True, progress=lambda _p, n, _t: told.append(n)
    )
    assert len(grouping.groups) == 1
    assert told == [1, 2, 3]
    jobs: list[JobSettings] = [row.job for row in resolution.rows if row.job is not None]
    assert [job.dimensions.crop.rect for job in jobs] == [LETTERBOX] * 3
    for job in jobs:
        plan = await app.jobs.plan(job)
        assert isinstance(plan, EncodePlan), plan
        assert "crop=320:134:0:22" in plan.display
