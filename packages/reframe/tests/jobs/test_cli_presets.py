"""``reframe presets list|export|import`` (C-15; demo 8 of the core breakdown: the list and an
export → import round trip). Private config folders (``cli_env``)."""

from __future__ import annotations

import asyncio
import io
import json
import os
import sys
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from reframe import cli
from reframe.cli import (
    EXIT_FAILED,
    EXIT_NOT_FOUND,
    EXIT_OK,
    EXIT_USAGE,
    build_app,
    preset_rows,
    read_preset_file,
    write_text_file,
)
from reframe.models import Preset
from reframe.presets import builtin_presets
from reframe_testing import fake_tools as ft

from .conftest import WIDTH, invoke

BUILTINS = builtin_presets()


def config_dir(tmp_path: Path) -> Path:
    return tmp_path / "config"


def user_preset(preset_id: str, name: str, **changes: Any) -> dict[str, Any]:
    """A user preset (a copy of *Fast 1080p30*) as JSON."""
    base = next(p for p in BUILTINS if p.id == "fast-1080p30")
    preset = base.model_copy(
        update={"id": preset_id, "name": name, "category": "Custom", "built_in": False, **changes}
    )
    return preset.model_dump(mode="json")


def write_presets(
    tmp_path: Path, presets: list[dict[str, Any]], default: str | None = None
) -> Path:
    folder = config_dir(tmp_path)
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "presets.json"
    data = {"schema_version": 1, "presets": presets, "default_preset_id": default}
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def stored(tmp_path: Path) -> dict[str, Any]:
    data: dict[str, Any] = json.loads(
        (config_dir(tmp_path) / "presets.json").read_text(encoding="utf-8")
    )
    return data


# --------------------------------------------------------------------------- list


def test_list_shows_builtins_then_user_presets_with_the_default(
    cli_env: ft.FakeTools, tmp_path: Path
) -> None:
    """Demo 8: ``reframe presets list``."""
    write_presets(
        tmp_path, [user_preset("u-1", "Anime 720p"), user_preset("u-2", "Grain")], default="u-2"
    )
    result = invoke("presets", "list")
    assert result.exit_code == EXIT_OK, result.output
    lines = result.stdout.splitlines()
    assert lines[0].split() == ["Name", "Category", "Id", "Kind"]
    rows = lines[1:-2]
    assert len(rows) == len(BUILTINS) + 2
    assert rows[0].split()[-2:] == ["very-fast-1080p30", "built-in"]
    assert rows[0].startswith("   Very Fast 1080p30 ")
    assert rows[-2].split() == ["Anime", "720p", "Custom", "u-1", "user"]
    assert rows[-1].startswith("*  Grain ")
    assert rows[-1].split()[-3:] == ["Custom", "u-2", "user"]
    assert sum(1 for row in rows if row.startswith("*")) == 1
    assert lines[-2] == ""
    assert lines[-1] == f"* default preset · {len(BUILTINS)} built-in, 2 user presets"
    assert result.stderr == ""


def test_list_marks_the_builtin_default(cli_env: ft.FakeTools) -> None:
    result = invoke("presets", "list")
    assert result.exit_code == EXIT_OK
    default = [line for line in result.stdout.splitlines() if line.startswith("*  ")]
    assert len(default) == 1
    assert default[0].split()[1:4] == ["H.265", "MKV", "1080p"]
    assert result.stdout.splitlines()[-1].endswith(", 0 user presets")


def test_list_json(cli_env: ft.FakeTools, tmp_path: Path) -> None:
    write_presets(tmp_path, [user_preset("u-1", "Anime 720p", description="cel")])
    result = invoke("presets", "list", "--json")
    assert result.exit_code == EXIT_OK, result.output
    data = json.loads(result.stdout)
    assert data["default_preset_id"] == "h265-mkv-1080p"
    assert [p["id"] for p in data["presets"]] == [*(p.id for p in BUILTINS), "u-1"]
    assert data["presets"][-1] == {
        "id": "u-1",
        "name": "Anime 720p",
        "category": "Custom",
        "description": "cel",
        "built_in": False,
        "default": False,
    }
    assert sum(p["default"] for p in data["presets"]) == 1


def test_list_prints_a_damaged_file_as_a_warning(cli_env: ft.FakeTools, tmp_path: Path) -> None:
    folder = config_dir(tmp_path)
    folder.mkdir(parents=True)
    (folder / "presets.json").write_text("{broken", encoding="utf-8")
    result = invoke("presets", "list")
    assert result.exit_code == EXIT_OK
    assert result.stderr.startswith("warning: ")
    assert "Traceback" not in result.stderr


def test_preset_rows_align_the_columns() -> None:
    presets = [
        Preset(id="a", name="A", category="General", built_in=True),
        Preset(id="long-id", name="Longer name", category="Custom"),
    ]
    assert preset_rows(presets, "long-id") == [
        "   Name         Category  Id       Kind",
        "   A            General   a        built-in",
        "*  Longer name  Custom    long-id  user",
        "",
        "* default preset · 1 built-in, 1 user preset",
    ]


# --------------------------------------------------------------------------- export → import


def test_export_import_round_trip(
    cli_env: ft.FakeTools, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Demo 8: every user preset exported to a file, imported into an empty config: the same
    presets, ids and default."""
    presets = [user_preset("u-1", "Anime 720p"), user_preset("u-2", "Grain", description="x")]
    write_presets(tmp_path, presets, default="u-2")
    out = tmp_path / "backup.json"
    result = invoke("presets", "export", "-o", str(out))
    assert result.exit_code == EXIT_OK, result.output
    assert result.stdout == f"Exported 2 presets to {out}.\n"
    document = json.loads(out.read_text(encoding="utf-8"))
    assert document["schema_version"] == 1
    assert [p["id"] for p in document["presets"]] == ["u-1", "u-2"]
    assert document["default_preset_id"] == "u-2"

    monkeypatch.setenv("REFRAME_CONFIG_DIR", str(tmp_path / "fresh"))
    result = invoke("presets", "import", str(out))
    assert result.exit_code == EXIT_OK, result.output
    lines = result.stdout.splitlines()
    assert lines[0] == f"Imported 2 presets from {out} (on a conflict: rename):"
    assert lines[1] == "  Anime 720p  (u-1)"
    assert lines[2] == "  Grain  (u-2)"
    assert result.stderr == ""
    fresh = json.loads((tmp_path / "fresh" / "presets.json").read_text(encoding="utf-8"))
    assert fresh["presets"] == document["presets"]
    assert fresh["default_preset_id"] == "u-2"
    listed = invoke("presets", "list").stdout
    assert "*  Grain" in listed


def test_export_to_stdout_by_name_and_id(cli_env: ft.FakeTools, tmp_path: Path) -> None:
    write_presets(tmp_path, [user_preset("u-1", "Anime 720p"), user_preset("u-2", "Grain")])
    result = invoke("presets", "export", "grain", "fast-720p30", "GRAIN")
    assert result.exit_code == EXIT_OK, result.output
    document = json.loads(result.stdout)
    assert [p["name"] for p in document["presets"]] == ["Grain", "Fast 720p30"]
    assert document["presets"][1]["built_in"] is True
    assert result.stderr == ""


def test_export_dash_is_stdout(cli_env: ft.FakeTools, tmp_path: Path) -> None:
    write_presets(tmp_path, [user_preset("u-1", "Anime 720p")])
    result = invoke("presets", "export", "-o", "-")
    assert result.exit_code == EXIT_OK
    assert json.loads(result.stdout)["presets"][0]["id"] == "u-1"


def test_export_without_user_presets_warns(cli_env: ft.FakeTools) -> None:
    result = invoke("presets", "export")
    assert result.exit_code == EXIT_OK
    assert json.loads(result.stdout)["presets"] == []
    assert result.stderr.startswith("warning: there are no user presets to export")


def test_export_keeps_presets_of_a_newer_reframe(cli_env: ft.FakeTools, tmp_path: Path) -> None:
    """Decision 0028: a newer preset is exported unchanged, with a warning."""
    future = {"id": "f", "name": "Future", "schema_version": 5, "video": {"encoder": "h266"}}
    write_presets(tmp_path, [future, user_preset("u-1", "Mine")])
    result = invoke("presets", "export")
    assert result.exit_code == EXIT_OK, result.output
    document = json.loads(result.stdout)
    assert document["presets"][0]["id"] == "u-1"
    assert document["presets"][1] == future
    assert result.stderr.startswith("warning: ")
    assert "Future" in result.stderr


def test_export_unknown_name_is_a_usage_error(cli_env: ft.FakeTools) -> None:
    result = invoke("presets", "export", "fast 1080")
    assert result.exit_code == EXIT_USAGE
    assert result.stdout == ""
    assert result.stderr.startswith('error: there is no preset named "fast 1080". Did you mean')


def test_export_to_a_folder_or_a_bad_path(cli_env: ft.FakeTools, tmp_path: Path) -> None:
    result = invoke("presets", "export", "-o", str(tmp_path))
    assert result.exit_code == EXIT_USAGE
    assert result.stderr == f"error: {tmp_path} is a folder: -o needs a file name.\n"
    missing = tmp_path / "no" / "such" / "folder" / "p.json"
    result = invoke("presets", "export", "fast-720p30", "-o", str(missing))
    assert result.exit_code == EXIT_FAILED
    assert result.stderr.startswith(f"error: {missing} cannot be written:")
    assert "Traceback" not in result.stderr


def test_write_text_file_leaves_no_temporary_file(tmp_path: Path) -> None:
    target = tmp_path / "out.json"
    write_text_file(target, "one")
    write_text_file(target, "two")
    assert target.read_text(encoding="utf-8") == "two"
    assert [p.name for p in tmp_path.iterdir()] == ["out.json"]
    with pytest.raises(UnicodeEncodeError):
        write_text_file(target, "\udcff")
    assert target.read_text(encoding="utf-8") == "two"
    assert [p.name for p in tmp_path.iterdir()] == ["out.json"]


# --------------------------------------------------------------------------- import


@pytest.fixture
def backup(tmp_path: Path) -> Path:
    path = tmp_path / "backup.json"
    data = {
        "schema_version": 1,
        "presets": [user_preset("u-1", "Anime 720p"), user_preset("u-9", "Fast 720p30")],
        "default_preset_id": None,
    }
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


@pytest.mark.parametrize(
    ("policy", "expected"),
    [
        (
            "rename",
            [
                "Imported 2 presets from {file} (on a conflict: rename):",
                "  Anime 720p (2)  ({id0}), renamed from “Anime 720p”",
                "  Fast 720p30 (2)  ({id1}), renamed from “Fast 720p30”",
            ],
        ),
        (
            "replace",
            [
                "Imported 2 presets from {file} (on a conflict: replace):",
                "  Anime 720p  (u-1)",
                "  Fast 720p30 (2)  ({id1}), renamed from “Fast 720p30”",
                "  Replaced: Anime 720p",
            ],
        ),
        ("skip", ["Nothing was imported from {file}.", "  Skipped: Anime 720p, Fast 720p30"]),
    ],
)
def test_import_conflicts(
    cli_env: ft.FakeTools, tmp_path: Path, backup: Path, policy: str, expected: list[str]
) -> None:
    """``u-1`` exists with the same name; ``Fast 720p30`` is a built-in's name (never
    replaced: renamed)."""
    write_presets(tmp_path, [user_preset("u-1", "Anime 720p", description="old")])
    result = invoke("presets", "import", str(backup), "--on-conflict", policy)
    assert result.exit_code == EXIT_OK, result.output
    users = stored(tmp_path)["presets"]
    ids = [p["id"] for p in users[1:]] if policy == "rename" else [None, users[-1]["id"]]
    lines = [
        line.format(file=backup, id0=ids[0], id1=ids[-1] if ids else None) for line in expected
    ]
    assert result.stdout.splitlines() == lines
    if policy == "replace":
        assert users[0]["description"] != "old"  # overwritten by the file's version
    if policy == "skip":
        assert len(users) == 1


def test_import_from_stdin(cli_env: ft.FakeTools, tmp_path: Path, backup: Path) -> None:
    result = CliRunner().invoke(
        build_app(),
        ["presets", "import", "-"],
        input=backup.read_bytes(),
        env={"COLUMNS": WIDTH},
    )
    assert result.exit_code == EXIT_OK, result.output
    assert result.stdout.startswith("Imported 2 presets from stdin")


def test_import_missing_file(cli_env: ft.FakeTools, tmp_path: Path) -> None:
    result = invoke("presets", "import", str(tmp_path / "nope.json"))
    assert result.exit_code == EXIT_NOT_FOUND
    assert result.stdout == ""
    assert result.stderr == f"error: {tmp_path / 'nope.json'}: the file does not exist.\n"
    folder = invoke("presets", "import", str(tmp_path))
    assert folder.exit_code == EXIT_NOT_FOUND
    assert "is a folder" in folder.stderr


@pytest.mark.parametrize(
    ("content", "message"),
    [
        (b"{broken", "it is not JSON"),
        (b"[1, 2]", "it is not a JSON object"),
        (b"\xff\xfe not utf-8 \xff", "it is not UTF-8 text"),
        (b"[" * 100_000 + b"]" * 100_000, "nested too deeply"),
    ],
)
def test_import_not_a_preset_file(
    cli_env: ft.FakeTools, tmp_path: Path, content: bytes, message: str
) -> None:
    path = tmp_path / "bad.json"
    path.write_bytes(content)
    result = invoke("presets", "import", str(path))
    assert result.exit_code == EXIT_FAILED
    assert result.stdout == ""
    assert result.stderr.startswith(f"error: {path} is not a Reframe preset file: ")
    assert message in result.stderr
    assert "Traceback" not in result.stderr


def test_import_a_file_the_store_refuses(cli_env: ft.FakeTools, tmp_path: Path) -> None:
    path = tmp_path / "newer.json"
    path.write_text(json.dumps({"schema_version": 99, "presets": []}), encoding="utf-8")
    result = invoke("presets", "import", str(path))
    assert result.exit_code == EXIT_FAILED
    assert result.stdout.splitlines()[0] == f"Nothing was imported from {path}."
    assert "error    The file was written by a newer Reframe" in result.stdout
    assert "[presets.import_newer]" in result.stdout


def test_import_with_an_invalid_preset_fails_but_keeps_the_good_ones(
    cli_env: ft.FakeTools, tmp_path: Path
) -> None:
    path = tmp_path / "mixed.json"
    data = {"schema_version": 1, "presets": [{"id": "x"}, user_preset("u-5", "Good")]}
    path.write_text(json.dumps(data), encoding="utf-8")
    result = invoke("presets", "import", str(path))
    assert result.exit_code == EXIT_FAILED
    assert result.stdout.splitlines()[:3] == [
        f"Imported 1 preset from {path} (on a conflict: rename):",
        "  Good  (u-5)",
        "  Skipped: preset #1",
    ]
    assert "Issues (0 errors, 1 warning, 0 info)" in result.stdout
    assert "[preset.invalid]" in result.stdout
    assert [p["id"] for p in stored(tmp_path)["presets"]] == ["u-5"]


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX permissions")
@pytest.mark.skipif(hasattr(os, "geteuid") and os.geteuid() == 0, reason="root reads anything")
def test_import_unreadable_file(cli_env: ft.FakeTools, tmp_path: Path, backup: Path) -> None:
    backup.chmod(0)
    try:
        result = invoke("presets", "import", str(backup))
    finally:
        backup.chmod(0o644)
    assert result.exit_code == EXIT_NOT_FOUND
    assert result.stderr.startswith(f"error: {backup} cannot be read: ")


def test_read_preset_file_strips_a_bom(tmp_path: Path) -> None:
    path = tmp_path / "bom.json"
    path.write_bytes(b"\xef\xbb\xbf" + b'{"schema_version": 1}')
    assert read_preset_file(path) == {"schema_version": 1}


def test_help() -> None:
    for command, texts in (
        ("list", ("--json", "default", "Exit codes")),
        ("export", ("NAME_OR_ID", "--output", "every user preset", "newer", "Exit codes")),
        ("import", ("FILE", "--on-conflict", "rename", "replace", "skip", "Exit codes")),
    ):
        result = invoke("presets", command, "--help")
        assert result.exit_code == 0
        for text in texts:
            assert text in result.stdout, (command, text)
    assert "export" in invoke("presets", "--help").stdout


def test_human_output_survives_an_ascii_stdout(cli_env: ft.FakeTools, tmp_path: Path) -> None:
    """A stdout that cannot encode ``·`` (``*`` legend) or ``“”`` (renamed) does not raise."""
    write_presets(tmp_path, [user_preset("u-1", "Ünïcode ✓")])
    buffer = io.BytesIO()
    stream = io.TextIOWrapper(buffer, encoding="ascii", errors="strict")
    cli._replace_unencodable(stream)
    old = sys.stdout
    sys.stdout = stream
    try:
        assert asyncio.run(cli.run_presets_list(as_json=False)) == EXIT_OK
        stream.flush()
    finally:
        sys.stdout = old
    text = buffer.getvalue().decode("ascii")
    assert "u-1" in text
