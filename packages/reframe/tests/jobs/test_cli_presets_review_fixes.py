"""``reframe presets`` after the core-complete review (decision 0038 "Follow-up
(core-complete review, 2026-10-16)"): R5-9 (names from an imported file carry terminal
escapes) and the size cap of ``presets import`` (``/dev/zero``, a FIFO). Each test failed
before its fix."""

from __future__ import annotations

import json
import os
import sys
import threading
from pathlib import Path
from typing import Any

import pytest

from reframe import cli
from reframe.cli import EXIT_FAILED, EXIT_NOT_FOUND, EXIT_OK, printable, read_preset_file
from reframe.presets import builtin_presets
from reframe_testing import fake_tools as ft

from .conftest import invoke

EVIL = "Evil\x1b[31mRED\x1b[0m\nline2\x07\x9b2J\x1b]0;title\x07"


def _user_preset(preset_id: str, name: str, **changes: Any) -> dict[str, Any]:
    base = next(p for p in builtin_presets() if p.id == "fast-1080p30")
    preset = base.model_copy(
        update={"id": preset_id, "name": name, "category": "Custom", "built_in": False, **changes}
    )
    return preset.model_dump(mode="json")


def _no_controls(text: str) -> None:
    bad = [c for c in text if (ord(c) < 0x20 and c != "\n") or 0x7F <= ord(c) <= 0x9F]
    assert bad == [], repr(text)


# --------------------------------------------------------------------------- R5-9


def test_r5_9_printable_replaces_control_characters() -> None:
    assert printable(EVIL) == ("Evil�[31mRED�[0m�line2��2J�]0;title�")
    assert printable("Grain 1080p · ünïcödé") == "Grain 1080p · ünïcödé"
    assert cli._one_line("error:\n  two\tlines\x1b[2J") == "error: two lines�[2J"


def test_r5_9_names_from_an_imported_file_reach_the_terminal_without_escapes(
    cli_env: ft.FakeTools, tmp_path: Path
) -> None:
    """``reframe presets import`` and ``list`` printed ``ESC [31m`` (``od -c``: ``033 [ 3 1
    m``) from a hostile preset's name, category and id."""
    data = {
        "schema_version": 1,
        "presets": [_user_preset("u-\x1b[1mid", EVIL, category="Cat\x1b[5m")],
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
    # An error that names the preset is one clean line too.
    missing = invoke("presets", "export", "Evil\x1b[31m")
    _no_controls(missing.stderr)


# --------------------------------------------------------------------------- the size cap


def _refused(result: dict[str, Any] | tuple[int, str]) -> tuple[int, str]:
    assert isinstance(result, tuple), result
    return result


def test_import_refuses_a_file_larger_than_the_cap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(cli, "MAX_PRESET_FILE", 1000)
    big = tmp_path / "big.json"
    big.write_text(json.dumps({"schema_version": 1, "presets": [], "pad": "x" * 2000}))
    code, message = _refused(read_preset_file(big))
    assert code == EXIT_FAILED
    assert "larger than" in message


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX devices and FIFOs")
def test_import_never_reads_a_device_or_a_fifo(tmp_path: Path) -> None:
    """A device was read until memory ran out; a FIFO blocked the command.

    ``/dev/null`` stands in for ``/dev/zero``: the unfixed code ate all memory on the latter.
    """
    code, message = _refused(read_preset_file(Path("/dev/null")))
    assert code == EXIT_NOT_FOUND
    assert "not a regular file" in message
    if sys.platform != "win32":  # mypy --platform win32 has no os.mkfifo (skipped there)
        fifo = tmp_path / "fifo"
        os.mkfifo(fifo)
        result: list[dict[str, Any] | tuple[int, str]] = []
        reader = threading.Thread(target=lambda: result.append(read_preset_file(fifo)), daemon=True)
        reader.start()
        reader.join(5)
        if reader.is_alive():  # unblock the read of the unfixed code, then fail
            with fifo.open("wb") as writer:
                writer.write(b"{}")
            reader.join(5)
            pytest.fail("reading the FIFO blocked")
        code, message = _refused(result[0])
        assert code == EXIT_NOT_FOUND
        assert "not a regular file" in message


def test_import_from_stdin_is_capped(
    cli_env: ft.FakeTools, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(cli, "MAX_PRESET_FILE", 1000)
    from typer.testing import CliRunner

    result = CliRunner().invoke(
        cli.build_app(), ["presets", "import", "-"], input=b"{" + b" " * 5000 + b"}"
    )
    assert result.exit_code == EXIT_FAILED
    assert "larger than" in result.stderr
