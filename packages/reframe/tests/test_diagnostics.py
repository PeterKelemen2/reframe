"""The diagnostics report: every part, ``~`` paths, only the known settings, stable order."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import BaseModel

from reframe import __version__
from reframe.diagnostics import build_report, home_relative
from reframe.models import (
    AppSettings,
    CapabilitySnapshot,
    EncoderState,
    EncoderStatus,
    ToolInfo,
    ToolOrigin,
    ToolSet,
    ToolStatus,
)

HOME = "/home/ann"


def tools(ffmpeg_path: str = f"{HOME}/bin/ffmpeg") -> ToolSet:
    return ToolSet(
        ffmpeg=ToolInfo(
            name="ffmpeg",
            status=ToolStatus.FOUND,
            origin=ToolOrigin.SETTINGS,
            path=Path(ffmpeg_path),
            version="n9.0.2",
            release="9.0.2",
            build_flags=["--enable-gpl", f"--prefix={HOME}/ffmpeg_build"],
            library_versions={"libavutil": "61.1.102", "libavcodec": "63.1.102"},
        ),
        ffprobe=ToolInfo(
            name="ffprobe", status=ToolStatus.TOO_OLD, reason="ffprobe 4.4 is too old"
        ),
        mkvpropedit=ToolInfo(
            name="mkvpropedit", status=ToolStatus.FOUND, path=Path("/usr/bin/mkvpropedit")
        ),
        mediainfo=ToolInfo(name="mediainfo", status=ToolStatus.MISSING, reason="not found"),
    )


def snapshot(*, detecting: bool = False) -> CapabilitySnapshot:
    return CapabilitySnapshot(
        encoders={
            "libx265": EncoderStatus(id="libx265", state=EncoderState.AVAILABLE),
            "hevc_nvenc": EncoderStatus(
                id="hevc_nvenc",
                state=EncoderState.UNAVAILABLE,
                reason="NVIDIA driver not found",
                detail="Cannot load libcuda.so.1",
            ),
        },
        detecting=detecting,
    )


def report(tmp_path: Path, **overrides: object) -> str:
    arguments: dict[str, object] = {
        "tools": tools(),
        "encoders": snapshot(),
        "settings": AppSettings(),
        "logs": tmp_path / "logs",
        "server": {"Mode": "web", "Login": "token"},
        "home": HOME,
    }
    return build_report(**(arguments | overrides))  # type: ignore[arg-type]


def section(text: str, title: str) -> list[str]:
    body = text.split(f"\n{title}\n", 1)[1]
    return body.split("\n\n", 1)[0].splitlines()


def test_the_report_has_the_version_server_os_and_python_first(tmp_path: Path) -> None:
    head = report(tmp_path).split("\n\n")[1].splitlines()
    assert head[:3] == [f"Reframe: {__version__}", "Mode: web", "Login: token"]
    assert head[3].startswith("OS: ")
    assert head[4].startswith("Python: ")


def test_each_tool_has_status_origin_path_version_flags_libraries_and_reason(
    tmp_path: Path,
) -> None:
    lines = section(report(tmp_path), "Tools")
    assert lines[:8] == [
        "  ffmpeg: found",
        "    origin: settings",
        "    path: ~/bin/ffmpeg",
        "    version: n9.0.2",
        "    release: 9.0.2",
        "    build flags: --enable-gpl --prefix=~/ffmpeg_build",
        "    libraries: libavutil 61.1.102, libavcodec 63.1.102",
        "  ffprobe: too_old",
    ]
    assert "    reason: ffprobe 4.4 is too old" in lines
    assert lines[-2:] == ["  mediainfo: missing", "    reason: not found"]


def test_each_encoder_has_its_status_and_reason_in_a_stable_order(tmp_path: Path) -> None:
    lines = section(report(tmp_path), "Encoders")
    assert lines == [
        "  hevc_nvenc: unavailable: NVIDIA driver not found",
        "    detail: Cannot load libcuda.so.1",
        "  libx265: available",
    ]


def test_a_running_detection_is_said(tmp_path: Path) -> None:
    lines = section(report(tmp_path, encoders=snapshot(detecting=True)), "Encoders")
    assert lines[0] == "  detection running: the statuses may still change"


def test_the_settings_have_their_known_fields_only(tmp_path: Path) -> None:
    settings = AppSettings.model_validate(
        {
            "diagnostics": {"log_level": "debug", "upload_key": "s3cr3t-1"},
            "future_section": {"token": "s3cr3t-2"},
            "output": {"naming": {"output_folder": f"{HOME}/Videos", "later": "s3cr3t-3"}},
        }
    )
    text = report(tmp_path, settings=settings)
    lines = section(text, "Settings")
    assert "s3cr3t" not in text
    assert '  diagnostics.log_level = "debug"' in lines
    assert '  output.naming.output_folder = "~/Videos"' in lines
    assert "  schema_version = 1" in lines


def _fields(model: type[BaseModel], prefix: str = "") -> list[str]:
    names = []
    for name, field in model.model_fields.items():
        names.append(prefix + name)
        if isinstance(field.annotation, type) and issubclass(field.annotation, BaseModel):
            names += _fields(field.annotation, f"{prefix}{name}.")
    return names


def test_no_setting_is_a_secret() -> None:
    """The report writes every known setting: a secret setting must be left out of it first."""
    secret = ("password", "token", "secret", "key", "cookie", "credential")
    assert [name for name in _fields(AppSettings) if any(word in name for word in secret)] == []


def test_the_logs_part_lists_the_files_that_exist(tmp_path: Path) -> None:
    logs = tmp_path / "logs"
    logs.mkdir()
    (logs / "reframe.log").write_bytes(b"x" * 2048)
    (logs / "reframe.log.1").write_bytes(b"x" * 10)
    (logs / "sidecar.log").write_bytes(b"")
    (logs / "0b6c5f1a.log").write_bytes(b"job")
    (logs / "9f3e2d1c.log").write_bytes(b"job")
    lines = section(report(tmp_path, home=str(tmp_path)), "Logs")
    assert lines == [
        "  folder: ~/logs",
        "  reframe.log: 2.0 KiB",
        "  reframe.log.1: 10 B",
        "  sidecar.log: 0 B",
        "  job logs: 2",
    ]


def test_a_logs_folder_that_does_not_exist_is_said(tmp_path: Path) -> None:
    lines = section(report(tmp_path), "Logs")
    assert lines[1] == "  (the folder does not exist yet)"


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("/home/ann/Videos/a.mkv", "~/Videos/a.mkv"),
        ("path: /home/ann", "path: ~"),
        ("--prefix=/home/ann/build -I/home/ann/include", "--prefix=~/build -I~/include"),
        ('"/home/ann/x"', '"~/x"'),
        ("/home/anna/x", "/home/anna/x"),
        ("/srv/home/ann/x", "/srv/home/ann/x"),
        ("/HOME/ANN/x", "/HOME/ANN/x"),
    ],
)
def test_paths_under_the_home_folder_start_with_a_tilde(text: str, expected: str) -> None:
    assert home_relative(text, home=HOME, windows=False) == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (r"C:\Users\Zoé\Videos\a.mkv", r"~\Videos\a.mkv"),
        ("c:/users/ZOÉ/Videos", "~/Videos"),
        (r'"C:\\Users\\Zoé\\x"', r'"~\\x"'),
        (r"C:\Users\Zoé2\x", r"C:\Users\Zoé2\x"),
        (r"D:\Backup\C:\Users\Zoé", r"D:\Backup\C:\Users\Zoé"),
    ],
)
def test_windows_paths_under_userprofile_start_with_a_tilde(text: str, expected: str) -> None:
    assert home_relative(text, home="C:\\Users\\Zoé", windows=True) == expected


@pytest.mark.parametrize(("home", "windows"), [("/", False), ("", False), ("C:\\", True)])
def test_a_home_folder_at_the_root_changes_nothing(home: str, windows: bool) -> None:
    assert home_relative(r"/x C:\x", home=home, windows=windows) == r"/x C:\x"


def test_the_default_home_is_the_users(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    assert home_relative(str(tmp_path / "a")) == str(Path("~") / "a")
