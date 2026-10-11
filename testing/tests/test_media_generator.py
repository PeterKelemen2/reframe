"""The fixture generator itself: recipes, hashing, incremental runs (with the fake ffmpeg)."""

from __future__ import annotations

import os
import struct
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from reframe_testing import boxfont, media, vobsub
from reframe_testing import fake_tools as ft
from reframe_testing.fake_tools import FakeTools

REPO = Path(__file__).resolve().parents[2]


@pytest.fixture
def out_dir(tmp_path: Path) -> Path:
    return tmp_path / "media"


def test_every_plan_fixture_has_a_recipe() -> None:
    recipes = media.build_recipes()
    assert set(recipes) == {
        "multitrack",
        "text-subs",
        "vobsub",
        "letterbox",
        "anamorphic",
        "interlaced",
        "vfr",
        "vfr-mkv",
        "hdr10",
        "chapters",
        "season",
    }
    assert media.fixture_names()[-2:] == ["text-subs-srt", "text-subs-ass"]


def test_fixture_paths() -> None:
    assert media.fixture_path("multitrack") == media.DEFAULT_MEDIA_DIR / "multitrack.mkv"
    assert media.fixture_path("season") == media.DEFAULT_MEDIA_DIR / "season"
    assert media.fixture_path("text-subs-srt", Path("x")) == Path("x") / "text-subs.en.srt"
    assert media.DEFAULT_MEDIA_DIR == REPO / "testdata" / "media"
    with pytest.raises(KeyError, match="unknown fixture"):
        media.fixture_path("nope")


def test_season_names_and_variants() -> None:
    season = media.build_recipes()["season"]
    names = [o.removeprefix("season/") for o in season.outputs]
    assert names == [f"Show.S01E{n:02d}.Title.mkv" for n in range(1, 13)]


def test_recipe_hash_is_stable_and_sensitive() -> None:
    a = media.build_recipes()["chapters"]
    b = media.build_recipes()["chapters"]
    assert a.fingerprint("ffmpeg version 1") == b.fingerprint("ffmpeg version 1")
    assert a.fingerprint("ffmpeg version 1") != a.fingerprint("ffmpeg version 2")
    changed_data = media.Recipe(
        a.name, a.description, a.outputs, (media.WriteFile("chapters.txt", b"x"), *a.steps[1:])
    )
    assert changed_data.fingerprint("v") != a.fingerprint("v")
    changed_args = media.Recipe(
        a.name, a.description, a.outputs, (*a.steps[:-1], media.Ffmpeg(("-i", "y")))
    )
    assert changed_args.fingerprint("v") != a.fingerprint("v")


def test_no_absolute_paths_in_ffmpeg_arguments() -> None:
    """Commands use relative names only: no path quoting in filter graphs, portable hashes."""
    for recipe in media.build_recipes().values():
        for step in recipe.steps:
            if isinstance(step, media.Ffmpeg):
                for arg in step.args:
                    assert not Path(arg).is_absolute(), (recipe.name, arg)
                    assert "\\" not in arg or arg.startswith("{"), (recipe.name, arg)


def test_text_templates() -> None:
    assert media.srt([(0.5, 61.25, "Hi")]) == "1\n00:00:00,500 --> 00:01:01,250\nHi\n"
    text = media.ass("Reframe Box", [(1.0, 2.5, "Default", "Hi")])
    assert "Style: Default,Reframe Box,18," in text
    assert text.endswith("Dialogue: 0,0:00:01.00,0:00:02.50,Default,,0,0,0,,Hi\n")


# --------------------------------------------------------------------------- incremental generation


def _gen(names: list[str], out_dir: Path, tools: FakeTools, **kw: object) -> dict[str, str]:
    results = media.generate(names, out_dir=out_dir, ffmpeg=str(tools.ffmpeg), jobs=2, **kw)  # type: ignore[arg-type]
    return {r.name: r.status for r in results}


def test_incremental_generation_with_the_fake(
    fake_tools: FakeTools, out_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    names = ["anamorphic", "chapters", "season"]
    assert _gen(names, out_dir, fake_tools) == dict.fromkeys(names, "generated")
    assert (out_dir / "anamorphic.mkv").stat().st_size == 1024  # written by the fake
    assert len(list((out_dir / "season").glob("Show.S01E*.Title.mkv"))) == 12
    encodes = [c for c in fake_tools.calls() if "-i" in c]
    assert len(encodes) == 1 + 1 + 13  # anamorphic, chapters, season master + 12 remuxes
    # the fake ran in the work folder with relative names
    assert all(not Path(c[-1]).is_absolute() for c in fake_tools.calls() if "-i" in c)

    fake_tools.clear_log()
    assert _gen(names, out_dir, fake_tools) == dict.fromkeys(names, "up-to-date")
    assert fake_tools.calls() == []  # not even "-version": it is cached per binary

    # a missing output, --force, and a recipe change regenerate
    (out_dir / "season" / "Show.S01E07.Title.mkv").unlink()
    assert _gen(names, out_dir, fake_tools) == {
        "anamorphic": "up-to-date",
        "chapters": "up-to-date",
        "season": "generated",
    }
    assert _gen(["chapters"], out_dir, fake_tools, force=True) == {"chapters": "generated"}
    monkeypatch.setattr(media, "GENERATOR_VERSION", media.GENERATOR_VERSION + 1)
    assert _gen(["anamorphic"], out_dir, fake_tools) == {"anamorphic": "generated"}

    manifest = media._read_manifest(out_dir)["fixtures"]
    assert set(manifest) == set(names)
    assert manifest["season"]["outputs"][0] == "season/Show.S01E01.Title.mkv"
    assert not list(out_dir.glob(".tmp-*"))


def test_a_new_ffmpeg_version_regenerates(fake_tools: FakeTools, out_dir: Path) -> None:
    assert _gen(["anamorphic"], out_dir, fake_tools) == {"anamorphic": "generated"}
    fake_tools.set_scenario(
        ft.Scenario([ft.Rule(argv_has=["-version"], actions=[ft.version("7.1.1")])])
    )
    media._version_line.cache_clear()  # the cache key is the binary (path, size, mtime)
    assert _gen(["anamorphic"], out_dir, fake_tools) == {"anamorphic": "generated"}


def test_a_failing_step_leaves_nothing_behind(fake_tools: FakeTools, out_dir: Path) -> None:
    fake_tools.set_scenario(
        ft.Scenario(
            [
                ft.Rule(
                    argv_contains=["libx265"],
                    actions=[ft.stderr("x265 [error]: boom\n")],
                    exit_code=1,
                )
            ]
        )
    )
    with pytest.raises(media.MediaError, match="boom"):
        _gen(["hdr10"], out_dir, fake_tools)
    assert not (out_dir / "hdr10.mkv").exists()
    assert "hdr10" not in media._read_manifest(out_dir)["fixtures"]
    assert not list(out_dir.glob(".tmp-*"))


def test_missing_output_is_an_error(fake_tools: FakeTools, out_dir: Path) -> None:
    fake_tools.set_scenario(ft.Scenario([ft.Rule(argv_has=["-i"], actions=[])]))  # writes nothing
    with pytest.raises(media.MediaError, match="did not create"):
        _gen(["anamorphic"], out_dir, fake_tools)


def test_ensure_fixture_generates_on_demand(fake_tools: FakeTools, out_dir: Path) -> None:
    path = media.ensure_fixture("text-subs-ass", out_dir=out_dir, ffmpeg=str(fake_tools.ffmpeg))
    assert path == out_dir / "text-subs.en.ass"
    assert "[V4+ Styles]" in path.read_text(encoding="utf-8")
    assert (out_dir / "text-subs.mkv").is_file()


def test_find_ffmpeg_honours_the_environment(
    fake_tools: FakeTools, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv(media.FFMPEG_ENV, str(fake_tools.ffmpeg))
    monkeypatch.delenv(media.FFPROBE_ENV, raising=False)
    assert media.find_ffmpeg() == str(fake_tools.ffmpeg)
    assert media.find_ffprobe() == str(fake_tools.ffprobe)  # next to the ffmpeg
    monkeypatch.setenv(media.FFMPEG_ENV, str(tmp_path / "missing"))
    assert media.find_ffmpeg() is None


def test_cli(
    fake_tools: FakeTools,
    out_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv(media.FFMPEG_ENV, str(fake_tools.ffmpeg))
    assert media.main(["--only", "letterbox", "--out", str(out_dir)]) == 0
    assert "1 generated, 0 up to date" in capsys.readouterr().out
    assert media.main(["--only", "letterbox", "--out", str(out_dir)]) == 0
    assert "0 generated, 1 up to date" in capsys.readouterr().out
    assert media.main(["--list"]) == 0
    assert "season" in capsys.readouterr().out
    assert media.main(["--only", "nope", "--out", str(out_dir)]) == 1
    monkeypatch.setenv(media.FFMPEG_ENV, str(out_dir / "missing-ffmpeg"))
    assert media.main(["--out", str(out_dir)]) == 1
    assert "ffmpeg not found" in capsys.readouterr().err


def test_script_wrapper_runs(fake_tools: FakeTools, out_dir: Path) -> None:
    r = subprocess.run(
        [
            sys.executable,
            str(REPO / "scripts" / "make-testdata.py"),
            "--only",
            "vfr",
            "--out",
            str(out_dir),
        ],
        capture_output=True,
        text=True,
        env={**fake_tools.env(), media.FFMPEG_ENV: str(fake_tools.ffmpeg)},
        timeout=60,
        check=False,
    )
    assert r.returncode == 0, r.stderr
    assert (out_dir / "vfr.mp4").is_file()


# --------------------------------------------------------------------------- fonts


def test_the_ass_fixture_always_attaches_the_generated_box_font() -> None:
    """No system font: text-subs.mkv is the same on every machine (C-3 snapshots)."""
    font = media.fixture_font()
    assert (font.family, font.file_name, font.source) == (
        boxfont.FAMILY,
        "ReframeBox.ttf",
        "generated",
    )
    assert font.data == boxfont.build_font()
    recipe = media.build_recipes()["text-subs"]
    writes = {s.path: s.data for s in recipe.steps if isinstance(s, media.WriteFile)}
    assert writes["ReframeBox.ttf"] == boxfont.build_font()
    assert "Style: Default,Reframe Box,18," in writes["text-subs.en.ass"].decode()
    (ffmpeg,) = [s for s in recipe.steps if isinstance(s, media.Ffmpeg)]
    assert ffmpeg.args[ffmpeg.args.index("-attach") + 1] == "ReframeBox.ttf"
    assert not hasattr(media, "find_font")  # the system font search is gone
    assert media.GENERATOR_VERSION >= 2  # fixtures made with a system font are regenerated


# --------------------------------------------------------------------------- manifest races


class _RecordingLock:
    """A stand-in for ``_manifest_lock`` that records whether it is held."""

    def __init__(self) -> None:
        self.depth = 0
        self.entered = 0

    def __enter__(self) -> None:
        self.depth += 1
        self.entered += 1

    def __exit__(self, *exc: object) -> None:
        self.depth -= 1


def test_manifest_reads_hold_the_lock(
    fake_tools: FakeTools, out_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Windows: reading manifest.json while another thread replaces it is a PermissionError."""
    _gen(["anamorphic"], out_dir, fake_tools)
    lock = _RecordingLock()
    monkeypatch.setattr(media, "_manifest_lock", lock)
    real_read = media._read_manifest
    held_during_read: list[bool] = []

    def read(path: Path) -> dict[str, object]:
        held_during_read.append(lock.depth > 0)
        return real_read(path)

    monkeypatch.setattr(media, "_read_manifest", read)
    recipe = media.build_recipes()["anamorphic"]
    version = media.ffmpeg_version(str(fake_tools.ffmpeg))
    assert media.is_up_to_date(recipe, out_dir, version)
    assert held_during_read == [True]


def test_replace_retries_on_permission_error(
    out_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    out_dir.mkdir()
    real_replace = os.replace
    attempts: list[str] = []

    def flaky(src: object, dst: object) -> None:
        attempts.append(str(dst))
        if len(attempts) <= 2:
            raise PermissionError(13, "The process cannot access the file")
        real_replace(src, dst)  # type: ignore[arg-type]

    monkeypatch.setattr(os, "replace", flaky)
    media._update_manifest(out_dir, "x", {"hash": "h"})
    assert len(attempts) == 3
    assert media._read_manifest(out_dir)["fixtures"] == {"x": {"hash": "h"}}

    # it gives up after the back-off and raises the last error
    monkeypatch.setattr(media, "_RETRY_DELAYS", (0.0, 0.0))
    attempts.clear()

    def always(src: object, dst: object) -> None:
        attempts.append(str(dst))
        raise PermissionError(13, "denied")

    monkeypatch.setattr(os, "replace", always)
    with pytest.raises(PermissionError):
        media._replace(out_dir / "a", out_dir / "b")
    assert len(attempts) == 3


def test_manifest_read_retries_on_permission_error(
    out_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    out_dir.mkdir()
    media._update_manifest(out_dir, "x", {"hash": "h"})
    real_read_text = Path.read_text
    failures = [PermissionError(13, "in use")]

    def read_text(self: Path, *args: object, **kwargs: object) -> str:
        if self.name == media.MANIFEST_NAME and failures:
            raise failures.pop()
        return real_read_text(self, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(Path, "read_text", read_text)
    assert media._read_manifest(out_dir)["fixtures"] == {"x": {"hash": "h"}}
    assert failures == []


def test_parallel_generation_and_up_to_date_checks(fake_tools: FakeTools, out_dir: Path) -> None:
    """Many generator threads write the manifest while others read it."""
    names = ["anamorphic", "interlaced", "vfr", "vfr-mkv", "letterbox", "chapters"]
    media.generate(names, out_dir=out_dir, ffmpeg=str(fake_tools.ffmpeg), jobs=6)
    version = media.ffmpeg_version(str(fake_tools.ffmpeg))
    recipes = media.build_recipes()
    with ThreadPoolExecutor(max_workers=8) as pool:
        regen = pool.submit(
            media.generate, names, out_dir=out_dir, ffmpeg=str(fake_tools.ffmpeg), force=True
        )
        checks = [pool.submit(media.is_up_to_date, recipes[n], out_dir, version) for n in names * 5]
        regen.result()
        for check in checks:
            check.result()  # no exception
    assert all(media.is_up_to_date(recipes[n], out_dir, version) for n in names)


def _tables(font: bytes) -> dict[bytes, bytes]:
    _, num = struct.unpack(">IH", font[:6])
    tables = {}
    for i in range(num):
        tag, _, offset, length = struct.unpack(">4sIII", font[12 + 16 * i : 28 + 16 * i])
        tables[tag] = font[offset : offset + length]
    return tables


def test_box_font_structure() -> None:
    font = boxfont.build_font("Test Family")
    tables = _tables(font)
    assert set(tables) == {
        b"OS/2",
        b"cmap",
        b"glyf",
        b"head",
        b"hhea",
        b"hmtx",
        b"loca",
        b"maxp",
        b"name",
        b"post",
    }
    assert len(tables[b"head"]) == 54
    assert len(tables[b"hhea"]) == 36
    assert len(tables[b"OS/2"]) == 96
    assert struct.unpack(">I", tables[b"head"][12:16])[0] == 0x5F0F3CF5
    assert boxfont._checksum(font) == 0xB1B0AFBA  # checkSumAdjustment is right
    assert "Test Family".encode("utf-16-be") in tables[b"name"]


# --------------------------------------------------------------------------- vobsub


def _decode_rle(data: bytes, width: int, lines: int) -> list[list[int]]:
    """Minimal SPU RLE decoder (as in FFmpeg's dvdsubdec decode_run_2bit)."""
    nibbles = [n for b in data for n in (b >> 4, b & 0xF)]
    pos = 0
    rows: list[list[int]] = []
    for _ in range(lines):
        row: list[int] = []
        while len(row) < width:
            v = nibbles[pos]
            pos += 1
            for threshold in (0x4, 0x10, 0x40):
                if v >= threshold:
                    break
                v = (v << 4) | nibbles[pos]
                pos += 1
            count, color = v >> 2, v & 3
            row += [color] * (count or width - len(row))
        rows.append(row)
        pos += pos % 2  # byte align
    return rows


def test_vobsub_rle_round_trip() -> None:
    image = vobsub.bar_image(300, 7)
    for row in image:
        assert _decode_rle(vobsub._rle_line(row), 300, 1) == [row]
    assert _decode_rle(vobsub._rle_line([1] * 700), 700, 1) == [[1] * 700]


def test_vobsub_files() -> None:
    idx, sub = vobsub.vobsub(
        [vobsub.Event(500, 1500, 100), vobsub.Event(2000, 2500, 200)], language="en"
    )
    assert idx.startswith("# VobSub index file, v7")
    assert "timestamp: 00:00:00:500, filepos: 000000000" in idx
    assert "timestamp: 00:00:02:000, filepos: 000000800" in idx
    assert len(sub) == 2 * vobsub.PACK_SIZE
    assert sub[:4] == b"\x00\x00\x01\xba"
    with pytest.raises(ValueError, match="wider"):
        vobsub.vobsub([vobsub.Event(0, 1, 715)], language="en")
