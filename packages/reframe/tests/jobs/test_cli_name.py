"""``reframe name`` on the two demo cases of ``testdata/names.toml``: the folder name wins for
Hacksaw Ridge, the file name for a Sopranos season pack."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from reframe.cli import EXIT_OK, EXIT_USAGE, output_name, parsed_fields
from reframe.models import NameResult
from reframe_testing import fake_tools as ft

from .conftest import invoke

HACKSAW_DIR = (
    "Hacksaw.Ridge.2016.HYBRID.2160p.UHD.BluRay.REMUX.TrueHD.7.1.Atmos.DoVi.HDR.HEVC.HUN-HenDerson"
)
HACKSAW_FILE = "hacksawridge.2160p.remux-henderson.mkv"
SOPRANOS_DIR = "The.Sopranos.S03.1080p.BluRay.REMUX-Kataklysm"
SOPRANOS = [
    "The.Sopranos.S03E01.Mr.Ruggerios.Neighborhood.1080p.BluRay.REMUX-Kataklysm.mkv",
    "The.Sopranos.S03E02.Proshai.Livushka.1080p.BluRay.REMUX-Kataklysm.mkv",
    "The.Sopranos.S03E03.Fortunate.Son.1080p.BluRay.REMUX-Kataklysm.mkv",
]


@pytest.fixture
def library(cli_env: ft.FakeTools, tmp_path: Path) -> Path:
    root = tmp_path / "library"
    (root / HACKSAW_DIR).mkdir(parents=True)
    (root / HACKSAW_DIR / HACKSAW_FILE).write_bytes(b"x")
    (root / SOPRANOS_DIR).mkdir()
    for name in SOPRANOS:
        (root / SOPRANOS_DIR / name).write_bytes(b"x")
    return root


def rows(output: str) -> dict[str, str]:
    """``{"Source": …, "Name": …}`` of one result (wrapped values joined)."""
    found: dict[str, str] = {}
    key = ""
    for line in output.splitlines()[1:]:
        label, value = line[2:10].strip(), line[11:].strip()
        if label:
            key = label
            found[key] = value if key not in found else found[key] + " | " + value
        elif key:
            found[key] += value
    return found


def test_hacksaw_ridge_uses_the_folder_name(library: Path) -> None:
    result = invoke("name", str(library / HACKSAW_DIR / HACKSAW_FILE))
    assert result.exit_code == EXIT_OK, result.output
    assert result.stdout.startswith(HACKSAW_FILE + "\n")
    found = rows(result.stdout)
    assert found["Name"] == "Hacksaw.Ridge"
    assert found["Source"].startswith("folder (Folder name: 8 fields recognised")
    assert found["Parsed"].startswith("kind movie · name Hacksaw.Ridge · year 2016")
    assert found["Template"] == "{main_title} (movie)"
    assert found["File"] == str(library / HACKSAW_DIR / "Hacksaw.Ridge.mkv")


def test_sopranos_season_pack_uses_the_file_name(library: Path) -> None:
    result = invoke("name", str(library / SOPRANOS_DIR / SOPRANOS[1]))
    assert result.exit_code == EXIT_OK, result.output
    found = rows(result.stdout)
    assert found["Name"] == "The.Sopranos.S03E02.Proshai.Livushka"
    assert found["Source"].startswith("file (Season pack: the folder holds 3 episode files")
    assert "episode S03E02 · season 3 · episode title Proshai.Livushka" in found["Parsed"]
    assert found["Template"] == "{main_title} (episode)"


def test_a_folder_names_its_media_files(library: Path) -> None:
    result = invoke("name", str(library / SOPRANOS_DIR))
    assert result.exit_code == EXIT_OK, result.output
    names = [line[11:] for line in result.stdout.splitlines() if line.startswith("  Name ")]
    assert names == [
        "The.Sopranos.S03E01.Mr.Ruggerios.Neighborhood",
        "The.Sopranos.S03E02.Proshai.Livushka",
        "The.Sopranos.S03E03.Fortunate.Son",
    ]


def test_template_and_preset(library: Path) -> None:
    file = str(library / HACKSAW_DIR / HACKSAW_FILE)
    result = invoke("name", file, "--template", "{name}< ({year})>", "--preset", "Fast 1080p30")
    assert result.exit_code == EXIT_OK, result.output
    found = rows(result.stdout)
    assert found["Name"] == "Hacksaw.Ridge (2016)"
    assert found["File"].endswith("Hacksaw.Ridge (2016).mp4")


def test_bad_template_is_a_usage_error(library: Path) -> None:
    result = invoke("name", str(library / HACKSAW_DIR / HACKSAW_FILE), "-t", "{nme}")
    assert result.exit_code == EXIT_USAGE
    assert result.stderr.startswith("error: --template: Unknown variable {nme}")
    assert result.stdout == ""


def test_a_path_that_does_not_exist_is_named_from_its_text(
    cli_env: ft.FakeTools, tmp_path: Path
) -> None:
    path = tmp_path / HACKSAW_DIR / HACKSAW_FILE
    result = invoke("name", str(path))
    assert result.exit_code == EXIT_OK, result.output
    found = rows(result.stdout)
    assert found["Name"] == "Hacksaw.Ridge"
    assert "The file does not exist" in found["Note"]


def test_empty_folder(cli_env: ft.FakeTools, tmp_path: Path) -> None:
    result = invoke("name", str(tmp_path))
    assert result.exit_code == 1
    assert "no media files in this folder" in result.stderr


def test_json(library: Path) -> None:
    result = invoke("name", "--json", str(library / SOPRANOS_DIR / SOPRANOS[1]))
    assert result.exit_code == EXIT_OK, result.output
    [data] = json.loads(result.stdout)
    named = NameResult.model_validate(data)
    assert output_name(named) == "The.Sopranos.S03E02.Proshai.Livushka"
    assert named.season_pack


def test_unknown_preset(library: Path) -> None:
    result = invoke("name", str(library), "--preset", "nope")
    assert result.exit_code == EXIT_USAGE


def test_output_name_and_fields_helpers() -> None:
    result = NameResult(
        source="file",
        reason="r",
        template="{name}/{name}",
        template_kind="movie",
        relative_path="A/A.mkv",
        extension="mkv",
    )
    assert output_name(result) == "A/A"
    assert parsed_fields(result) == "kind movie"
    odd = result.model_copy(update={"relative_path": "A.mkv.tmp"})
    assert output_name(odd) == "A.mkv.tmp"
    multi = result.model_copy(
        update={"fields": result.fields.model_copy(update={"episodes": [2, 3]})}
    )
    assert parsed_fields(multi) == "kind movie · episode numbers 2, 3"
