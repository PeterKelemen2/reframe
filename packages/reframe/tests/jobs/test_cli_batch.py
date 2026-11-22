"""``reframe batch`` and the ``selected:`` lines of ``reframe plan``."""

from __future__ import annotations

import asyncio
import importlib.util
import json
import shutil
import sys
from collections.abc import Callable
from pathlib import Path
from types import ModuleType

import pytest

from reframe import cli
from reframe.cli import EXIT_FAILED, EXIT_NOT_FOUND, EXIT_OK, EXIT_USAGE
from reframe.models import CropRect, CropSettings, MediaSource
from reframe.service import Reframe
from reframe_testing import fake_tools as ft
from reframe_testing import media
from reframe_testing.cli import invoke

from .conftest import Queues, media_file, replay


def _load_anime() -> ModuleType:
    path = Path(__file__).resolve().parents[1] / "batch" / "anime.py"
    spec = importlib.util.spec_from_file_location("_reframe_batch_anime", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


A = _load_anime()
Media = Callable[[str], Path]


#: The fake ffmpeg's ``cropdetect`` answer: black bars of 22 and 24 lines in the 320x180 frame.
CROPDETECT = ft.Rule(
    tool="ffmpeg",
    argv_contains=["cropdetect="],
    actions=[
        ft.stderr(
            "[Parsed_cropdetect_0 @ 0x55d1] x1:0 x2:319 y1:22 y2:155 w:320 h:134 x:0 y:22 "
            "pts:0 t:0.000000 limit:0.094118 crop=320:134:0:22\n"
        )
    ],
)


def season_files(
    cli_env: ft.FakeTools,
    tmp_path: Path,
    number: int,
    *,
    extra: tuple[ft.Rule, ...] = (CROPDETECT,),
) -> Path:
    """Placeholder files of season ``number``; the fake ffprobe replays each one's recording
    (``extra`` rules first)."""
    folder = tmp_path / "media" / media.anime_folder(number)
    per_file = {}
    for n in range(1, len(media.ANIME_TITLES[number]) + 1):
        name = media.anime_file_name(number, n)
        file = media_file(folder, name)
        per_file[file] = f"{media.anime_folder(number)}/{name.removesuffix('.mkv')}"
    replay(
        cli_env,
        f"{media.anime_folder(number)}/{media.anime_file_name(number, 1)[:-4]}",
        per_file=per_file,
        extra=extra,
    )
    return folder


@pytest.fixture
def s01(cli_env: ft.FakeTools, tmp_path: Path) -> Path:
    return season_files(cli_env, tmp_path, 1)


def import_demo_preset() -> None:
    result = invoke("presets", "import", str(A.PRESET_FILE))
    assert result.exit_code == EXIT_OK, result.output


STRICT = "Anime Season (dub required)"


def import_strict_preset(tmp_path: Path) -> None:
    """The demo preset with the dub (A2) required: E11, which has no dub, is an error."""
    data = json.loads(A.PRESET_FILE.read_text(encoding="utf-8"))
    (preset,) = data["presets"]
    preset.update(id="strict-dub", name=STRICT)
    preset["audio_rules"][1]["required"] = True
    file = tmp_path / "strict.json"
    file.write_text(json.dumps(data), encoding="utf-8")
    result = invoke("presets", "import", str(file))
    assert result.exit_code == EXIT_OK, result.output


def test_dry_run_with_the_default_preset(s01: Path) -> None:
    result = invoke("batch", str(s01), "--dry-run")
    assert result.exit_code == EXIT_OK, result.output
    out = result.stdout.splitlines()
    assert out[0] == "Preset: H.265 MKV 1080p"
    assert out[2] == "Group 1 of 1: Anime Show S01 · 12 files · standard match"
    assert out[3] == f"  E01  {media.anime_file_name(1, 1)} (representative)"
    assert out[7] == (
        f'  E05  {media.anime_file_name(1, 5)}  ⚠ 1 extra track (eng AC-3 2.0 "Commentary")'
    )
    assert "  A1  every track (defaults)" in out
    assert "  S1  every track (defaults)" in out
    header = out.index("File    V           A1           S1        Output name")
    assert out[header + 1].startswith("─────")
    assert (
        out[header + 2] == "E01 ✓   ✓ 320x180   ✓ #1 #2      ✓ #3 #4   Anime.Show.S01E01.Pilot.mkv"
    )
    assert (
        out[header + 6] == "E05 ⚠   ✓ 320x180   ✓ #1 #2 #3   ✓ #4 #5   Anime.Show.S01E05.Echoes.mkv"
    )
    assert "  E11: 1 warning" in out
    assert out[-1] == "Dry run: 12 of 12 files can be queued."
    assert not list(s01.glob("*.part.*"))


def test_dry_run_with_the_group_preset(s01: Path) -> None:
    """E05 has an extra track. E11 has no dub (A2 skipped) and another signs title."""
    import_demo_preset()
    result = invoke("batch", str(s01), "--preset", A.PRESET_NAME, "--dry-run")
    assert result.exit_code == EXIT_OK, result.output
    out = result.stdout.splitlines()
    assert out[0] == f"Preset: {A.PRESET_NAME}"
    assert [line for line in out if line.startswith(("  A", "  S"))][-4:] == [
        "  A1  jpn TrueHD→Opus 5.1",
        "  A2  eng DTS-HD MA→AC-3 5.1",
        "  S1  eng Signs & Songs",
        "  S2  eng Full",
    ]
    header = out.index("File    V           A1     A2          S1             S2     Output name")
    rows = out[header + 2 : header + 14]
    assert rows[0] == (
        "E01 ✓   ✓ 320x180   ✓ #1   ✓ #2        ✓ #3           ✓ #4   "
        "Anime Show - S01E01 - Pilot.mkv"
    )
    assert rows[4] == (
        "E05 ⚠   ✓ 320x180   ✓ #1   ✓ #2        ✓ #4           ✓ #5   "
        "Anime Show - S01E05 - Echoes.mkv"
    )
    assert rows[10] == (
        "E11 ⚠   ✓ 320x180   ✓ #1   \N{EN DASH} skipped   ≈ #2 (title)   ✓ #3   "
        "Anime Show - S01E11 - Static.mkv"
    )
    assert sum(r.split()[1] == "✓" for r in rows) == 10
    problems = out[out.index("Problems") :]
    assert "  E05: 1 warning" in problems
    assert "  E11: 2 warnings" in problems
    assert any("[batch.near_match · source]" in line for line in problems)
    assert any("[batch.track_relaxed · subtitle_rules[0]]" in line for line in problems)
    assert out[-1] == "Dry run: 12 of 12 files can be queued."


def test_dry_run_with_the_dub_required(s01: Path, tmp_path: Path) -> None:
    import_strict_preset(tmp_path)
    result = invoke("batch", str(s01), "--preset", STRICT, "--dry-run")
    assert result.exit_code == EXIT_FAILED, result.output
    out = result.stdout.splitlines()
    assert (
        "E11 ✗   ✓ 320x180   ✓ #1   ✗ none   ≈ #2 (title)   ✓ #3   Anime Show - S01E11 - Static.mkv"
        in out
    )
    problems = out[out.index("Problems") :]
    assert "  E11: 1 error, 2 warnings" in problems
    assert any("[batch.track_missing · audio_rules[1]]" in line for line in problems)
    assert any("fix: Make the rule optional" in line for line in problems)
    assert out[-1] == "Dry run: 11 of 12 files can be queued; 1 cannot (errors)."


def test_the_group_preset_on_season_2(cli_env: ft.FakeTools, tmp_path: Path) -> None:
    folder = season_files(cli_env, tmp_path, 2)
    import_demo_preset()
    result = invoke("batch", str(folder), "--preset", A.PRESET_NAME, "--dry-run")
    assert result.exit_code == EXIT_OK, result.output
    out = result.stdout.splitlines()
    assert out[2] == "Group 1 of 1: Anime Show S02 · 3 files · standard match"
    assert (
        "E03 ✓   ✓ 320x180   ✓ #1   ✓ #2   ✓ #3   ✓ #4   Anime Show - S02E03 - Northbound.mkv"
        in out
    )
    assert "Problems" not in out
    assert out[-1] == "Dry run: 3 of 3 files can be queued."


def test_json(s01: Path) -> None:
    result = invoke("batch", str(s01), "--dry-run", "--json", "--level", "loose")
    assert result.exit_code == EXIT_OK, result.output
    data = json.loads(result.stdout)
    (group,) = data["grouping"]["groups"]
    assert group["level"] == "loose"
    assert len(group["members"]) == 12
    (resolution,) = data["resolutions"]
    assert [c["label"] for c in resolution["columns"]][1] == "A1 every track (defaults)"
    assert resolution["rows"][4]["status"] == "warning"


def test_levels(s01: Path) -> None:
    result = invoke("batch", str(s01), "--dry-run", "--level", "strict")
    assert result.exit_code == EXIT_OK, result.output
    assert "Anime Show S01 · 12 files · strict match" in result.stdout
    assert '1 track differs (eng ASS "Signs & Songs" → eng ASS "Signs")' in result.stdout


def test_usage_errors(s01: Path, tmp_path: Path) -> None:
    result = invoke("batch", str(s01), "--json")
    assert result.exit_code == EXIT_USAGE
    assert result.stderr.startswith("error: --json needs --dry-run")
    result = invoke("batch", str(s01), "--preset", "H.265 MKV 1080")
    assert result.exit_code == EXIT_USAGE
    assert 'Did you mean "H.265 MKV 1080p"' in result.stderr
    result = invoke("batch", str(tmp_path / "nope"))
    assert result.exit_code == EXIT_NOT_FOUND
    assert "does not exist" in result.stderr
    empty = tmp_path / "empty"
    empty.mkdir()
    result = invoke("batch", str(empty), "--dry-run")
    assert result.exit_code == EXIT_NOT_FOUND
    assert "no media files in this folder" in result.stderr
    result = invoke("batch", str(s01), "--level", "sloppy")
    assert result.exit_code == EXIT_USAGE


def test_a_file_that_cannot_be_read(cli_env: ft.FakeTools, tmp_path: Path) -> None:
    broken = tmp_path / "media" / media.anime_folder(1) / "broken.mkv"
    garbage = ft.Rule(
        tool="ffprobe",
        argv_has=[str(broken)],
        exit_code=1,
        actions=[ft.stderr(f"{broken}: Invalid data found when processing input\n")],
    )
    folder = season_files(cli_env, tmp_path, 1, extra=(garbage,))
    media_file(folder, "broken.mkv")
    result = invoke("batch", str(folder), "--dry-run")
    assert result.exit_code == EXIT_FAILED, result.output
    out = result.stdout.splitlines()
    assert "Files that cannot be read" in out
    assert out[-1] == "Dry run: 12 of 13 files can be queued; 1 cannot (errors)."


def test_the_season_is_queued_in_episode_order(s01: Path, queues: Queues) -> None:
    import_demo_preset()
    result = invoke("batch", str(s01), "--preset", A.PRESET_NAME)
    assert result.exit_code == EXIT_OK, result.output
    out = result.stdout.splitlines()
    first = s01 / "Anime Show - S01E01 - Pilot.mkv"
    assert f"[ 1/12] {media.anime_file_name(1, 1)} → {first}" in out
    assert "Queued 12 jobs." in out
    assert out[-1] == "Summary: 12 done, 0 failed, 0 cancelled, 0 not queued."
    (queue,) = queues.made
    jobs = queue.list()
    assert [job.position for job in jobs] == list(range(12))
    names = [job.settings.output.path.name for job in jobs if job.settings.output.path]
    assert names[:2] == ["Anime Show - S01E01 - Pilot.mkv", "Anime Show - S01E02 - Departure.mkv"]
    assert names[10] == "Anime Show - S01E11 - Static.mkv"
    assert [len(job.settings.audio) for job in jobs][10] == 1  # E11: no dub
    assert queue.calls[-1] == "start " + " ".join(f"job-{n}" for n in range(1, 13))
    # The preset crops automatically: each file's crop is detected before it is queued.
    assert f"Detecting the crop of {media.anime_file_name(1, 1)} (1 of 12)…" in out
    assert {job.settings.dimensions.crop.model_dump_json() for job in jobs} == {
        CropSettings(mode="auto", rect=CropRect(top=22, bottom=24)).model_dump_json()
    }


def test_a_file_with_errors_is_not_queued(s01: Path, queues: Queues, tmp_path: Path) -> None:
    import_strict_preset(tmp_path)
    result = invoke("batch", str(s01), "--preset", STRICT)
    assert result.exit_code == EXIT_FAILED, result.output  # E11 is not queued
    out = result.stdout.splitlines()
    eleven = out.index(
        f"[11/12] {media.anime_file_name(1, 11)} → {s01 / 'Anime Show - S01E11 - Static.mkv'}"
    )
    assert out[eleven + 1] == "        not queued: 1 error, 2 warnings, 1 info (see Problems)"
    assert "Queued 11 jobs." in out
    assert out[-1] == "Summary: 11 done, 0 failed, 0 cancelled, 1 not queued."
    (queue,) = queues.made
    assert [job.position for job in queue.list()] == list(range(11))


def test_cancelling_the_batch_cancels_its_jobs(s01: Path, queues: Queues) -> None:
    """Ctrl+C (the cancelled task) cancels the batch's jobs."""
    queues.behaviour = lambda _job: "hang"

    async def run() -> int:
        running = asyncio.Event()
        queues.on_running = lambda _job: running.set()
        task = asyncio.create_task(cli.run_batch([s01], preset=None, in_process=True))
        await asyncio.wait_for(running.wait(), 30)
        task.cancel()
        return await task

    assert asyncio.run(run()) == cli.EXIT_INTERRUPTED
    assert {job.state.value for job in queues.made[0].list()} == {"cancelled"}


def test_plan_shows_why_a_track_was_selected(s01: Path) -> None:
    import_demo_preset()
    result = invoke("plan", str(s01 / media.anime_file_name(1, 5)), "--preset", A.PRESET_NAME)
    assert result.exit_code == EXIT_OK, result.output
    out = result.stdout.splitlines()
    audio = out.index(
        "  Audio    #1  Fixed settings of rule A1 jpn TrueHD→Opus 5.1: Opus 5.1 · 448 kb/s"
    )
    assert out[audio + 1] == "               selected: Rule A1 jpn TrueHD→Opus 5.1: exact match"
    assert "           #3  No track rule takes this track" in out
    subtitle = out.index("  Subtitle #4  Copy (rule S1 eng Signs & Songs)")
    assert out[subtitle + 1] == "               selected: Rule S1 eng Signs & Songs: exact match"
    # With the default preset, the keep-everything selection.
    result = invoke("plan", str(s01 / media.anime_file_name(1, 1)))
    keep = "No audio languages set (preset or Settings): every track is kept, in source order"
    assert f"               selected: {keep}" in result.stdout


@pytest.mark.needs_ffmpeg
@pytest.mark.slow
def test_a_season_encoded_end_to_end(
    fixture_media: Media, tmp_path: Path, dirs: dict[str, Path]
) -> None:
    """Season 2 with the group preset of season 1, on the real queue and FFmpeg."""
    folder = tmp_path / "media" / media.anime_folder(2)
    shutil.copytree(fixture_media("anime-s02"), folder)
    import_demo_preset()
    result = invoke("batch", str(folder), "--preset", A.PRESET_NAME)
    assert result.exit_code == EXIT_OK, result.output
    assert result.stdout.splitlines()[-1] == "Summary: 3 done, 0 failed, 0 cancelled, 0 not queued."
    outputs = sorted(p.name for p in folder.iterdir() if p.name.startswith("Anime Show"))
    assert outputs == [
        "Anime Show - S02E01 - Return.mkv",
        "Anime Show - S02E02 - Ashes.mkv",
        "Anime Show - S02E03 - Northbound.mkv",
    ]

    async def probe(path: Path) -> MediaSource:
        async with await Reframe.create() as app:
            found = await app.sources.probe(path)
        assert isinstance(found, MediaSource)
        return found

    encoded = asyncio.run(probe(folder / outputs[0]))
    assert [(a.codec, a.channels, a.title, a.disposition.default) for a in encoded.audio] == [
        ("opus", 6, "Japanese 5.1", True),
        ("ac3", 6, "English 5.1", False),
    ]
    assert encoded.audio[1].bitrate.value == 640_000
    assert [(s.title, s.disposition.forced, s.disposition.default) for s in encoded.subtitles] == [
        ("Signs & Songs", True, False),
        ("Full", False, True),
    ]


@pytest.mark.needs_ffmpeg
@pytest.mark.slow
def test_letterboxed_episodes_are_encoded_cropped(
    fixture_media: Media, tmp_path: Path, dirs: dict[str, Path]
) -> None:
    """The default preset crops automatically: each episode's bars are detected and cut."""
    folder = tmp_path / "media"
    folder.mkdir()
    sources = []
    for n in (1, 2):
        sources.append(folder / f"Letterbox.S01E{n:02d}.mkv")
        shutil.copy2(fixture_media("letterbox"), sources[-1])
    result = invoke("batch", str(folder))
    assert result.exit_code == EXIT_OK, result.output
    out = result.stdout.splitlines()
    assert "Detecting the crop of Letterbox.S01E02.mkv (2 of 2)…" in out
    assert out[-1] == "Summary: 2 done, 0 failed, 0 cancelled, 0 not queued."
    outputs = sorted(p for p in folder.iterdir() if p not in sources)
    assert len(outputs) == 2

    async def sizes() -> list[tuple[int, int]]:
        async with await Reframe.create() as app:
            found = [await app.sources.probe(path) for path in outputs]
        return [(s.video[0].width, s.video[0].height) for s in found if isinstance(s, MediaSource)]

    assert asyncio.run(sizes()) == [(320, 134), (320, 134)]
