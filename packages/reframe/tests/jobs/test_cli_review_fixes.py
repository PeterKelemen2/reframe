"""``reframe batch``, ``encode`` and ``plan``: output name checks, season labels and warnings."""

from __future__ import annotations

import asyncio
import hashlib
import json
import shutil
from collections.abc import Callable
from pathlib import Path

import pytest

from reframe.batch import service as batch_service
from reframe.batch.grouping import episode_key
from reframe.batch.service import BatchService
from reframe.cli import DRY_RUN_NOTE, EXIT_FAILED, EXIT_OK
from reframe.jobs import JobService
from reframe.models import (
    AppSettings,
    AudioCodecRule,
    JobDraft,
    JobTemplate,
    Preset,
    Resolution,
    Severity,
    TrackDraft,
    ValidationIssue,
)
from reframe.probe import mediainfo
from reframe_testing import fake_tools as ft
from reframe_testing import media

from .conftest import Stubs, invoke, media_file, preset, recorded, replay
from .test_cli_batch import A, Queues, import_demo_preset, queues  # noqa: F401
from .test_cli_plan_dry_run import CUSTOM, DryRun, dry_run, movie  # noqa: F401

Media = Callable[[str], Path]
S01 = media.anime_folder(1)
E01 = media.anime_file_name(1, 1)
#: E01's output with the default preset (H.265 MKV 1080p, Settings → Output naming).
E01_OUT = "Anime.Show.S01E01.Pilot.mkv"
WEB = "Anime.Show.S01E01.Pilot.WEB.x264-GRP.mkv"


def anime(season: int, episode: int) -> str:
    """The recorded probe of an episode (``probe_json`` name)."""
    return f"{media.anime_folder(season)}/{media.anime_file_name(season, episode)[:-4]}"


def write_settings(tmp_path: Path, **output: object) -> None:
    settings = AppSettings()
    settings.output = settings.output.model_copy(update=output)
    folder = tmp_path / "config"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "settings.json").write_text(settings.model_dump_json(), encoding="utf-8")


def two_sources(cli_env: ft.FakeTools, tmp_path: Path, other: str) -> tuple[Path, Path, Path]:
    """E01 of season 1 and ``other`` (a file of another layout: the ``multitrack`` recording)
    in one folder."""
    folder = tmp_path / "media" / S01
    e01 = media_file(folder, E01)
    second = media_file(folder, other)
    replay(cli_env, "multitrack", per_file={e01: anime(1, 1), second: "multitrack"})
    return folder, e01, second


def outputs_of(made: Queues) -> list[Path | None]:
    return [job.settings.output.path for q in made.made for job in q.list()]


def test_batch_never_writes_a_file_of_another_group(
    cli_env: ft.FakeTools,
    queues: Queues,  # noqa: F811
    tmp_path: Path,
) -> None:
    """With the collision setting *overwrite*, E01's job would otherwise replace that file."""
    write_settings(tmp_path, collision="overwrite")
    folder, _e01, copy = two_sources(cli_env, tmp_path, E01_OUT)
    result = invoke("batch", str(folder), "--dry-run")
    assert result.exit_code == EXIT_FAILED, result.output
    out = result.stdout.splitlines()
    assert "Already encoded (left out of the batch)" in out
    assert any(f"{E01_OUT} is the planned output of {E01}" in line for line in out)
    assert "Group 1 of 1: Anime Show S01 · 1 file · standard match" in out
    assert any("[batch.output_is_source · output.path]" in line for line in out)
    assert not any("[output.overwrite" in line for line in out)
    assert out[-1] == (
        "Dry run: 0 of 1 file can be queued; 1 cannot (errors); 1 left out (already encoded)."
    )
    result = invoke("batch", str(folder))
    assert result.exit_code == EXIT_FAILED, result.output
    assert "Nothing to encode." in result.stdout
    assert copy not in outputs_of(queues)
    assert copy.read_bytes() == b"placeholder"


def test_batch_two_outputs_with_one_name_in_two_groups(
    cli_env: ft.FakeTools, tmp_path: Path
) -> None:
    folder, _e01, _web = two_sources(cli_env, tmp_path, WEB)
    result = invoke("batch", str(folder), "--dry-run")
    assert result.exit_code == EXIT_FAILED, result.output
    out = result.stdout.splitlines()
    assert out.count("Group 1 of 2: Anime Show S01 · 1 file · standard match") == 1
    collisions = [line for line in out if "[batch.name_collision · output.path]" in line]
    assert len(collisions) == 3  # one per row, one for the batch
    assert any(f"2 files get the output name {E01_OUT}: {E01}, {WEB}." in line for line in out)
    assert out[-1] == "Dry run: 0 of 2 files can be queued; 2 cannot (errors)."


def test_batch_json_has_the_left_out_files(cli_env: ft.FakeTools, tmp_path: Path) -> None:
    folder, _e01, copy = two_sources(cli_env, tmp_path, E01_OUT)
    result = invoke("batch", str(folder), "--dry-run", "--json")
    assert result.exit_code == EXIT_FAILED, result.output
    data = json.loads(result.stdout)
    (issue,) = data["grouping"]["issues"]
    assert (issue["code"], issue["severity"]) == ("batch.already_encoded", "info")
    (resolution,) = data["resolutions"]
    (row,) = resolution["rows"]
    assert row["status"] == "error"
    assert "batch.output_is_source" in [i["code"] for i in row["issues"]]
    assert str(copy) not in json.dumps(data["grouping"]["groups"])


def test_encode_never_writes_another_file_of_the_command(
    cli_env: ft.FakeTools,
    queues: Queues,  # noqa: F811
    tmp_path: Path,
) -> None:
    write_settings(tmp_path, collision="overwrite")
    folder, _e01, copy = two_sources(cli_env, tmp_path, E01_OUT)
    result = invoke("encode", str(folder))
    assert result.exit_code == EXIT_FAILED, result.output
    out = result.stdout
    assert f"[1/2] {E01} → {copy}" in out
    assert f"[2/2] {E01_OUT} → {folder / 'Anime.Show.S01E01.Pilot (1).mkv'}" in out
    assert "[batch.output_is_source · output.path]" in out
    assert f"The output {E01_OUT} is a source file of this command ([2/2] {E01_OUT})" in out
    assert copy not in outputs_of(queues)
    assert out.splitlines()[-1] == "Summary: 1 done, 0 failed, 0 cancelled, 1 not queued."


def test_encode_two_outputs_with_one_name(
    cli_env: ft.FakeTools,
    queues: Queues,  # noqa: F811
    tmp_path: Path,
) -> None:
    """The second file is not queued: its output would replace the first's."""
    folder, _e01, _web = two_sources(cli_env, tmp_path, WEB)
    result = invoke("encode", str(folder))
    assert result.exit_code == EXIT_FAILED, result.output
    out = result.stdout
    assert "[batch.name_collision · output.path]" in out
    assert f"{E01_OUT} is also the output of [1/2] {E01} in this command" in out
    assert [p.name if p else None for p in outputs_of(queues)] == [E01_OUT]
    assert out.splitlines()[-1] == "Summary: 1 done, 0 failed, 0 cancelled, 1 not queued."


def test_a_rerun_queues_only_the_episodes_not_done_yet(
    cli_env: ft.FakeTools,
    queues: Queues,  # noqa: F811
    tmp_path: Path,
) -> None:
    """E01 and E02 were encoded by an earlier run (their outputs are in the season folder,
    with another layout)."""
    folder = tmp_path / "media" / S01
    done = [
        media_file(folder, "Anime Show - S01E01 - Pilot.mkv"),
        media_file(folder, "Anime Show - S01E02 - Departure.mkv"),
    ]
    per_file = {media_file(folder, media.anime_file_name(1, n)): anime(1, n) for n in range(1, 13)}
    per_file.update(dict.fromkeys(done, "multitrack"))
    replay(cli_env, anime(1, 1), per_file=per_file)
    import_demo_preset()
    result = invoke("batch", str(folder), "--preset", A.PRESET_NAME, "--dry-run")
    assert result.exit_code == EXIT_FAILED, result.output
    out = result.stdout.splitlines()
    left = out.index("Already encoded (left out of the batch)")
    assert "Group 1 of 1: Anime Show S01 · 12 files · standard match" in out
    assert sum("[batch.already_encoded · source]" in line for line in out[left:]) == 2
    assert out[-1] == (
        "Dry run: 10 of 12 files can be queued; 2 cannot (errors); 2 left out (already encoded)."
    )
    result = invoke("batch", str(folder), "--preset", A.PRESET_NAME)
    assert result.exit_code == EXIT_FAILED, result.output
    assert "Queued 10 jobs." in result.stdout
    (queue,) = queues.made
    sources = [job.settings.source.path for job in queue.list()]
    assert not set(done) & set(sources)
    assert [p.name for p in sources][:2] == [
        media.anime_file_name(1, 3),
        media.anime_file_name(1, 4),
    ]
    assert result.stdout.splitlines()[-1] == (
        "Summary: 10 done, 0 failed, 0 cancelled, 2 not queued."
    )


def test_a_group_of_two_seasons_names_the_season(cli_env: ft.FakeTools, tmp_path: Path) -> None:
    per_file = {}
    for season, count in ((1, 2), (2, 2)):
        for n in range(1, count + 1):
            file = media_file(
                tmp_path / "media" / media.anime_folder(season), media.anime_file_name(season, n)
            )
            per_file[file] = anime(season, n)
    replay(cli_env, anime(1, 1), per_file=per_file)
    import_demo_preset()
    s01, s02 = (tmp_path / "media" / media.anime_folder(n) for n in (1, 2))
    result = invoke("batch", str(s01), str(s02), "--preset", A.PRESET_NAME, "--dry-run")
    assert result.exit_code == EXIT_OK, result.output
    out = result.stdout.splitlines()
    assert f"  S01E01  {media.anime_file_name(1, 1)} (representative)" in out
    assert f"  S02E02  {media.anime_file_name(2, 2)}" in out
    labels = [line.split()[0] for line in out if line.startswith(("S01E", "S02E"))]
    assert labels == ["S01E01", "S01E02", "S02E01", "S02E02"]


def test_plan_with_a_group_preset_shows_the_track_rule_warnings(
    cli_env: ft.FakeTools, tmp_path: Path
) -> None:
    """S1 matches without its title; A2 is skipped."""
    folder = tmp_path / "media" / S01
    e11 = media_file(folder, media.anime_file_name(1, 11))
    replay(cli_env, anime(1, 11))
    import_demo_preset()
    result = invoke("plan", str(e11), "--preset", A.PRESET_NAME)
    assert result.exit_code == EXIT_OK, result.output
    out = result.stdout
    assert "Issues (0 errors, 1 warning, " in out
    assert "[batch.track_relaxed · subtitle_rules[0]]" in out
    assert "[batch.track_skipped · audio_rules[1]]" in out


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


SKIPPED = ValidationIssue(
    severity=Severity.WARNING,
    code="encoder.dry_run_skipped",
    path="video.encoder",
    message="The test encode did not finish within 30 s.",
)
CHANGED = ValidationIssue(
    severity=Severity.WARNING,
    code="encoder.dry_run_warning",
    path="video.custom_params",
    message="The encoder changed a setting: limit-tu disabled",
)


def test_plan_shows_a_skipped_dry_run(movie: Path, dry_run: DryRun) -> None:  # noqa: F811
    """A dry run that did not finish does not get the note that the parameters were checked."""
    dry_run.issues = [SKIPPED]
    result = invoke("plan", str(movie), "--preset", CUSTOM)
    assert result.exit_code == EXIT_OK, result.output
    out = result.stdout
    assert "did not finish within 30 s" in out
    assert "[encoder.dry_run_skipped · video.encoder]" in out
    assert "Issues (0 errors, 1 warning, " in out
    assert DRY_RUN_NOTE not in out
    assert "Command (encode, " in out


def test_plan_shows_the_dry_runs_warnings(movie: Path, dry_run: DryRun) -> None:  # noqa: F811
    dry_run.issues = [CHANGED]
    result = invoke("plan", str(movie), "--preset", CUSTOM)
    assert result.exit_code == EXIT_OK, result.output
    out = result.stdout
    assert "The encoder changed a setting: limit-tu disabled" in out
    assert f"  Note     {DRY_RUN_NOTE}" in out
    data = json.loads(invoke("plan", str(movie), "--preset", CUSTOM, "--json").stdout)
    assert "encoder.dry_run_warning" in [i["code"] for i in data["draft"]["issues"]]
    assert data["plan"] is not None


class BatchStubs(Stubs):
    """:class:`~.conftest.Stubs` as ``Reframe.presets`` for the batch service too."""

    async def create(
        self, template: JobTemplate, name: str, *, category: str = "Custom", description: str = ""
    ) -> Preset | ValidationIssue:
        raise AssertionError("not used here")


def make_batch(stubs: BatchStubs) -> BatchService:
    jobs = JobService(
        sources=stubs,
        presets=stubs,
        tools=stubs,
        capabilities=stubs,
        settings=lambda: stubs.settings,
    )
    return BatchService(sources=stubs, presets=stubs, jobs=jobs, settings=lambda: stubs.settings)


@pytest.mark.anyio
async def test_resolve_batch_checks_every_group(tmp_path: Path) -> None:
    folder = tmp_path / S01
    e01, e02 = (media_file(folder, media.anime_file_name(1, n)) for n in (1, 2))
    web = media_file(folder, "Anime.Show.S01E02.Departure.WEB.x264-GRP.mkv")
    copy = media_file(folder, E01_OUT)
    stubs = BatchStubs(
        {
            e01: recorded(anime(1, 1), e01),
            e02: recorded(anime(1, 2), e02),
            web: recorded("multitrack", web),
            copy: recorded("multitrack", copy),
        }
    )
    grouping, resolutions = await make_batch(stubs).resolve_batch(None, [e01, e02, web, copy])
    assert [len(g.members) for g in grouping.groups] == [2, 1]
    (left,) = grouping.issues
    assert (left.code, left.severity) == ("batch.already_encoded", Severity.INFO)
    first, second = resolutions
    assert first.group == grouping.groups[0]

    def errors(rows: list[Resolution]) -> list[list[str]]:
        return [[i.code for i in row.issues if i.severity is Severity.ERROR] for row in rows]

    assert errors(first.rows) == [["batch.output_is_source"], ["batch.name_collision"]]
    assert errors(second.rows) == [["batch.name_collision"]]
    # The batch issue of the shared name: once, in the first group concerned.
    assert [i.code for i in first.issues] == ["batch.name_collision"]
    assert second.issues == []


@pytest.mark.anyio
async def test_the_row_order_is_computed_off_the_event_loop(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """guessit takes milliseconds per file name: the row sort of ``resolve`` runs in a
    worker thread, not on the event loop."""
    folder = tmp_path / S01
    files = [media_file(folder, media.anime_file_name(1, n)) for n in (2, 1)]
    stubs = BatchStubs(
        {file: recorded(anime(1, n), file) for file, n in zip(files, (2, 1), strict=True)}
    )
    where: list[str] = []
    real = episode_key

    def spy(path: Path) -> object:
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            where.append("thread")
        else:
            where.append("loop")
        return real(path)

    monkeypatch.setattr(batch_service, "episode_key", spy)
    resolution = await make_batch(stubs).resolve(None, files)
    assert [row.path for row in resolution.rows] == list(reversed(files))
    assert where
    assert set(where) == {"thread"}


@pytest.mark.needs_ffmpeg
def test_the_leads_reproduction_with_the_real_queue(
    fixture_media: Media, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """E01 of ``anime-s01`` and ``multitrack.mkv`` copied as ``Anime.Show.S01E01.Pilot.mkv``,
    with the collision setting *overwrite*: the copy is not overwritten."""
    for name in ("config", "data", "cache"):
        monkeypatch.setenv(f"REFRAME_{name.upper()}_DIR", str(tmp_path / name))
    monkeypatch.setattr(mediainfo, "mediainfo_available", lambda: False)
    write_settings(tmp_path, collision="overwrite")
    folder = tmp_path / "media" / S01
    folder.mkdir(parents=True)
    shutil.copy2(fixture_media("anime-s01") / E01, folder / E01)
    copy = folder / E01_OUT
    shutil.copy2(fixture_media("multitrack"), copy)
    before = hashlib.sha256(copy.read_bytes()).hexdigest()
    result = invoke("batch", str(folder))
    assert hashlib.sha256(copy.read_bytes()).hexdigest() == before, result.stdout
    assert result.exit_code == EXIT_FAILED, result.output
    assert "Nothing to encode." in result.stdout
    assert sorted(p.name for p in folder.iterdir()) == sorted([E01, E01_OUT])
