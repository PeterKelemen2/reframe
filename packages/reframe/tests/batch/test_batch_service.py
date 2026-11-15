"""``Reframe.batch`` through the facade, on the generated anime seasons and the real ffprobe."""

from __future__ import annotations

import importlib.util
import shutil
import sys
from collections.abc import AsyncIterator, Callable
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
from pydantic import TypeAdapter

from reframe.models import (
    JobDraft,
    JobSettings,
    JobState,
    JobTemplate,
    JsonPatchOp,
    MediaSource,
    NamingOptions,
    Preset,
    Resolution,
)
from reframe.service import Reframe
from reframe_testing import media

pytestmark = [pytest.mark.anyio, pytest.mark.needs_ffmpeg]

Media = Callable[[str], Path]
OPS = TypeAdapter(list[JsonPatchOp])


def _load(name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        f"_reframe_batch_{name}", Path(__file__).with_name(f"{name}.py")
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


A = _load("anime")


@pytest.fixture
async def app(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[Reframe]:
    async with await Reframe.create(
        tmp_path / "config", tmp_path / "data", cache_dir=tmp_path / "cache"
    ) as reframe:
        yield reframe


def season(fixture_media: Media, tmp_path: Path, number: int, *episodes: int) -> list[Path]:
    """A copy of the season's folder under ``tmp_path`` (only ``episodes``, default all).

    The queue and the name checks then see only this test's files.
    """
    source = fixture_media(f"anime-s{number:02d}")
    folder = tmp_path / "media" / source.name
    folder.mkdir(parents=True, exist_ok=True)
    count = len(media.ANIME_TITLES[number])
    files = []
    for n in episodes or range(1, count + 1):
        name = media.anime_file_name(number, n)
        shutil.copy2(source / name, folder / name)
        files.append(folder / name)
    return files


async def example_template(app: Reframe, e01: Path) -> tuple[JobTemplate, MediaSource]:
    """The group template: E01's draft with the example's audio and subtitles, and its naming."""
    source = await app.sources.probe(e01)
    assert isinstance(source, MediaSource)
    draft = await app.jobs.draft(source)
    assert isinstance(draft, JobDraft)
    job = A.example_job(source)  # the same edit, on the same preset's draft
    assert [t.source_stream for t in job.audio] == [t.source_stream for t in draft.job.audio]
    template = app.batch.derive(
        draft.job.model_copy(update={"audio": job.audio, "subtitles": job.subtitles}),
        source,
        {"audio", "subtitles"},
    )
    template = app.batch.merge(template, JobTemplate(naming=A.EXAMPLE_NAMING), {"naming"})
    return template, source


async def test_a_season_from_grouping_to_the_queue_and_its_preset_on_season_2(
    app: Reframe, fixture_media: Media, tmp_path: Path
) -> None:
    files = season(fixture_media, tmp_path, 1)
    grouping = await app.batch.group(list(reversed(files)))
    assert grouping.issues == []
    (group,) = grouping.groups
    assert (group.name, group.level, len(group.members)) == ("Anime Show S01", "standard", 12)
    assert group.representative == files[0]

    template, _e01 = await example_template(app, group.representative)
    resolution = await app.batch.resolve(template, [m.path for m in group.members], group=group)
    assert [c.label for c in resolution.columns] == [
        "V",
        "A1 jpn TrueHD→Opus 5.1",
        "A2 eng DTS-HD MA→AC-3 5.1",
        "S1 eng Signs & Songs",
        "S2 eng Full",
        "Output name",
    ]
    statuses = [row.status for row in resolution.rows]
    assert statuses == ["ok"] * 4 + ["warning"] + ["ok"] * 5 + ["error", "ok"]
    e05, e11 = resolution.rows[4], resolution.rows[10]
    assert [i.code for i in e05.issues if i.severity.value == "warning"] == ["batch.near_match"]
    assert e05.issues[0].message == (
        'Near match of the group: 1 extra track (eng AC-3 2.0 "Commentary").'
    )
    assert [(m.status, m.streams) for m in e11.matches] == [
        ("exact", [1]),
        ("missing", []),
        ("relaxed", [2]),
        ("exact", [3]),
    ]
    assert all(m.status == "exact" for r in resolution.rows if r is not e11 for m in r.matches)
    names = [r.job.output.path for r in resolution.rows if r.job is not None]
    assert [p.name for p in names if p is not None][:2] == [
        "Anime Show - S01E01 - Pilot.mkv",
        "Anime Show - S01E02 - Departure.mkv",
    ]
    assert all(r.naming is not None and r.naming.source == "file" for r in resolution.rows)
    assert resolution.issues == []

    # E11: the dub is optional for this file (a per-file override) → every file can be queued.
    skip = {
        str(files[10]): OPS.validate_python(
            [{"op": "replace", "path": "/audio_rules/1/required", "value": False}]
        )
    }
    resolution = await app.batch.resolve(
        template, [m.path for m in group.members], group=group, overrides=skip
    )
    assert [row.status for row in resolution.rows].count("error") == 0
    queued = []
    for row in resolution.rows:
        assert row.job is not None
        job = await app.queue.add(row.job)
        assert job.state is JobState.WAITING, job.issues
        queued.append(job)
    assert len(queued) == 12
    assert [j.settings.output.path.name for j in queued if j.settings.output.path][10] == (
        "Anime Show - S01E11 - Static.mkv"
    )

    saved = await app.batch.save_preset(template, "Anime Show", description="The example season")
    assert isinstance(saved, Preset)
    assert (saved.category, saved.audio_rules) == ("Custom", template.audio_rules)
    s02 = season(fixture_media, tmp_path, 2)
    second = await app.batch.group(s02)
    (group2,) = second.groups
    applied = await app.batch.resolve("anime show", s02, group=group2)
    assert [row.status for row in applied.rows] == ["ok"] * 3
    assert all(m.status == "exact" for row in applied.rows for m in row.matches)
    assert [r.job.output.path.name for r in applied.rows if r.job and r.job.output.path] == [
        "Anime Show - S02E01 - Return.mkv",
        "Anime Show - S02E02 - Ashes.mkv",
        "Anime Show - S02E03 - Northbound.mkv",
    ]
    assert all(r.job is not None and r.job.preset_id == saved.id for r in applied.rows)


async def test_files_that_cannot_be_read(
    app: Reframe, fixture_media: Media, tmp_path: Path
) -> None:
    files = season(fixture_media, tmp_path, 2, 1, 2)
    broken = files[0].with_name("broken.mkv")
    broken.write_bytes(b"not a video")
    grouping = await app.batch.group([*files, broken, files[0]])
    (group,) = grouping.groups
    assert len(group.members) == 2  # files[0] given twice: once
    (issue,) = grouping.issues
    assert (issue.code, issue.severity.value) == ("source.probe_failed", "error")
    assert issue.message.startswith("broken.mkv cannot be read")
    resolution = await app.batch.resolve(None, [broken, *files])
    assert [r.path.name for r in resolution.rows] == [f.name for f in files] + ["broken.mkv"]
    assert resolution.rows[-1].status == "error"
    assert resolution.rows[-1].job is None


async def test_the_default_preset_and_an_unknown_preset(
    app: Reframe, fixture_media: Media, tmp_path: Path
) -> None:
    files = season(fixture_media, tmp_path, 2, 1)
    default = await app.batch.resolve(None, files)
    assert [c.label for c in default.columns] == [
        "V",
        "A1 every track (defaults)",
        "S1 every track (defaults)",
        "Output name",
    ]
    (row,) = default.rows
    assert row.status == "ok"
    assert row.job is not None
    assert row.job.preset_id == "h265-mkv-1080p"
    assert [m.streams for m in row.matches] == [[1, 2], [3, 4]]
    unknown = await app.batch.resolve("No Such Preset", files)
    assert [i.code for i in unknown.issues] == ["preset.not_found"]
    assert unknown.rows[0].status == "error"
    assert unknown.rows[0].issues[0].code == "preset.not_found"


async def test_name_collisions(app: Reframe, fixture_media: Media, tmp_path: Path) -> None:
    files = season(fixture_media, tmp_path, 2)
    template, _ = await example_template(app, files[0])
    same = template.model_copy(
        update={"naming": NamingOptions(movie_template="{name}", episode_template="{name}")}
    )
    resolution = await app.batch.resolve(same, files)
    assert [r.status for r in resolution.rows] == ["error"] * 3
    (batch_issue,) = resolution.issues
    assert batch_issue.code == "batch.name_collision"
    assert (
        batch_issue.message == "3 files get the output name Anime.Show.mkv: S02E01, S02E02, S02E03."
    )
    first = [i for i in resolution.rows[0].issues if i.code == "batch.name_collision"]
    assert first[0].message.startswith("Anime.Show.mkv is also the output name of S02E02, S02E03")

    # An output that exists already (Settings: auto-rename) is an error in a batch.
    (files[0].parent / "Anime Show - S02E01 - Return.mkv").write_bytes(b"done before")
    resolution = await app.batch.resolve(template, files)
    assert [r.status for r in resolution.rows] == ["error", "ok", "ok"]
    codes = [i.code for i in resolution.rows[0].issues]
    assert "output.renamed" in codes
    (exists,) = [i for i in resolution.rows[0].issues if i.code == "batch.output_exists"]
    assert exists.message == (
        "Anime Show - S02E01 - Return.mkv already exists. In a batch an existing output is an "
        "error: remove it, or set the collision setting to overwrite."
    )


async def test_an_output_that_is_another_source(
    app: Reframe, fixture_media: Media, tmp_path: Path
) -> None:
    files = season(fixture_media, tmp_path, 2)
    template, _ = await example_template(app, files[0])
    stem = files[1].stem  # every output gets E02's own name
    fixed = template.model_copy(
        update={"naming": NamingOptions(movie_template=stem, episode_template=stem)}
    )
    resolution = await app.batch.resolve(fixed, files)
    e01, e02, e03 = resolution.rows
    assert e02.job is not None
    assert e02.job.output.path is not None
    assert e02.job.output.path.name == f"{stem} (1).mkv"  # its own source: the next free name
    assert "batch.output_is_source" in [i.code for i in e01.issues]
    assert "batch.output_is_source" in [i.code for i in e03.issues]
    assert "batch.output_is_source" not in [i.code for i in e02.issues]


async def test_derive_merge_and_overrides_by_path_text(
    app: Reframe, fixture_media: Media, tmp_path: Path
) -> None:
    files = season(fixture_media, tmp_path, 2)
    source = await app.sources.probe(files[0])
    assert isinstance(source, MediaSource)
    draft = await app.jobs.draft(source, "H.264 MKV 1080p")
    assert isinstance(draft, JobDraft)
    derived = app.batch.derive(draft.job, source, {"video"})
    assert derived.video.encoder == "libx264"  # the job's preset is the base
    assert derived.audio_rules == []
    orphan = draft.job.model_copy(update={"preset_id": None})
    assert app.batch.derive(orphan, source, {"audio"}).video.encoder == "libx265"  # default preset
    merged = app.batch.merge(JobTemplate(), derived, {"video"})
    assert merged.video == derived.video
    # Overrides are found by the file's path, however it is written.
    key = str(files[1].parent / ".." / files[1].parent.name / files[1].name)
    patch = {
        key: OPS.validate_python([{"op": "replace", "path": "/video/preset", "value": "veryslow"}])
    }
    resolution = await app.batch.resolve(derived, files, overrides=patch)
    presets = [r.job.video.preset for r in resolution.rows if r.job is not None]
    assert presets[1] == "veryslow"
    assert presets[0] != "veryslow"


async def test_a_check_sees_each_resolved_job_before_it_is_named_or_validated(
    app: Reframe, fixture_media: Media, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The server refuses a job whose patch brings in a path outside its roots: nothing may
    look at that job's files before the check has seen it, with the overrides applied."""
    files = season(fixture_media, tmp_path, 2, 1)
    patch = {
        str(files[0]): OPS.validate_python(
            [{"op": "replace", "path": "/video/preset", "value": "veryslow"}]
        )
    }
    named: list[JobSettings] = []
    real = app.jobs.name_job

    async def name_job(job: JobSettings, *args: Any, **kwargs: Any) -> Any:
        named.append(job)
        return await real(job, *args, **kwargs)

    monkeypatch.setattr(app.jobs, "name_job", name_job)
    checked: list[str] = []

    def refuse(job: JobSettings) -> None:
        checked.append(job.video.preset or "")
        raise PermissionError(job.source.path)

    with pytest.raises(PermissionError):
        await app.batch.resolve(None, files, overrides=patch, check=refuse)
    with pytest.raises(PermissionError):
        await app.batch.resolve_batch(None, files, overrides=patch, check=refuse)
    assert checked == ["veryslow", "veryslow"]
    assert named == []


async def test_a_naming_edit_on_a_base_without_naming_keeps_the_settings_output_folder(
    app: Reframe, fixture_media: Media, tmp_path: Path
) -> None:
    out = tmp_path / "out"
    result = await app.settings.update(
        [
            {"op": "replace", "path": "/output/naming/output_folder_mode", "value": "fixed"},
            {"op": "replace", "path": "/output/naming/output_folder", "value": str(out)},
        ]
    )
    assert result.ok
    files = season(fixture_media, tmp_path, 1)
    source = await app.sources.probe(files[0])
    assert isinstance(source, MediaSource)
    draft = await app.jobs.draft(source, None)
    assert isinstance(draft, JobDraft)
    job = draft.job.model_copy(deep=True)
    job.output.naming.template = "{name} - S{season:02}E{episode:02}"
    base = JobTemplate()  # as a preset without naming of its own
    derived = app.batch.derive(job, source, {"naming"}, base=base)
    assert derived.naming is not None
    assert derived.naming.movie_template == "{name} - S{season:02}E{episode:02}"
    assert (derived.naming.output_folder_mode, derived.naming.output_folder) == ("fixed", out)
    # Other sections leave a template without naming as it is: it follows the settings.
    assert app.batch.derive(job, source, {"video"}, base=base).naming is None
    # So does a naming section from a job without naming of its own.
    assert app.batch.derive(draft.job, source, {"naming"}, base=base).naming is None


def output_path(path: Path) -> list[JsonPatchOp]:
    """A file's override that sets its output path."""
    return OPS.validate_python([{"op": "replace", "path": "/job/output/path", "value": str(path)}])


def codes(row: Resolution) -> list[str]:
    return [issue.code for issue in row.issues]


async def test_an_output_path_set_by_a_files_override_is_kept(
    app: Reframe, fixture_media: Media, tmp_path: Path
) -> None:
    files = season(fixture_media, tmp_path, 2)
    template, _ = await example_template(app, files[0])
    (files[0].parent / "Anime Show - S02E01 - Return.mkv").write_bytes(b"done before")
    first = (await app.batch.resolve(template, files)).rows[0]
    (renamed,) = [i for i in first.issues if i.code == "output.renamed"]
    (fix,) = renamed.fixes
    override = [op.model_copy(update={"path": "/job" + op.path}) for op in fix.patch]
    resolution = await app.batch.resolve(template, files, overrides={str(files[0]): override})
    row = resolution.rows[0]
    assert row.job is not None
    assert row.job.output.path == files[0].parent / "Anime Show - S02E01 - Return (1).mkv"
    assert "batch.output_exists" not in codes(row)
    assert row.status == "ok"
    assert row.naming is not None
    assert row.naming.fields.episode == 1  # the name fields are still the file's


@pytest.mark.parametrize("run", [False, True])
async def test_output_paths_set_by_overrides_are_checked_in_the_batch(
    app: Reframe, fixture_media: Media, tmp_path: Path, run: bool
) -> None:
    files = season(fixture_media, tmp_path, 2)
    template, _ = await example_template(app, files[0])
    shared = tmp_path / "out" / "same.mkv"
    overrides = {
        str(files[0]): output_path(shared),
        str(files[1]): output_path(shared),
        str(files[2]): output_path(files[0]),
    }
    if run:
        _, (resolution,) = await app.batch.resolve_batch(template, files, overrides=overrides)
    else:
        resolution = await app.batch.resolve(template, files, overrides=overrides)
    e01, e02, e03 = resolution.rows
    assert [row.path for row in resolution.rows] == files  # E01 is not left out as an output
    assert "batch.name_collision" in codes(e01)
    assert "batch.name_collision" in codes(e02)
    assert "batch.output_is_source" in codes(e03)
