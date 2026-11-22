"""Control characters from files and imported presets never reach the terminal (``printable``)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from reframe import cli
from reframe.cli import EXIT_OK, printable
from reframe_testing import fake_tools as ft
from reframe_testing import media
from reframe_testing.cli import invoke

from .conftest import Queues, media_file, probe_json, probe_rule, user_preset
from .test_cli_output_names import E01, S01, anime, two_sources

EVIL = "Evil\x1b[31mRED\x1b[0m\nline2\x07\x9b2J\x1b]0;title\x07"
#: Windows file names cannot hold control characters; titles (metadata) can.
NAMES_HOLD_ESC = sys.platform != "win32"


def _no_controls(text: str) -> None:
    bad = [c for c in text if (ord(c) < 0x20 and c != "\n") or 0x7F <= ord(c) <= 0x9F]
    assert bad == [], repr(text)


def test_printable_replaces_control_characters() -> None:
    assert printable(EVIL) == ("Evil�[31mRED�[0m�line2��2J�]0;title�")
    assert printable("Grain 1080p · ünïcödé") == "Grain 1080p · ünïcödé"
    assert cli._one_line("error:\n  two\tlines\x1b[2J") == "error: two lines�[2J"


def test_names_from_an_imported_file_reach_the_terminal_without_escapes(
    cli_env: ft.FakeTools, tmp_path: Path
) -> None:
    data = {
        "schema_version": 1,
        "presets": [user_preset("u-\x1b[1mid", EVIL, category="Cat\x1b[5m")],
    }
    file = tmp_path / "hostile.json"
    file.write_text(json.dumps(data), encoding="utf-8")
    imported = invoke("presets", "import", str(file))
    assert imported.exit_code == EXIT_OK, imported.output
    _no_controls(imported.stdout)
    _no_controls(imported.stderr)
    listed = invoke("presets", "list")
    assert listed.exit_code == EXIT_OK, listed.output
    _no_controls(listed.stdout)
    assert "Evil�[31mRED" in listed.stdout
    # The JSON output keeps the names as they are (escaped by JSON).
    as_json = invoke("presets", "list", "--json")
    names = [p["name"] for p in json.loads(as_json.stdout)["presets"]]
    assert any(name.startswith("Evil\x1b[31mRED") for name in names), names
    missing = invoke("presets", "export", "Evil\x1b[31m")
    _no_controls(missing.stderr)


ESC = "\x1b"


def import_evil_preset(tmp_path: Path) -> None:
    exported = tmp_path / "h265.json"
    assert invoke("presets", "export", "H.265 MKV 1080p", "--output", str(exported)).exit_code == 0
    data = json.loads(exported.read_text(encoding="utf-8"))
    data["presets"][0].update(id="evil", name="Evil\x1b[31mRED", built_in=False)
    data["default_preset_id"] = None
    exported.write_text(json.dumps(data), encoding="utf-8")
    assert invoke("presets", "import", str(exported)).exit_code == 0


def test_preset_line_of_batch_and_encode_has_no_control_characters(
    cli_env: ft.FakeTools,
    queues: Queues,
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
    assert batch.stdout.splitlines()[0] == "Preset: Evil\ufffd[31mRED"
    assert encode.stdout.splitlines()[0] == "Preset: Evil\ufffd[31mRED"


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


def test_titles_and_file_names_in_the_batch_output_are_printable(
    cli_env: ft.FakeTools, tmp_path: Path
) -> None:
    """A near member's difference names a track title with ESC (E05's commentary), two releases
    of E01 are labelled by their file names (one with ESC, where file names can hold it), and
    the matrix shows that name and its output name: no ESC on stdout."""
    folder = tmp_path / "media" / S01
    e01 = media_file(folder, E01)
    e05 = media_file(folder, media.anime_file_name(1, 5))
    commentary = escaped_probe(tmp_path, anime(1, 5), "Commentary", "Comm\x1b[32mGreen")
    rules = [probe_rule(commentary, e05), probe_rule(probe_json(anime(1, 1)), e01)]
    if NAMES_HOLD_ESC:
        evil = media_file(folder, "Anime.Show.S01E01.\x1b[31mRed.WEB.x264-GRP.mkv")
        rules.append(probe_rule(probe_json(anime(1, 1)), evil))
    cli_env.set_scenario(ft.Scenario(rules))
    result = invoke("batch", str(folder), "--dry-run")
    assert result.exit_code == EXIT_OK, result.output
    out = result.stdout
    assert ESC not in out, out
    assert 'extra track (eng AC-3 2.0 "Comm\ufffd[32mGreen")' in out
    if NAMES_HOLD_ESC:
        # The member list and the matrix row label.
        assert out.count("Anime.Show.S01E01.\ufffd[31mRed.WEB.x264-GRP.mkv") == 2
        assert "Anime.Show.S01E01.[31mRed.mkv" in out


def test_reframe_probe_prints_titles_without_control_characters(
    cli_env: ft.FakeTools, tmp_path: Path
) -> None:
    """``reframe probe``: a track title, the container title and a chapter title come from the
    file; they are shown through ``printable`` too (``--json`` keeps them)."""
    file = media_file(tmp_path / "media", "Movie\x1b[35m.mkv" if NAMES_HOLD_ESC else "Movie.mkv")
    data = json.loads(probe_json(anime(1, 5)).read_text(encoding="utf-8"))
    for stream in data["streams"]:
        if stream.get("tags", {}).get("title") == "Commentary":
            stream["tags"]["title"] = "Comm\x1b[32mGreen"
    data["format"]["tags"]["title"] = "Movie\x1b]0;PWNED\x07"
    data["chapters"] = [
        {
            "id": 1,
            "time_base": "1/1000",
            "start": 0,
            "start_time": "0.000000",
            "end": 1000,
            "end_time": "1.000000",
            "tags": {"title": "Open\x1b[2Jing\nNext"},
        }
    ]
    path = tmp_path / "probe.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    cli_env.set_scenario(ft.Scenario([probe_rule(path)]))
    result = invoke("probe", str(file))
    assert result.exit_code == EXIT_OK, result.output
    assert ESC not in result.stdout, result.stdout
    assert "\x07" not in result.stdout
    assert "Comm\ufffd[32mGreen" in result.stdout
    assert "Movie\ufffd]0;PWNED\ufffd" in result.stdout
    assert "   1  0:00:00.000  Open\ufffd[2Jing\ufffdNext" in result.stdout.splitlines()
    raw = json.loads(invoke("probe", str(file), "--json").stdout)
    assert raw["container"]["title"] == "Movie\x1b]0;PWNED\x07"
    assert raw["chapters"][0]["title"] == "Open\x1b[2Jing\nNext"
