"""Batch checks that compare files by identity, and overrides that keep the compiled columns.

A link or a hard link is the same file as its target. An override that changes the rules the
defaults compile to is invalid, so each cell stays under its column.
"""

from __future__ import annotations

import importlib.util
import ntpath
import os
import shutil
import sys
from collections.abc import AsyncIterator, Callable
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any

import pytest
from pydantic import TypeAdapter

from reframe.batch import group_sources, matrix_columns, resolve, resolve_group
from reframe.batch.report import matrix_lines
from reframe.jobs import OutputClaims, file_key, find_media_files
from reframe.models import (
    BatchResolution,
    JobSettings,
    JobTemplate,
    JsonPatchOp,
    LanguageSettings,
    Severity,
    ValidationIssue,
)
from reframe.probe import mediainfo
from reframe.queue.files import same_file
from reframe.service import Reframe
from reframe_testing import media


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
OPS = TypeAdapter(list[JsonPatchOp])
Media = Callable[[str], Path]
E01 = media.anime_file_name(1, 1)
E02 = media.anime_file_name(1, 2)
E01_OUT = "Anime.Show.S01E01.Pilot.mkv"


@pytest.fixture
def tree(tmp_path: Path) -> SimpleNamespace:
    real = tmp_path / "real"
    real.mkdir()
    a, b = real / "a.mkv", real / "b.mkv"
    a.write_bytes(b"a")
    b.write_bytes(b"b")
    link = tmp_path / "link"
    link.symlink_to(real, target_is_directory=True)
    a_link = tmp_path / "a-link.mkv"
    a_link.symlink_to(a)
    hard = tmp_path / "hard.mkv"
    os.link(b, hard)
    return SimpleNamespace(real=real, a=a, b=b, link=link, a_link=a_link, hard=hard)


def test_ra1_file_key_compares_files(tree: SimpleNamespace) -> None:
    a = file_key(tree.a)
    assert file_key(tree.a_link) == a
    assert file_key(tree.link / "a.mkv") == a
    assert file_key(str(tree.real / ".." / "real" / "a.mkv")) == a
    assert file_key(tree.hard) == file_key(tree.b)
    assert file_key(tree.a) != file_key(tree.b)
    new = file_key(tree.real / "new.mkv")
    assert new.startswith("path:")
    assert file_key(tree.link / "new.mkv") == new
    assert file_key(tree.link / "sub" / "new.mkv") == file_key(tree.real / "sub" / "new.mkv")
    # A new name is compared without case (macOS and Windows ignore it; the safe side on Linux).
    assert file_key(tree.link / "NEW.mkv") == new


def test_ra1_file_key_agrees_with_the_queue(tree: SimpleNamespace) -> None:
    pairs = [
        (tree.a, tree.a_link),
        (tree.a, tree.link / "a.mkv"),
        (tree.b, tree.hard),
        (tree.a, tree.b),
        (tree.real / "new.mkv", tree.link / "new.mkv"),
        (tree.real / "new.mkv", tree.real / "other.mkv"),
        (tree.hard, tree.link / "b.mkv"),
    ]
    for one, two in pairs:
        assert (file_key(one) == file_key(two)) == same_file(one, two), (one, two)


def _stat(dev: int, ino: int) -> os.stat_result:
    return os.stat_result((0o100644, ino, dev, 1, 0, 0, 0, 0, 0, 0))


def test_ra1_file_key_on_windows_mocked(monkeypatch: pytest.MonkeyPatch) -> None:
    """On Windows, ``realpath`` gives a mapped drive's UNC path (``GetFinalPathNameByHandle``)."""
    files = {
        "z:\\show\\e01.mkv": _stat(0x1234, 77),
        "\\\\server\\share\\show\\e01.mkv": _stat(0x1234, 77),
        "z:\\show\\e02.mkv": _stat(0x1234, 78),
        "z:\\show\\zero.mkv": _stat(0x1234, 0),
    }

    def stat(path: Any) -> os.stat_result:
        found = files.get(ntpath.normcase(os.fspath(path)))
        if found is None:
            raise FileNotFoundError(path)
        return found

    def realpath(path: Any) -> str:
        text: str = ntpath.normpath(os.fspath(path))
        if text[:2].lower() == "z:":
            return "\\\\server\\share" + text[2:]
        return text

    monkeypatch.setattr(os, "stat", stat)
    monkeypatch.setattr(os.path, "realpath", realpath)
    monkeypatch.setattr(os.path, "normcase", ntpath.normcase)
    assert file_key("Z:\\Show\\E01.mkv") == "file:4660:77"
    assert file_key("\\\\SERVER\\Share\\Show\\e01.MKV") == file_key("Z:\\Show\\E01.mkv")
    assert file_key("Z:\\Show\\E02.mkv") != file_key("Z:\\Show\\E01.mkv")
    # Not known: by its path, the mapped drive resolved to the UNC path.
    assert file_key("Z:\\Show\\Zero.mkv") == "path:\\\\server\\share\\show\\zero.mkv"
    # Two new outputs, one through the mapped drive and one through the UNC path.
    assert file_key("Z:\\Show\\New.mkv") == file_key("\\\\server\\share\\SHOW\\new.mkv")


def _job(source: Path, output: Path) -> JobSettings:
    return JobSettings.model_validate(
        {"source": {"path": str(source)}, "output": {"path": str(output)}}
    )


def _codes(issues: list[ValidationIssue]) -> list[str]:
    return [issue.code for issue in issues]


def test_ra1_output_claims_compare_files(tree: SimpleNamespace) -> None:
    claims = OutputClaims({tree.a: "[1/2] a.mkv", tree.link / "b.mkv": "[2/2] b.mkv"})
    (issue,) = claims.check(_job(tree.a, tree.real / "b.mkv"), "[1/2] a.mkv")
    assert issue.code == "batch.output_is_source"
    assert issue.severity is Severity.ERROR
    assert "([2/2] b.mkv)" in issue.message  # the label as given
    assert _codes(claims.check(_job(tree.a, tree.hard), "[1/2] a.mkv")) == [
        "batch.output_is_source"
    ]
    # The job's own source is not a claim here.
    assert claims.check(_job(tree.a, tree.a_link), "[1/2] a.mkv") == []
    assert claims.check(_job(tree.a, tree.link / "new.mkv"), "[1/2] a.mkv") == []
    assert _codes(claims.check(_job(tree.b, tree.real / "new.mkv"), "[2/2] b.mkv")) == [
        "batch.name_collision"
    ]


def test_ra1_find_media_files_takes_a_file_once(tree: SimpleNamespace) -> None:
    """Each file once, in the spelling it was first given."""
    found = find_media_files([tree.link, tree.real, tree.a_link, tree.hard])
    assert found.files == [tree.link / "a.mkv", tree.link / "b.mkv"]
    assert found.missing == []
    assert found.empty == []


def test_ra1_find_media_files_keeps_two_files_whose_names_differ_in_case(
    tmp_path: Path,
) -> None:
    upper = tmp_path / "E01.mkv"
    upper.write_bytes(b"1")
    lower = tmp_path / "e01.mkv"
    if lower.exists():
        pytest.skip("this file system ignores case")
    lower.write_bytes(b"2")
    assert find_media_files([upper, lower]).files == [upper, lower]


def test_ra1_file_key_never_raises_for_a_bad_path(tmp_path: Path) -> None:
    """A NUL character makes ``os.stat`` and ``realpath`` raise: the key uses the absolute path."""
    bad = str(tmp_path / "a\x00b.mkv")
    assert file_key(bad) == "path:" + os.path.normcase(os.path.abspath(bad)).casefold()
    source = tmp_path / "a.mkv"
    source.write_bytes(b"a")
    claims = OutputClaims({source: "[1/1] a.mkv"})
    assert claims.check(_job(source, Path(bad)), "[1/1] a.mkv") == []


def _jpn_template() -> JobTemplate:
    base: JobTemplate = A.builtin("h265-mkv-1080p")
    selection = base.audio_defaults.selection.model_copy(
        update={"languages": ["jpn"], "other_languages": "keep_all"}
    )
    defaults = base.audio_defaults.model_copy(update={"selection": selection})
    return base.model_copy(update={"audio_defaults": defaults})


def _replace(path: str, value: object) -> list[JsonPatchOp]:
    return OPS.validate_python([{"op": "replace", "path": path, "value": value}])


def test_ra3_an_override_that_changes_the_compiled_rules_is_invalid() -> None:
    """The override changes what the compiled audio columns mean, so it is invalid: the English
    dub would land under "A1 jpn"."""
    template = _jpn_template()
    sources = A.season(1)[:2]
    (group,) = group_sources(sources, "standard")
    columns = matrix_columns(template)
    assert [c.label for c in columns if c.kind == "audio"] == [
        "A1 jpn (defaults)",
        "A2 no listed language (defaults)",
        "A3 other languages (defaults)",
    ]
    override = _replace("/audio_defaults/selection/languages", ["eng", "jpn"])
    rows = resolve_group(group, template, sources, {str(A.path(1, 2)): override})
    e01, e02 = rows
    (invalid,) = [i for i in e02.issues if i.code == "batch.override_invalid"]
    assert invalid.path == "audio_defaults.selection"
    assert "A1 jpn, A2 no listed language, A3 other languages → A1 eng, A2 jpn, A3 no" in (
        invalid.message
    )
    assert e02.status == "error"
    audio = [(m.rule, m.status, m.streams) for m in e02.matches if m.kind == "audio"]
    assert audio == [(m.rule, m.status, m.streams) for m in e01.matches if m.kind == "audio"]
    assert audio[0] == (0, "exact", [1])  # A1 jpn: the Japanese track, not the dub
    assert e02.job is not None
    assert e01.job is not None
    assert [a.source_stream for a in e02.job.audio] == [a.source_stream for a in e01.job.audio]
    lines = matrix_lines(BatchResolution(group=group, columns=columns, rows=rows))
    a1 = lines[0].index("A1")
    assert lines[2][a1:].startswith("✓ #1")
    assert lines[3][a1:].startswith("✓ #1")


def test_ra3_an_override_inside_the_compiled_rules_is_applied() -> None:
    """A language override that keeps the structure is applied: here the A1 rule takes the dub."""
    template = _jpn_template()
    e02 = A.recorded(1, 2)
    swapped = resolve(template, e02, _replace("/audio_defaults/selection/languages", ["eng"]))
    assert "batch.override_invalid" not in _codes(swapped.issues)
    assert next((m.rule, m.streams) for m in swapped.matches if m.kind == "audio") == (0, [2])
    codec = resolve(
        template,
        e02,
        OPS.validate_python(
            [
                {
                    "op": "add",
                    "path": "/audio_defaults/codec_rules/0",
                    "value": {"codec": "libopus", "max_bitrate": 96},
                }
            ]
        ),
    )
    assert "batch.override_invalid" not in _codes(codec.issues)
    assert codec.job is not None
    assert {(a.encoder, a.bitrate) for a in codec.job.audio} == {("libopus", 96)}
    explicit = A.example_template()
    row = resolve(
        explicit, e02, _replace("/audio_defaults/selection/languages", ["eng", "jpn", "fre"])
    )
    assert "batch.override_invalid" not in _codes(row.issues)


def test_ra3_preferred_languages_count() -> None:
    """An empty language list compiles to the preferred languages: another number of them is
    invalid."""
    base = A.builtin("h265-mkv-1080p")
    e02 = A.recorded(1, 2)
    languages = LanguageSettings(preferred_audio=["jpn"])
    same = resolve(
        base, e02, _replace("/audio_defaults/selection/languages", ["jpn"]), languages=languages
    )
    assert "batch.override_invalid" not in _codes(same.issues)
    more = resolve(
        base,
        e02,
        _replace("/audio_defaults/selection/languages", ["jpn", "eng"]),
        languages=languages,
    )
    assert "batch.override_invalid" in _codes(more.issues)


@pytest.fixture
async def app(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[Reframe]:
    monkeypatch.setattr(mediainfo, "mediainfo_available", lambda: False)
    async with await Reframe.create(
        tmp_path / "config", tmp_path / "data", cache_dir=tmp_path / "cache"
    ) as reframe:
        yield reframe


def _real_and_link(fixture_media: Media, tmp_path: Path) -> tuple[Path, Path]:
    source = fixture_media("anime-s01")
    real = tmp_path / "media" / "real"
    real.mkdir(parents=True)
    for name in (E01, E02):
        shutil.copy2(source / name, real / name)
    link = tmp_path / "media" / "link"
    link.symlink_to(real, target_is_directory=True)
    return real, link


@pytest.mark.anyio
@pytest.mark.needs_ffmpeg
async def test_ra3_through_reframe_batch_resolve(
    app: Reframe, fixture_media: Media, tmp_path: Path
) -> None:
    """E02's override is found through a linked folder and is invalid, so the "A1 jpn" column
    shows the Japanese track in both rows."""
    real, link = _real_and_link(fixture_media, tmp_path)
    override = _replace("/audio_defaults/selection/languages", ["eng", "jpn"])
    resolution = await app.batch.resolve(
        _jpn_template(), [real / E01, real / E02], overrides={str(link / E02): override}
    )
    e01, e02 = resolution.rows
    assert "batch.override_invalid" in _codes(e02.issues)
    assert e02.override == override
    lines = matrix_lines(resolution)
    a1 = lines[0].index("A1")
    assert [line[a1:].split("   ")[0] for line in lines[2:]] == ["✓ #1", "✓ #1"]
    assert "batch.override_invalid" not in _codes(e01.issues)


@pytest.mark.anyio
@pytest.mark.needs_ffmpeg
async def test_ra1_resolve_batch_through_a_linked_folder(
    app: Reframe, fixture_media: Media, tmp_path: Path
) -> None:
    real, link = _real_and_link(fixture_media, tmp_path)
    user = real / E01_OUT
    shutil.copy2(fixture_media("multitrack"), user)
    grouping, resolutions = await app.batch.resolve_batch(None, [real / E01, link / E01_OUT])
    (left,) = grouping.issues
    assert left.code == "batch.already_encoded"
    assert left.message.startswith(f"{E01_OUT} is the planned output of {E01} with this preset:")
    (resolution,) = resolutions
    (row,) = resolution.rows
    assert "batch.output_is_source" in _codes(row.issues)
    user.unlink()
    grouping, resolutions = await app.batch.resolve_batch(None, [real / E01, link / E01])
    assert grouping.issues == []
    assert [r.path for res in resolutions for r in res.rows] == [real / E01]
    # The service dedupes the paths it is given.
    grouping, resolutions = await app.batch.resolve_batch(
        None, [real / E01, real / E02, link / E01, link / E02]
    )
    rows = [r for res in resolutions for r in res.rows]
    assert [r.path for r in rows] == [real / E01, real / E02]
    assert all("batch.name_collision" not in _codes(r.issues) and r.status != "error" for r in rows)
