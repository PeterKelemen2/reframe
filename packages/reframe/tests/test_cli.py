"""``reframe probe`` and ``reframe version``: human and ``--json`` output, and error exits."""

from __future__ import annotations

import io
import json
import os
import re
import subprocess
import sys
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from rich.console import Console
from syrupy.assertion import SnapshotAssertion
from typer.testing import CliRunner, Result

from reframe import __version__, cli
from reframe.cli import (
    EXIT_NO_FFPROBE,
    EXIT_NOT_FOUND,
    EXIT_OK,
    EXIT_PROBE_FAILED,
    EXIT_USAGE,
    TIMES,
    build_app,
    error_message,
    fmt_bitrate,
    fmt_bps,
    fmt_channels,
    fmt_color,
    fmt_duration,
    fmt_events,
    fmt_flags,
    fmt_hdr,
    fmt_language,
    fmt_sample,
    fmt_size,
    make_console,
    origin_text,
    render_source,
    role_badge,
    video_details,
    video_line,
)
from reframe.models import (
    AttachedPicture,
    Attachment,
    AudioStream,
    BitrateInfo,
    BitrateSource,
    Chapter,
    ColorInfo,
    ContainerInfo,
    DataStream,
    DolbyVisionInfo,
    FieldOrder,
    HdrFormat,
    HdrInfo,
    MediaSource,
    Rational,
    RoleEvidence,
    SourceRef,
    SubtitleStream,
    ToolInfo,
    ToolOrigin,
    ToolStatus,
    TrackRole,
    TrackRoleInfo,
    VideoStream,
)
from reframe.platform import longpath
from reframe.service import ProbeError, ProbeErrorKind
from reframe.tools import ENV_VARS
from reframe_testing import fake_tools as ft

REPO = Path(__file__).resolve().parents[3]
PROBES = REPO / "testdata" / "probes"
INDEX: dict[str, dict[str, Any]] = json.loads((PROBES / "index.json").read_text(encoding="utf-8"))[
    "probes"
]
X = TIMES  # the multiplication sign between width and height
WIDTH = "200"
#: SGR colour parameters (foreground 30-38, 90-97; background 40-48, 100-107).
COLOUR_SGR = re.compile(r"\x1b\[(?:\d+;)*(?:3[0-8]|9[0-7]|4[0-8]|10[0-7])(?:;\d+)*m")

Media = Callable[[str], Path]


def invoke(*args: str, env: dict[str, str] | None = None) -> Result:
    return CliRunner().invoke(build_app(), list(args), env={"COLUMNS": WIDTH, **(env or {})})


def assert_clean_failure(result: Result, code: int) -> str:
    """Exit ``code``, nothing on stdout, one ``error:`` line on stderr, no traceback."""
    assert result.exit_code == code, (result.stdout, result.stderr)
    assert result.stdout == ""
    assert "Traceback" not in result.stderr
    lines = result.stderr.splitlines()
    assert len(lines) == 1, result.stderr
    assert lines[0].startswith("error: ")
    return lines[0]


def table_rows(output: str) -> dict[str, list[str]]:
    """Rows of the rich tables by their ``#`` cell; a cell over several lines is joined with
    newlines. Box characters as rich draws them for a UTF-8 stream."""
    rows: dict[str, list[str]] = {}
    current: list[str] | None = None
    for line in output.splitlines():
        if not line.startswith("│"):
            current = None if not line.startswith(("├", "┌", "└")) else current
            continue
        cells = [c.strip() for c in line.strip("│").split("│")]
        if cells[0] == "#":
            continue
        if cells[0]:
            current = rows.setdefault(cells[0], cells)
        elif current is not None:
            for i, cell in enumerate(cells):
                if cell:
                    current[i] = f"{current[i]}\n{cell}" if current[i] else cell
    return rows


def roles_and_flags(roles: list[TrackRoleInfo], flags: list[str]) -> str:
    lines = []
    if roles:
        lines.append(" ".join(role_badge(r) for r in roles))
    if flags:
        lines.append(", ".join(flags))
    return "\n".join(lines)


def assert_every_track(output: str, source: MediaSource) -> None:
    rows = table_rows(output)
    for a in source.audio:
        delay = (
            [f"delay {round(a.delay * 1000):+d} ms"] if a.delay and round(a.delay * 1000) else []
        )
        codec = (a.display_codec or "") + (" lossless" if a.lossless else "")
        assert rows[str(a.index)] == [
            str(a.index),
            fmt_language(a.language),
            a.title or "—",
            codec,
            fmt_channels(a),
            fmt_sample(a.sample_rate, a.bit_depth),
            fmt_bitrate(a.bitrate),
            roles_and_flags(a.roles, [*fmt_flags(a.disposition), *delay]),
        ], a
    for s in source.subtitles:
        kind = s.subtitle_kind + (f" {s.width}{X}{s.height}" if s.width and s.height else "")
        assert rows[str(s.index)] == [
            str(s.index),
            fmt_language(s.language),
            s.title or "—",
            s.display_codec or "",
            kind,
            fmt_events(s),
            roles_and_flags(s.roles, fmt_flags(s.disposition)),
        ], s
    streams: list[AudioStream | SubtitleStream] = [*source.audio, *source.subtitles]
    for stream in streams:
        for role in stream.roles:
            assert f"  #{stream.index}  {role_badge(role)}  {role.detail}" in output
    for v in source.video:
        assert video_line(v) in output
    assert f"Audio ({len(source.audio)})" in output
    assert f"Subtitles ({len(source.subtitles)})" in output


@pytest.fixture
def cache_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """A private probe cache; the environment's tool settings (CI's override) stay."""
    monkeypatch.setenv("REFRAME_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("REFRAME_CONFIG_DIR", str(tmp_path / "config"))
    return tmp_path


@pytest.fixture
def fake_env(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, fake_tools: ft.FakeTools
) -> ft.FakeTools:
    """The fake ffmpeg and ffprobe, MediaInfo off, and private folders."""
    for var in ENV_VARS.values():
        monkeypatch.delenv(var, raising=False)
    for name in ("config", "data", "cache"):
        monkeypatch.setenv(f"REFRAME_{name.upper()}_DIR", str(tmp_path / name))
    monkeypatch.setenv("REFRAME_FFMPEG", str(fake_tools.ffmpeg))
    monkeypatch.setenv("REFRAME_FFPROBE", str(fake_tools.ffprobe))
    monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.delenv("FORCE_COLOR", raising=False)
    return fake_tools


def replay(fake: ft.FakeTools, probe: Path, frames: Path | None = None) -> None:
    """The fake ffprobe prints ``probe`` (and ``frames`` for the first-frame read)."""
    rules = [
        ft.Rule(tool="ffprobe", argv_has=["-show_streams"], actions=[{"stdout_file": str(probe)}])
    ]
    if frames is not None:
        rules.insert(
            0,
            ft.Rule(
                tool="ffprobe", argv_has=["-show_frames"], actions=[{"stdout_file": str(frames)}]
            ),
        )
    fake.set_scenario(ft.Scenario(rules))


def recorded_file(tmp_path: Path, name: str, fake: ft.FakeTools) -> Path:
    """A placeholder file named like the recording; the fake ffprobe replays the recording."""
    frames = PROBES / f"{name}.frames.json"
    replay(fake, PROBES / f"{name}.json", frames if frames.exists() else None)
    path = tmp_path / "media" / str(INDEX[name]["file"])
    path.parent.mkdir(exist_ok=True)
    path.write_bytes(b"placeholder")
    return path


def without_path_row(output: str) -> str:
    """Drop the ``Path`` header row (it holds ``tmp_path`` and wraps differently with its
    length) and trailing spaces."""
    lines = [line.rstrip() for line in output.splitlines()]
    start = next(i for i, line in enumerate(lines) if line.startswith("  Path "))
    end = next(i for i, line in enumerate(lines) if line.startswith("  Container "))
    return "\n".join(lines[:start] + lines[end:]) + "\n"


@pytest.mark.needs_ffmpeg
@pytest.mark.parametrize(
    "fixture", ["season-e01", "multitrack", "hdr10", "vobsub", "text-subs", "chapters"]
)
def test_probe_fixture_lists_every_track(
    cache_env: Path, fixture_media: Media, fixture: str
) -> None:
    if fixture == "season-e01":
        path = fixture_media("season") / "Show.S01E01.Title.mkv"
    else:
        path = fixture_media(fixture)
    as_json = invoke("probe", "--json", str(path))
    assert as_json.exit_code == EXIT_OK, as_json.stderr
    assert as_json.stderr == ""
    source = MediaSource.model_validate_json(as_json.stdout)
    assert source.ref.path == path.absolute()

    human = invoke("probe", str(path))
    assert human.exit_code == EXIT_OK, human.stderr
    assert human.stderr == ""
    out = human.stdout
    assert out.startswith(f"{path.name}\n")
    assert "\x1b[" not in out  # not a terminal: no colour
    assert_every_track(out, source)
    assert f"Chapters   {len(source.chapters)}" in out
    if source.container.title:
        assert source.container.title in out


@pytest.mark.needs_ffmpeg
def test_probe_of_a_season_episode_shows_every_track(cache_env: Path, fixture_media: Media) -> None:
    path = fixture_media("season") / "Show.S01E01.Title.mkv"
    out = invoke("probe", str(path)).stdout
    assert "Show - S01E01" in out
    rows = table_rows(out)
    assert rows["1"][:6] == [
        "1",
        "jpn Japanese",
        "Japanese 5.1",
        "AC-3",
        "5.1(side), 6 ch",
        "48 kHz",
    ]
    assert rows["1"][6] == "192 kb/s (stream)"
    assert rows["1"][7] == "[Main]\ndefault"
    assert rows["2"][1:5] == ["eng English", "English Stereo", "AAC-LC", "stereo, 2 ch"]
    assert rows["2"][6].endswith("(estimated)")
    assert rows["2"][7] == "(Main?)"
    assert rows["3"][2:4] == ["Director's Commentary", "AAC-LC"]
    assert rows["3"][7] == "[Commentary]\ncommentary"
    assert rows["4"][1:7] == [
        "eng English",
        "English",
        "SRT",
        "text",
        "— (unknown)",
        "[Main]\ndefault",
    ]
    assert rows["5"][2] == "English SDH"
    assert rows["5"][6] == "[SDH]\nhearing impaired"
    assert rows["6"][2] == "Signs & Songs"
    assert rows["6"][6] == "[Forced] (Signs & Songs?)\nforced"
    assert '  #6  (Signs & Songs?)  title contains "Signs"' in out
    assert "  #3  [Commentary]  disposition comment" in out


@pytest.mark.needs_ffmpeg
def test_hdr10_video_line(cache_env: Path, fixture_media: Media) -> None:
    out = invoke("probe", str(fixture_media("hdr10"))).stdout
    assert f"  #0  HEVC Main 10 · 320{X}180 · 25 fps · HDR10 · BT.2020 PQ" in out
    assert "MaxCLL 1000 / MaxFALL 400" in out
    assert "mastering 0.0001-1000 cd/m²" in out


@pytest.mark.needs_ffmpeg
def test_text_subs_attachment(cache_env: Path, fixture_media: Media) -> None:
    out = invoke("probe", str(fixture_media("text-subs"))).stdout
    assert "Attachments (1)" in out
    assert re.search(r"  #\d+  ReframeBox\.ttf · application/x-truetype-font · [\d.]+ KiB", out)


@pytest.mark.needs_ffmpeg
def test_garbage_file_real_ffprobe(cache_env: Path) -> None:
    path = cache_env / "garbage.mkv"
    path.write_bytes(bytes(range(256)) * 16)
    line = assert_clean_failure(invoke("probe", str(path)), EXIT_PROBE_FAILED)
    assert "ffprobe could not read the file" in line


# Refresh with --snapshot-update.
@pytest.mark.parametrize("name", sorted(INDEX))
def test_recorded_probe_snapshot(
    fake_env: ft.FakeTools, tmp_path: Path, name: str, snapshot: SnapshotAssertion
) -> None:
    path = recorded_file(tmp_path, name, fake_env)
    result = invoke("probe", str(path), env={"COLUMNS": "120"})
    assert result.exit_code == EXIT_OK, result.stderr
    assert result.stderr == ""
    as_json = invoke("probe", "--json", str(path))
    source = MediaSource.model_validate_json(as_json.stdout)
    assert_every_track(invoke("probe", str(path)).stdout, source)
    assert without_path_row(result.stdout) == snapshot


def test_recorded_badges_and_bitrate_sources(fake_env: ft.FakeTools, tmp_path: Path) -> None:
    out = invoke("probe", str(recorded_file(tmp_path, "truehd-atmos", fake_env))).stdout
    rows = table_rows(out)
    codecs = {row[3] for row in rows.values()}
    assert {"TrueHD Atmos lossless", "AC-3"} <= codecs
    assert any(row[6].endswith("(stats tag)") for row in rows.values())
    assert "(Commentary?)" in out  # title only, no flag: outlined
    assert 'title contains "Commentary"' in out

    out = invoke("probe", str(recorded_file(tmp_path, "dts-hd-ma", fake_env))).stdout
    assert "DTS-HD MA lossless" in out
    assert "(Commentary?)" in out  # the structure heuristic

    out = invoke("probe", str(recorded_file(tmp_path, "pgs", fake_env))).stdout
    assert "PGS" in out
    assert "(stats tag)" in out
    assert f"bitmap 1920{X}1080" in out

    out = invoke("probe", str(recorded_file(tmp_path, "dv-p8", fake_env))).stdout
    assert "Dolby Vision 8.1" in out


def test_a_path_windows_refuses_is_named_as_too_long(
    fake_env: ft.FakeTools, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(longpath, "long_paths_enabled", lambda: False)
    path = tmp_path / ("x" * 250) / "movie.mkv"
    line = assert_clean_failure(invoke("probe", str(path)), EXIT_NOT_FOUND)
    assert "Windows refuses this path" in line
    assert "does not exist" not in line


def test_missing_file(fake_env: ft.FakeTools, tmp_path: Path) -> None:
    line = assert_clean_failure(invoke("probe", str(tmp_path / "nope.mkv")), EXIT_NOT_FOUND)
    assert line == f"error: {tmp_path / 'nope.mkv'}: The file does not exist."
    json_result = invoke("probe", "--json", str(tmp_path / "nope.mkv"))
    assert_clean_failure(json_result, EXIT_NOT_FOUND)


def test_folder_is_not_a_file(fake_env: ft.FakeTools, tmp_path: Path) -> None:
    line = assert_clean_failure(invoke("probe", str(tmp_path)), EXIT_NOT_FOUND)
    assert "The path is not a file." in line


@pytest.mark.skipif(
    sys.platform == "win32" or getattr(os, "geteuid", lambda: 1)() == 0,
    reason="POSIX permissions (root can read anything)",
)
def test_unreadable_file(fake_env: ft.FakeTools, tmp_path: Path) -> None:
    """An unreadable file is the facade's one-line exit 3, not click's usage error (exit 2)."""
    path = tmp_path / "locked.mkv"
    path.write_bytes(b"\x1aE\xdf\xa3")
    path.chmod(0o000)
    try:
        line = assert_clean_failure(invoke("probe", str(path)), EXIT_NOT_FOUND)
        assert line.startswith(f"error: {path}: The file cannot be read.")
        assert_clean_failure(invoke("probe", "--json", str(path)), EXIT_NOT_FOUND)
    finally:
        path.chmod(0o644)
    # Reported before ffprobe reads the file (only discovery's version checks ran).
    assert all(call == ("-version",) for call in fake_env.calls("ffprobe"))


def test_garbage_file(fake_env: ft.FakeTools, tmp_path: Path) -> None:
    fake_env.set_scenario(
        ft.Scenario(
            [
                ft.Rule(
                    tool="ffprobe",
                    argv_has=["-show_streams"],
                    actions=[ft.stderr("garbage.mkv: Invalid data found when processing input\n")],
                    exit_code=1,
                )
            ]
        )
    )
    path = tmp_path / "garbage.mkv"
    path.write_bytes(b"\0" * 100)
    line = assert_clean_failure(invoke("probe", str(path)), EXIT_PROBE_FAILED)
    assert line == (
        f"error: {path}: ffprobe could not read the file (exit code 1). "
        "(garbage.mkv: Invalid data found when processing input)"
    )
    assert_clean_failure(invoke("probe", "--json", str(path)), EXIT_PROBE_FAILED)


def test_invalid_ffprobe_output(fake_env: ft.FakeTools, tmp_path: Path) -> None:
    fake_env.set_scenario(
        ft.Scenario([ft.Rule(tool="ffprobe", argv_has=["-show_streams"], actions=[ft.stdout("[")])])
    )
    path = tmp_path / "x.mkv"
    path.write_bytes(b"x")
    line = assert_clean_failure(invoke("probe", str(path)), EXIT_PROBE_FAILED)
    assert "not JSON" in line


def test_missing_ffprobe(fake_env: ft.FakeTools, tmp_path: Path) -> None:
    missing = tmp_path / "no" / "ffprobe"
    path = tmp_path / "x.mkv"
    path.write_bytes(b"x")
    result = invoke("probe", str(path), env={"REFRAME_FFPROBE": str(missing)})
    line = assert_clean_failure(result, EXIT_NO_FFPROBE)
    assert line.startswith(
        f"error: ffprobe is not usable (missing, set by REFRAME_FFPROBE: {missing}): "
    )
    assert f"REFRAME_FFPROBE={missing}: the file does not exist." in line
    # A missing file is still reported as such.
    result = invoke("probe", str(tmp_path / "nope.mkv"), env={"REFRAME_FFPROBE": str(missing)})
    assert_clean_failure(result, EXIT_NOT_FOUND)


def test_broken_ffprobe(fake_env: ft.FakeTools, tmp_path: Path) -> None:
    fake_env.set_scenario(
        ft.Scenario(
            [
                ft.Rule(
                    tool="ffprobe",
                    argv_has=["-version"],
                    actions=[ft.stderr("error while loading shared libraries\n")],
                    exit_code=127,
                )
            ]
        )
    )
    path = tmp_path / "x.mkv"
    path.write_bytes(b"x")
    line = assert_clean_failure(invoke("probe", str(path)), EXIT_NO_FFPROBE)
    assert "ffprobe is not usable (broken, set by REFRAME_FFPROBE" in line
    assert "error while loading shared libraries" in line


def test_too_old_ffprobe(fake_env: ft.FakeTools, tmp_path: Path) -> None:
    fake_env.set_scenario(
        ft.Scenario([ft.Rule(tool="ffprobe", argv_has=["-version"], actions=[ft.version("6.1.1")])])
    )
    path = tmp_path / "x.mkv"
    path.write_bytes(b"x")
    line = assert_clean_failure(invoke("probe", str(path)), EXIT_NO_FFPROBE)
    assert "(too_old, set by REFRAME_FFPROBE" in line
    assert "too old" in line


def test_usage_error_exit_code(fake_env: ft.FakeTools) -> None:
    result = invoke("probe")
    assert result.exit_code == EXIT_USAGE
    assert "Traceback" not in result.output


def test_error_message_when_a_found_ffprobe_cannot_start() -> None:
    info = ToolInfo(name="ffprobe", status=ToolStatus.FOUND, path=Path("/x/ffprobe"))
    info.origin = ToolOrigin.PATH
    error = ProbeError(
        Path("/m.mkv"),
        ProbeErrorKind.TOOL_FAILED,
        "ffprobe could not be started.",
        "PermissionError: [Errno 13]\nPermission denied",
    )
    assert error_message(error, info) == (
        f"error: ffprobe (found on PATH: {Path('/x/ffprobe')}) could not be started: "
        "PermissionError: [Errno 13] Permission denied"
    )


def test_origin_text() -> None:
    def info(**kw: object) -> ToolInfo:
        return ToolInfo.model_validate({"name": "ffprobe", "status": "missing", **kw})

    p = Path("/t/ffprobe")
    assert origin_text(info(origin="env", env_var="REFRAME_FFPROBE", path=p)) == (
        f"set by REFRAME_FFPROBE: {p}"
    )
    assert origin_text(info(origin="settings", path=p, next_to_ffmpeg=True)) == (
        f"set in Settings > Tools, next to ffmpeg: {p}"
    )
    assert origin_text(info(origin="bundled")) == "bundled build"
    assert origin_text(info(origin="path", path=p)) == f"found on PATH: {p}"
    assert origin_text(info()) == "not found anywhere"
    no_reason = info()
    error = ProbeError(Path("/m.mkv"), ProbeErrorKind.TOOL_FAILED, "x")
    assert error_message(error, no_reason) == (
        "error: ffprobe is not usable (missing, not found anywhere): no reason given"
    )


def test_json_is_only_the_model(fake_env: ft.FakeTools, tmp_path: Path) -> None:
    path = recorded_file(tmp_path, "ass-fonts", fake_env)
    result = invoke("probe", "--json", str(path))
    assert result.exit_code == EXIT_OK
    assert result.stderr == ""
    assert result.stdout.startswith("{\n")
    assert result.stdout.endswith("}\n")
    source = MediaSource.model_validate_json(result.stdout)
    assert result.stdout == source.model_dump_json(indent=2) + "\n"
    assert len(source.attachments) == 2


def test_no_colour_when_piped_or_no_color(fake_env: ft.FakeTools, tmp_path: Path) -> None:
    path = recorded_file(tmp_path, "truehd-atmos", fake_env)
    assert "\x1b[" not in invoke("probe", str(path)).stdout
    forced = invoke("probe", str(path), env={"FORCE_COLOR": "1"}).stdout
    assert COLOUR_SGR.search(forced), "FORCE_COLOR should give colour"
    no_color = invoke("probe", str(path), env={"FORCE_COLOR": "1", "NO_COLOR": "1"}).stdout
    assert not COLOUR_SGR.search(no_color)


def test_make_console_width(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli, "_isatty", lambda fd: False)
    monkeypatch.delenv("COLUMNS", raising=False)
    assert make_console().width == cli.DEFAULT_PIPE_WIDTH
    monkeypatch.setenv("COLUMNS", "90")
    assert make_console().width == 90


@pytest.fixture
def unicode_recording(tmp_path: Path) -> Path:
    """The truehd-atmos recording with a Japanese commentary title (not in cp1252)."""
    data = json.loads((PROBES / "truehd-atmos.json").read_text(encoding="utf-8"))
    for stream in data["streams"]:
        if stream.get("tags", {}).get("title") == "Director's Commentary":
            stream["tags"]["title"] = "Kommentár コメンタリー"
    path = tmp_path / "unicode.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def run_subprocess(
    fake: ft.FakeTools, tmp_path: Path, *args: str, encoding: str | None
) -> subprocess.CompletedProcess[bytes]:
    env = fake.env()
    for var in ENV_VARS.values():
        env.pop(var, None)
    env.update(
        REFRAME_FFMPEG=str(fake.ffmpeg),
        REFRAME_FFPROBE=str(fake.ffprobe),
        REFRAME_CACHE_DIR=str(tmp_path / "cache-sub"),
        REFRAME_CONFIG_DIR=str(tmp_path / "config-sub"),
        COLUMNS="120",
    )
    env.pop("PYTHONUTF8", None)
    env.pop("PYTHONIOENCODING", None)
    if encoding is not None:
        env["PYTHONIOENCODING"] = encoding
    return subprocess.run(
        [sys.executable, "-m", "reframe.cli", *args],
        capture_output=True,
        env=env,
        timeout=60,
        check=False,
    )


def test_a_pipe_gets_utf8_when_no_encoding_is_set(
    fake_env: ft.FakeTools, tmp_path: Path, unicode_recording: Path
) -> None:
    replay(fake_env, unicode_recording)
    path = tmp_path / "Film ő 日本 🎬.mkv"
    path.write_bytes(b"x")
    result = run_subprocess(fake_env, tmp_path, "probe", str(path), encoding=None)
    assert result.returncode == 0, result.stderr.decode("utf-8", "replace")
    assert "Film ő 日本 🎬.mkv" in result.stdout.decode("utf-8")
    missing = run_subprocess(
        fake_env, tmp_path, "probe", str(tmp_path / "ő 日本.mkv"), encoding=None
    )
    assert "ő 日本.mkv" in missing.stderr.decode("utf-8")


@pytest.mark.parametrize(
    ("platform", "environ", "expected"),
    [
        ("win32", {}, "utf-8"),
        ("win32", {"PYTHONIOENCODING": "cp1252"}, "cp1252"),
        ("linux", {}, "cp1252"),
    ],
)
def test_only_a_windows_stream_without_a_chosen_encoding_becomes_utf8(
    platform: str, environ: dict[str, str], expected: str
) -> None:
    stream = io.TextIOWrapper(io.BytesIO(), encoding="cp1252")
    cli._configure_stream(stream, platform=platform, environ=environ)
    assert (stream.encoding, stream.errors) == (expected, "replace")


def test_non_utf8_stdout_does_not_crash(
    fake_env: ft.FakeTools, tmp_path: Path, unicode_recording: Path
) -> None:
    replay(fake_env, unicode_recording)
    path = tmp_path / "movie.mkv"
    path.write_bytes(b"x")
    result = run_subprocess(fake_env, tmp_path, "probe", str(path), encoding="cp1252")
    assert result.returncode == 0, result.stderr.decode("utf-8", "replace")
    out = result.stdout.decode("cp1252")
    assert 'title contains "Kommentár"' in out
    assert "??????" in out  # what cp1252 cannot encode is replaced
    assert "TrueHD Atmos" in out
    assert f"· 1920{X}1080 ·" in out  # the middle dot and the multiplication sign are in cp1252
    assert "+-" in out  # ASCII table borders
    assert "Traceback" not in result.stderr.decode("cp1252", "replace")

    as_json = run_subprocess(fake_env, tmp_path, "probe", "--json", str(path), encoding="cp1252")
    assert as_json.returncode == 0
    source = MediaSource.model_validate_json(as_json.stdout.decode("ascii"))
    assert "Kommentár コメンタリー" in [a.title for a in source.audio]


def test_write_json_escapes_for_a_legacy_stdout(monkeypatch: pytest.MonkeyPatch) -> None:
    source = MediaSource(ref=SourceRef(path=Path("/m/コ.mkv")))
    buffer = io.BytesIO()
    stream = io.TextIOWrapper(buffer, encoding="cp1252")
    monkeypatch.setattr(sys, "stdout", stream)
    cli._write_json(source)
    text = buffer.getvalue().decode("ascii")
    assert "\\u30b3" in text
    assert MediaSource.model_validate_json(text) == source


def test_main_runs_the_app(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(sys, "argv", ["reframe", "version"])
    with pytest.raises(SystemExit) as exit_info:
        cli.main()
    assert exit_info.value.code == 0
    assert capsys.readouterr().out.strip() == __version__


def test_number_formats() -> None:
    assert fmt_bps(2_104_000) == "2 104 kb/s"
    assert fmt_bps(192_000) == "192 kb/s"
    assert fmt_bps(1_500) == "1.5 kb/s"
    assert fmt_bps(2_000) == "2 kb/s"
    assert fmt_bitrate(BitrateInfo(value=2_104_000, source=BitrateSource.STATS_TAG)) == (
        "2 104 kb/s (stats tag)"
    )
    assert fmt_bitrate(BitrateInfo()) == "— (unknown)"
    assert fmt_duration(5025.5) == "1:23:45.500"
    assert fmt_duration(None) == "—"
    assert fmt_size(None) == "—"
    assert fmt_size(512) == "512 bytes"
    assert fmt_size(378_781) == "369.9 KiB (378 781 bytes)"
    assert fmt_size(5 * 2**30) == "5.0 GiB (5 368 709 120 bytes)"
    assert fmt_size(3 * 2**50).startswith("3072.0 TiB")
    assert fmt_sample(44_100, 24) == "44.1 kHz / 24-bit"
    assert fmt_sample(None, None) == "—"
    assert fmt_language(None) == "—"
    assert fmt_language("hun") == "hun Hungarian"
    assert fmt_language("xx-invalid-1") == "xx-invalid-1 (unknown code)"


def test_video_formats() -> None:
    video = VideoStream(
        index=0,
        width=3840,
        height=2160,
        display_codec="HEVC Main 10",
        avg_frame_rate=Rational(num=24000, den=1001),
        color=ColorInfo(primaries="bt2020", transfer="smpte2084"),
        hdr=HdrInfo(formats=[HdrFormat.HDR10, HdrFormat.HDR10_PLUS]),
    )
    assert (
        video_line(video)
        == f"HEVC Main 10 · 3840{X}2160 · 23.976 fps · HDR10 + HDR10+ · BT.2020 PQ"
    )
    assert fmt_hdr(None) == "SDR"
    dv = HdrInfo(
        formats=[HdrFormat.DOLBY_VISION, HdrFormat.HDR10],
        dolby_vision=DolbyVisionInfo(profile=5),
    )
    assert fmt_hdr(dv) == "Dolby Vision 5 + HDR10"
    assert fmt_color(ColorInfo()) is None
    assert fmt_color(ColorInfo(primaries="bt709", transfer="bt709")) == "BT.709"
    assert fmt_color(ColorInfo(primaries="bt2020", transfer="arib-std-b67")) == "BT.2020 HLG"
    assert fmt_color(ColorInfo(primaries="weird", transfer="odd")) == "weird odd"
    vfr = VideoStream(index=0, width=10, height=10, vfr=True)
    assert video_line(vfr) == f"unknown codec · 10{X}10 · VFR · SDR"
    phone = VideoStream(
        index=0,
        width=10,
        height=10,
        codec="h264",
        vfr=True,
        frame_rate=Rational(num=120),
        avg_frame_rate=Rational(num=38),
        field_order=FieldOrder.TOP_FIRST,
    )
    assert video_line(phone) == f"h264 · 10{X}10 · 38 fps average (VFR) · SDR"
    assert video_details(phone).startswith("interlaced TFF · base rate 120 fps · ")
    mkv = VideoStream(index=0, width=10, height=10, vfr=True, frame_rate=Rational(num=120))
    assert f"10{X}10 · VFR (base 120 fps) · SDR" in video_line(mkv)
    assert video_details(mkv) == "bitrate — (unknown)"
    unknown = VideoStream(index=0, width=10, height=10, codec="foo", pix_fmt="gray")
    assert video_details(unknown) == "gray · bitrate — (unknown)"
    assert video_line(unknown) == f"foo · 10{X}10 · SDR"


def test_role_badges_and_events() -> None:
    flag = TrackRoleInfo(role=TrackRole.COMMENTARY, evidence=RoleEvidence.FLAG)
    title = TrackRoleInfo(role=TrackRole.DESCRIPTION, evidence=RoleEvidence.TITLE)
    guess = TrackRoleInfo(role=TrackRole.MUSIC, evidence=RoleEvidence.HEURISTIC)
    assert [role_badge(r) for r in (flag, title, guess)] == [
        "[Commentary]",
        "(Audio description?)",
        "(Music only?)",
    ]
    sub = SubtitleStream(index=3)
    assert fmt_events(sub) == "— (unknown)"
    sub.event_count = 3410
    assert fmt_events(sub) == "3 410"
    sub.event_count_source = "stats_tag"
    sub.forced_event_count = 12
    assert fmt_events(sub) == "3 410 (stats tag, 12 forced)"


def test_render_edge_cases() -> None:
    source = MediaSource(
        ref=SourceRef(path=Path("/m/odd.m4a")),
        container=ContainerInfo(format_name="mov,mp4,m4a,3gp,3g2,mj2"),
        audio=[
            AudioStream(
                index=0,
                codec="pcm_s24le",
                display_codec="PCM",
                lossless=True,
                channels=2,
                start_time=1.358,
                delay=-0.042,
            )
        ],
        attachments=[Attachment(index=1)],
        cover_art=[AttachedPicture(index=2, codec="png")],
        data=[DataStream(index=3, codec_tag="tmcd", title="Timecode")],
        chapters=[Chapter(index=i, start=float(i), end=float(i + 1)) for i in range(55)],
        warnings=["MediaInfo could not read the file: boom"],
        probed_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    buffer = io.StringIO()
    render_source(source, make_console_for(buffer))
    out = buffer.getvalue()
    assert "Video (0)\n  —\n" in out
    assert "Subtitles (0)" in out
    assert "PCM lossless" in out
    assert "delay -42 ms" in out
    assert "2 ch" in out
    assert "#1  — · — · —" in out
    assert "#2  PNG" in out
    assert "#3  tmcd · Timecode" in out
    assert "Chapters (55)" in out
    assert "55  0:00:54.000" not in out
    assert "… and 5 more" in out
    assert "Warnings (1)\n  MediaInfo could not read the file: boom" in out
    assert "Bitrate    —" in out
    assert "Probed by" not in out


def make_console_for(buffer: io.StringIO) -> Console:
    return Console(file=buffer, width=100, color_system=None, highlight=False)


def test_long_values_wrap_with_their_indent() -> None:
    source = MediaSource(ref=SourceRef(path=Path("/" + "very-long-folder-name/" * 8 + "x.mkv")))
    buffer = io.StringIO()
    render_source(source, Console(file=buffer, width=60, color_system=None))
    lines = buffer.getvalue().splitlines()
    assert all(len(line) <= 60 for line in lines)
    start = next(i for i, line in enumerate(lines) if line.startswith("  Path "))
    assert lines[start + 1].startswith(" " * 13)
    assert all(line == line.rstrip() for line in lines)
