"""Regression tests for file identity, control characters, overwrite warnings and labels."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import shutil
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from reframe import jobs
from reframe.batch import service as batch_service
from reframe.cli import EXIT_FAILED, EXIT_OK
from reframe.models.issues import ReplaceOp
from reframe.probe import mediainfo
from reframe_testing import fake_tools as ft
from reframe_testing import media

from .conftest import invoke, media_file, probe_json, probe_rule, recorded, replay
from .test_cli_batch import Queues, queues  # noqa: F401
from .test_cli_review_fixes import (
    E01,
    E01_OUT,
    S01,
    BatchStubs,
    anime,
    make_batch,
    outputs_of,
    two_sources,
    write_settings,
)

Media = Callable[[str], Path]
ESC = "\x1b"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def linked(tmp_path: Path, folder: Path) -> Path:
    """``tmp_path/link``: a symbolic link to ``folder``."""
    link = tmp_path / "link"
    link.symlink_to(folder, target_is_directory=True)
    return link


def test_ra1_encode_never_writes_a_source_given_through_a_linked_folder(
    cli_env: ft.FakeTools,
    queues: Queues,  # noqa: F811
    tmp_path: Path,
) -> None:
    """The second file is named through a link to the folder. E01's output is that file by
    another spelling: E01 is not queued."""
    write_settings(tmp_path, collision="overwrite")
    folder, e01, copy = two_sources(cli_env, tmp_path, E01_OUT)
    link = linked(tmp_path, folder)
    result = invoke("encode", str(e01), str(link / E01_OUT))
    written = [p.resolve() for p in outputs_of(queues) if p is not None]
    assert copy.resolve() not in written, result.output
    assert result.exit_code == EXIT_FAILED
    out = result.stdout
    assert "[batch.output_is_source · output.path]" in out
    # The messages keep the spelling the user typed.
    assert f"The output {E01_OUT} is a source file of this command ([2/2] {E01_OUT})" in out
    assert f"[2/2] {E01_OUT} → {link / 'Anime.Show.S01E01.Pilot (1).mkv'}" in out
    assert out.splitlines()[-1] == "Summary: 1 done, 0 failed, 0 cancelled, 1 not queued."


def test_ra1_batch_never_writes_a_source_given_through_a_linked_folder(
    cli_env: ft.FakeTools,
    queues: Queues,  # noqa: F811
    tmp_path: Path,
) -> None:
    """``reframe batch``: the linked file is E01's planned output (left out as already encoded),
    and E01 is ``batch.output_is_source``: nothing is queued."""
    write_settings(tmp_path, collision="overwrite")
    folder, e01, copy = two_sources(cli_env, tmp_path, E01_OUT)
    link = linked(tmp_path, folder)
    result = invoke("batch", str(e01), str(link / E01_OUT))
    written = [p.resolve() for p in outputs_of(queues) if p is not None]
    assert copy.resolve() not in written, result.output
    assert result.exit_code == EXIT_FAILED
    out = result.stdout.splitlines()
    assert any(f"{E01_OUT} is the planned output of {E01}" in line for line in out)
    assert any("[batch.output_is_source · output.path]" in line for line in out)
    assert "Nothing to encode." in out


def test_ra1_encode_never_writes_a_hard_linked_output_name(
    cli_env: ft.FakeTools,
    queues: Queues,  # noqa: F811
    tmp_path: Path,
) -> None:
    """E01's output name is a hard link to another source of the command (in another folder,
    by another name): the same file, so E01 is not queued."""
    write_settings(tmp_path, collision="overwrite")
    folder = tmp_path / "media" / S01
    e01 = media_file(folder, E01)
    other = media_file(tmp_path / "other", "Other.mkv")
    os.link(other, folder / E01_OUT)
    replay(cli_env, "multitrack", per_file={e01: anime(1, 1), other: "multitrack"})
    result = invoke("encode", str(e01), str(other))
    assert result.exit_code == EXIT_FAILED, result.output
    out = result.stdout
    assert "[batch.output_is_source · output.path]" in out
    assert f"The output {E01_OUT} is a source file of this command ([2/2] Other.mkv)" in out
    assert outputs_of(queues) == [other.parent / "Other (1).mkv"]  # its own job only
    assert other.read_bytes() == b"placeholder"


def test_ra1_batch_never_writes_a_hard_linked_output_name(
    cli_env: ft.FakeTools,
    queues: Queues,  # noqa: F811
    tmp_path: Path,
) -> None:
    """``reframe batch`` of the same files: ``Other.mkv`` is E01's planned output (the same
    file by another name), left out as already encoded; E01 is not queued."""
    write_settings(tmp_path, collision="overwrite")
    folder = tmp_path / "media" / S01
    e01 = media_file(folder, E01)
    other = media_file(tmp_path / "other", "Other.mkv")
    os.link(other, folder / E01_OUT)
    replay(cli_env, "multitrack", per_file={e01: anime(1, 1), other: "multitrack"})
    result = invoke("batch", str(e01), str(other), "--dry-run")
    assert result.exit_code == EXIT_FAILED, result.output
    out = result.stdout.splitlines()
    assert any(
        f"Other.mkv is the planned output of {E01} with this preset (the same file as "
        f"{E01_OUT})" in line
        for line in out
    ), result.stdout
    assert any("[batch.output_is_source · output.path]" in line for line in out)
    assert out[-1] == (
        "Dry run: 0 of 1 file can be queued; 1 cannot (errors); 1 left out (already encoded)."
    )
    result = invoke("batch", str(e01), str(other))
    assert "Nothing to encode." in result.stdout
    assert outputs_of(queues) == []


def season_pair(cli_env: ft.FakeTools, tmp_path: Path) -> Path:
    """E01 and E02 of season 1 (one layout: one group)."""
    folder = tmp_path / "media" / S01
    per_file = {media_file(folder, media.anime_file_name(1, n)): anime(1, n) for n in (1, 2)}
    replay(cli_env, anime(1, 1), per_file=per_file)
    return folder


def test_ra1_a_folder_given_through_two_spellings_is_taken_once(
    cli_env: ft.FakeTools, tmp_path: Path
) -> None:
    """``reframe batch real link --dry-run`` (``link`` → ``real``): every episode once, in the
    spelling of the first argument, and no name collision of a file with itself."""
    folder = season_pair(cli_env, tmp_path)
    link = linked(tmp_path, folder)
    result = invoke("batch", str(folder), str(link), "--dry-run")
    assert result.exit_code == EXIT_OK, result.output
    out = result.stdout.splitlines()
    assert "Group 1 of 1: Anime Show S01 · 2 files · standard match" in out
    assert not any("batch.name_collision" in line for line in out)
    assert out[-1] == "Dry run: 2 of 2 files can be queued."
    data = json.loads(invoke("batch", str(folder), str(link), "--dry-run", "--json").stdout)
    rows = [row["path"] for r in data["resolutions"] for row in r["rows"]]
    assert rows == [str(folder / media.anime_file_name(1, n)) for n in (1, 2)]


def test_ra1_encode_takes_a_file_named_through_a_link_once(
    cli_env: ft.FakeTools,
    queues: Queues,  # noqa: F811
    tmp_path: Path,
) -> None:
    """``reframe encode link/E01 real/E01 real``: one job per file."""
    folder = season_pair(cli_env, tmp_path)
    link = linked(tmp_path, folder)
    result = invoke("encode", str(link / E01), str(folder / E01), str(folder))
    assert result.exit_code == EXIT_OK, result.output
    sources = [job.settings.source.path for q in queues.made for job in q.list()]
    assert sources == [link / E01, folder / media.anime_file_name(1, 2)]
    assert "[2/2]" in result.stdout
    assert "[1/3]" not in result.stdout


class LoopSpy:
    """``file_key`` of ``reframe.jobs`` and of the batch service, recording for each call
    whether it ran on the event loop's thread (a file system that stops answering would then
    freeze the loop)."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.where: list[str] = []
        real = jobs.file_key

        def spy(path: Any) -> str:
            try:
                asyncio.get_running_loop()
            except RuntimeError:
                self.where.append("thread")
            else:
                self.where.append("loop")
            return real(path)

        monkeypatch.setattr(jobs, "file_key", spy)
        monkeypatch.setattr(batch_service, "file_key", spy)


def test_ra1_the_file_keys_are_computed_off_the_event_loop(
    cli_env: ft.FakeTools,
    queues: Queues,  # noqa: F811
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``reframe encode`` and ``reframe batch``: every ``stat`` / ``realpath`` of the name
    checks runs in a worker thread, never on the event loop."""
    folder, e01, _copy = two_sources(cli_env, tmp_path, E01_OUT)
    spy = LoopSpy(monkeypatch)
    invoke("encode", str(folder))
    invoke("batch", str(folder), "--dry-run")
    invoke("batch", str(e01), str(folder))
    assert spy.where
    assert set(spy.where) == {"thread"}


@pytest.mark.anyio
async def test_ra1_the_batch_service_keys_files_off_the_event_loop(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``Reframe.batch.resolve`` (with a group and overrides) and ``resolve_batch``: the keys
    are computed in worker threads."""
    folder = tmp_path / S01
    files = [media_file(folder, media.anime_file_name(1, n)) for n in (1, 2)]
    stubs = BatchStubs({f: recorded(anime(1, n), f) for f, n in zip(files, (1, 2), strict=True)})
    batch = make_batch(stubs)
    grouping = await batch.group(files)
    spy = LoopSpy(monkeypatch)
    op = ReplaceOp.model_validate({"op": "replace", "path": "/video/preset", "value": "slow"})
    resolution = await batch.resolve(
        None, files, overrides={str(files[1]): [op]}, group=grouping.groups[0]
    )
    assert [row.path for row in resolution.rows] == files
    _grouping, resolutions = await batch.resolve_batch(None, [*files, *files])
    assert [row.path for r in resolutions for row in r.rows] == files
    assert spy.where
    assert set(spy.where) == {"thread"}


def import_evil_preset(tmp_path: Path) -> None:
    exported = tmp_path / "h265.json"
    assert invoke("presets", "export", "H.265 MKV 1080p", "--output", str(exported)).exit_code == 0
    data = json.loads(exported.read_text(encoding="utf-8"))
    data["presets"][0].update(id="evil", name="Evil\x1b[31mRED", built_in=False)
    data["default_preset_id"] = None
    exported.write_text(json.dumps(data), encoding="utf-8")
    assert invoke("presets", "import", str(exported)).exit_code == 0


def test_ra2_preset_line_of_batch_and_encode_has_no_control_characters(
    cli_env: ft.FakeTools,
    queues: Queues,  # noqa: F811
    tmp_path: Path,
) -> None:
    """A preset named ``Evil ESC[31m RED`` (imported) in the ``Preset:`` line of
    ``reframe batch`` and ``reframe encode``."""
    import_evil_preset(tmp_path)
    folder, _e01, _copy = two_sources(cli_env, tmp_path, "Other.mkv")
    batch = invoke("batch", str(folder), "--preset", "evil", "--dry-run")
    encode = invoke("encode", str(folder), "--preset", "evil")
    assert ESC not in batch.stdout, batch.stdout.splitlines()[0]
    assert ESC not in encode.stdout, encode.stdout.splitlines()[0]
    assert batch.stdout.splitlines()[0] == "Preset: Evil�[31mRED"
    assert encode.stdout.splitlines()[0] == "Preset: Evil�[31mRED"


def escaped_probe(tmp_path: Path, name: str, old: str, new: str) -> Path:
    """The recorded probe ``name`` with the title ``old`` renamed ``new``."""
    data = json.loads(probe_json(name).read_text(encoding="utf-8"))
    for stream in data["streams"]:
        if stream.get("tags", {}).get("title") == old:
            stream["tags"]["title"] = new
    path = tmp_path / "probes" / (Path(name).name + ".json")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def test_ra2_titles_and_file_names_in_the_batch_output_are_printable(
    cli_env: ft.FakeTools, tmp_path: Path
) -> None:
    """A near member's difference names a track title with ESC (E05's commentary), two releases
    of E01 are labelled by their file names (one with ESC), and the matrix shows that name
    and its output name: no ESC on stdout."""
    folder = tmp_path / "media" / S01
    e01 = media_file(folder, E01)
    evil = media_file(folder, "Anime.Show.S01E01.\x1b[31mRed.WEB.x264-GRP.mkv")
    e05 = media_file(folder, media.anime_file_name(1, 5))
    commentary = escaped_probe(tmp_path, anime(1, 5), "Commentary", "Comm\x1b[32mGreen")
    cli_env.set_scenario(
        ft.Scenario(
            [
                probe_rule(commentary, e05),
                probe_rule(probe_json(anime(1, 1)), e01),
                probe_rule(probe_json(anime(1, 1)), evil),
            ]
        )
    )
    result = invoke("batch", str(folder), "--dry-run")
    assert result.exit_code == EXIT_OK, result.output
    out = result.stdout
    assert ESC not in out, out
    assert 'extra track (eng AC-3 2.0 "Comm�[32mGreen")' in out
    # The member list and the matrix row label.
    assert out.count("Anime.Show.S01E01.�[31mRed.WEB.x264-GRP.mkv") == 2
    assert "Anime.Show.S01E01.[31mRed.mkv" in out


def test_ra2_reframe_probe_prints_titles_without_control_characters(
    cli_env: ft.FakeTools, tmp_path: Path
) -> None:
    """``reframe probe``: a track title, the container title and a chapter title come from the
    file; they are shown through ``printable`` too (``--json`` keeps them)."""
    file = media_file(tmp_path / "media", "Movie\x1b[35m.mkv")
    data = json.loads(probe_json(anime(1, 5)).read_text(encoding="utf-8"))
    for stream in data["streams"]:
        if stream.get("tags", {}).get("title") == "Commentary":
            stream["tags"]["title"] = "Comm\x1b[32mGreen"
    data["format"]["tags"]["title"] = "Movie\x1b]0;PWNED\x07"
    path = tmp_path / "probe.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    cli_env.set_scenario(ft.Scenario([probe_rule(path)]))
    result = invoke("probe", str(file))
    assert result.exit_code == EXIT_OK, result.output
    assert ESC not in result.stdout, result.stdout
    assert "\x07" not in result.stdout
    assert "Comm�[32mGreen" in result.stdout
    assert "Movie�]0;PWNED�" in result.stdout
    raw = json.loads(invoke("probe", str(file), "--json").stdout)
    assert raw["container"]["title"] == "Movie\x1b]0;PWNED\x07"


def test_ra4_encode_does_not_say_will_be_replaced_next_to_never_overwritten(
    cli_env: ft.FakeTools,
    queues: Queues,  # noqa: F811
    tmp_path: Path,
) -> None:
    """With *overwrite*, E01's output is the other file of the folder."""
    write_settings(tmp_path, collision="overwrite")
    folder, _e01, _copy = two_sources(cli_env, tmp_path, E01_OUT)
    result = invoke("encode", str(folder))
    assert "[batch.output_is_source · output.path]" in result.stdout
    assert "[output.overwrite" not in result.stdout, result.stdout


def test_ra4_encode_keeps_the_overwrite_warning_of_a_file_outside_the_command(
    cli_env: ft.FakeTools,
    queues: Queues,  # noqa: F811
    tmp_path: Path,
) -> None:
    """An existing output that is not a file of the command is replaced with *overwrite*, and
    ``output.overwrite`` warns about it."""
    write_settings(tmp_path, collision="overwrite")
    folder = tmp_path / "media" / S01
    e01 = media_file(folder, E01)
    media_file(folder, E01_OUT)
    replay(cli_env, anime(1, 1))
    result = invoke("encode", str(e01))
    assert result.exit_code == EXIT_OK, result.output
    assert "[output.overwrite · output.path]" in result.stdout


def test_ra5_a_member_labelled_by_its_file_name_shows_the_name_once(
    cli_env: ft.FakeTools, tmp_path: Path
) -> None:
    """Two releases of S02E01 are labelled by their file names: each member line shows the
    name once; E02 keeps its label column."""
    folder = tmp_path / "media" / media.anime_folder(2)
    bluray = media.anime_file_name(2, 1)
    web = "Anime.Show.S02E01.Return.WEB.x264-GRP.mkv"
    e02 = media.anime_file_name(2, 2)
    per_file = {
        media_file(folder, bluray): anime(2, 1),
        media_file(folder, web): anime(2, 1),
        media_file(folder, e02): anime(2, 2),
    }
    replay(cli_env, anime(2, 1), per_file=per_file)
    result = invoke("batch", str(folder), "--dry-run")
    assert result.exit_code == EXIT_FAILED, result.output  # the two releases share a name
    out = result.stdout.splitlines()
    start = out.index("Group 1 of 1: Anime Show S02 · 3 files · standard match")
    assert out[start + 1 : start + 4] == [
        f"  {bluray} (representative)",
        f"  {web}",
        f"  E02  {e02}",
    ]


@pytest.mark.needs_ffmpeg
def test_ra1_the_symlink_case_with_the_real_queue(
    fixture_media: Media, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``real/`` holds E01 and a user file named as E01's output (a copy of ``multitrack.mkv``),
    ``link`` → ``real``, the collision setting *overwrite*. ``reframe encode real/E01
    link/<E01's output>`` and ``reframe batch`` of the same files leave the user file as it was
    (its SHA-256)."""
    for name in ("config", "data", "cache"):
        monkeypatch.setenv(f"REFRAME_{name.upper()}_DIR", str(tmp_path / name))
    monkeypatch.setattr(mediainfo, "mediainfo_available", lambda: False)
    write_settings(tmp_path, collision="overwrite")
    settings = json.loads((tmp_path / "config" / "settings.json").read_text(encoding="utf-8"))
    assert settings["queue"]["when_done"] == "nothing"
    real = tmp_path / "symlink" / "real"
    real.mkdir(parents=True)
    shutil.copy2(fixture_media("anime-s01") / E01, real / E01)
    user = real / E01_OUT
    shutil.copy2(fixture_media("multitrack"), user)
    link = tmp_path / "symlink" / "link"
    link.symlink_to(real, target_is_directory=True)
    before = sha256(user)

    encode = invoke("encode", str(real / E01), str(link / E01_OUT))
    assert sha256(user) == before, encode.stdout
    assert encode.exit_code == EXIT_FAILED, encode.output
    assert "[batch.output_is_source · output.path]" in encode.stdout
    assert encode.stdout.splitlines()[-1] == (
        "Summary: 1 done, 0 failed, 0 cancelled, 1 not queued."
    )
    second = real / "Anime.Show.S01E01.Pilot (1).mkv"
    assert second.stat().st_size > 0  # the user file's own job, to a free name
    second.unlink()

    batch = invoke("batch", str(real / E01), str(link / E01_OUT))
    assert sha256(user) == before, batch.stdout
    assert batch.exit_code == EXIT_FAILED, batch.output
    assert "Nothing to encode." in batch.stdout
    assert sorted(p.name for p in real.iterdir()) == sorted([E01, E01_OUT])
