"""scripts/bundle-tools.py: the layout of the bundled tools. No network: the manifests point at
local archives through ``file:`` URLs."""

from __future__ import annotations

import hashlib
import importlib.util
import io
import os
import stat
import sys
import tarfile
import zipfile
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from reframe.tools.fetch import FetchError

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "bundle-tools.py"
FF_ROOT = "ffmpeg-test-win64"
LINUX_ROOT = "ffmpeg-test-linux64"


def _load_script() -> ModuleType:
    # The script name has a hyphen, so it cannot be imported by name.
    spec = importlib.util.spec_from_file_location("bundle_tools", SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # dataclasses look the module up by name
    spec.loader.exec_module(module)
    return module


bt = _load_script()


def _zip(members: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, data in members.items():
            info = zipfile.ZipInfo(name)
            info.external_attr = (stat.S_IFREG | 0o755) << 16
            zf.writestr(info, data)
    return buf.getvalue()


def _tar_xz(members: dict[str, bytes], mode: str = "w:xz") -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode=mode) as tf:  # type: ignore[call-overload]
        for name, data in members.items():
            info = tarfile.TarInfo(name)
            info.mode = 0o755
            info.size = len(data)
            tf.addfile(info, io.BytesIO(data))
    return buf.getvalue()


def _fake_ffmpeg(tool: str, version: str) -> bytes:
    return (
        f"#!/bin/sh\necho '{tool} version {version} Copyright (c) the FFmpeg developers'\n".encode()
    )


class Setup:
    """Archives in ``tmp/archives``, manifests that pin them, the destination ``tmp/dest``
    with its README."""

    def __init__(self, tmp: Path) -> None:
        self.archives = tmp / "archives"
        self.archives.mkdir()
        self.dest = tmp / "dest"
        self.dest.mkdir()
        (self.dest / "README.md").write_text("committed\n")
        self.ffmpeg_manifest = tmp / "ffmpeg.toml"
        self.tools_manifest = tmp / "bundled-tools.toml"
        self.ffmpeg_version = "n9.0.2-test"
        self.files: dict[str, bytes] = {
            f"{FF_ROOT}.zip": _zip(
                {
                    f"{FF_ROOT}/bin/ffmpeg.exe": b"MZ ffmpeg",
                    f"{FF_ROOT}/bin/ffprobe.exe": b"MZ ffprobe",
                    f"{FF_ROOT}/bin/avcodec-63.dll": b"MZ dll",
                    f"{FF_ROOT}/LICENSE.txt": b"GPL-3",
                }
            ),
            f"{LINUX_ROOT}.tar.xz": _tar_xz(
                {
                    f"{LINUX_ROOT}/bin/ffmpeg": _fake_ffmpeg("ffmpeg", self.ffmpeg_version),
                    f"{LINUX_ROOT}/bin/ffprobe": _fake_ffmpeg("ffprobe", self.ffmpeg_version),
                    f"{LINUX_ROOT}/lib/libavcodec.so.63": b"ELF",
                    f"{LINUX_ROOT}/LICENSE.txt": b"GPL-3",
                }
            ),
            "MediaInfo_CLI_x64.zip": _zip(
                {
                    "MediaInfo/MediaInfo.exe": b"MZ mediainfo",
                    "MediaInfo/LICENSE": b"BSD-2",
                    "MediaInfo/doc/History.txt": b"history",
                    "MediaInfo/LIBCURL.DLL": b"MZ curl",
                }
            ),
        }
        self.mediainfo_files = '["MediaInfo.exe", "LICENSE"]'
        self.libraries = ""
        self.write()

    def add_libva(self, copying: bytes = b"MIT") -> None:
        """Pin a libva source for Linux (the build itself is the ``fake_libva_build``'s)."""
        name = "libva-9.9.tar.bz2"
        self.files[name] = _tar_xz(
            {"libva-9.9/COPYING": copying, "libva-9.9/meson.build": b"project('libva')"},
            mode="w:bz2",
        )
        self.libraries = f"""[libraries.libva]
version = "9.9"
license = "MIT"
license_file = "COPYING"
source_repository = "https://example.invalid/libva"
[libraries.libva.platforms.linux-x64]
url = "{self.url(name)}"
{self.pin(name)}format = "tar.bz2"
root = "libva-9.9"
"""
        self.write()

    def url(self, name: str) -> str:
        return (self.archives / name).as_uri()

    def pin(self, name: str) -> str:
        data = self.files[name]
        return f'sha256 = "{hashlib.sha256(data).hexdigest()}"\nsize = {len(data)}\n'

    def write(self) -> None:
        for name, data in self.files.items():
            (self.archives / name).write_bytes(data)
        lin, win = f"{LINUX_ROOT}.tar.xz", f"{FF_ROOT}.zip"
        self.ffmpeg_manifest.write_text(
            f"""schema_version = 1
[builds.default]
version = "{self.ffmpeg_version}"
release_version = "9.0.2"
release_tag = "test"
license = "GPL-3.0-or-later"
license_file = "LICENSE.txt"
source_repository = "https://example.invalid/ffmpeg"
source_commit = "{"0" * 40}"
[builds.default.platforms.linux-x64]
url = "{self.url(lin)}"
{self.pin(lin)}format = "tar.xz"
root = "{LINUX_ROOT}"
bin_dir = "bin"
ffmpeg = "bin/ffmpeg"
ffprobe = "bin/ffprobe"
[builds.default.platforms.windows-x64]
url = "{self.url(win)}"
{self.pin(win)}format = "zip"
root = "{FF_ROOT}"
bin_dir = "bin"
ffmpeg = "bin/ffmpeg.exe"
ffprobe = "bin/ffprobe.exe"
""",
            encoding="utf-8",
        )
        mi = "MediaInfo_CLI_x64.zip"
        self.tools_manifest.write_text(
            f"""schema_version = 1
[tools.mediainfo]
version = "26.10"
license = "BSD-2-Clause"
license_file = "LICENSE"
source_url = "https://example.invalid/mediainfo.tar.xz"
[tools.mediainfo.platforms.windows-x64]
url = "{self.url(mi)}"
{self.pin(mi)}format = "zip"
root = "MediaInfo"
binary = "MediaInfo.exe"
files = {self.mediainfo_files}
{self.libraries}""",
            encoding="utf-8",
        )

    def bundle(self, platform: str = "windows-x64") -> Any:
        return bt.bundle(
            platform,
            self.dest,
            ffmpeg_manifest=self.ffmpeg_manifest,
            tools_manifest=self.tools_manifest,
        )

    def tree(self) -> list[str]:
        return sorted(
            p.relative_to(self.dest).as_posix()
            for p in self.dest.rglob("*")
            if p.is_file() and p.name != ".fetch-tools.json"
        )


@pytest.fixture
def setup(tmp_path: Path) -> Setup:
    return Setup(tmp_path)


@pytest.fixture
def no_discovery(monkeypatch: pytest.MonkeyPatch) -> None:
    """The fake Windows binaries cannot run: lay the layout out as on another platform."""
    monkeypatch.setattr(bt.fetch, "host_platform", lambda: None)


@pytest.mark.usefixtures("no_discovery")
def test_windows_layout_has_each_tool_its_licence_and_nothing_else(setup: Setup) -> None:
    setup.bundle()
    assert setup.tree() == [
        "README.md",
        "ffmpeg/LICENSE.txt",
        "ffmpeg/bin/avcodec-63.dll",
        "ffmpeg/bin/ffmpeg.exe",
        "ffmpeg/bin/ffprobe.exe",
        "mediainfo/LICENSE",
        "mediainfo/MediaInfo.exe",
    ]
    assert (setup.dest / "mediainfo" / "MediaInfo.exe").read_bytes() == b"MZ mediainfo"


@pytest.mark.usefixtures("no_discovery")
def test_a_tool_folder_of_an_earlier_layout_does_not_stay_to_be_shipped(setup: Setup) -> None:
    """The bundler ships every folder of the layout: an mkvpropedit.exe laid out before
    MKVToolNix stopped being bundled would end up in the installers."""
    old = setup.dest / "mkvtoolnix"
    old.mkdir()
    (old / "mkvpropedit.exe").write_bytes(b"MZ mkvpropedit")
    (old / bt.fetch.MARKER_NAME).write_text('{"build": "mkvtoolnix", "layout": "bundled"}')
    setup.bundle()
    assert sorted(p.name for p in setup.dest.iterdir()) == ["README.md", "ffmpeg", "mediainfo"]


@pytest.mark.usefixtures("no_discovery")
@pytest.mark.parametrize("field", ["sha256", "size"])
def test_a_download_that_does_not_match_its_pin_is_never_extracted(
    setup: Setup, field: str
) -> None:
    name = "MediaInfo_CLI_x64.zip"
    pinned = setup.files[name]
    setup.write()
    # The server now serves other bytes of the same size, or one byte more.
    other = bytes(len(pinned)) if field == "sha256" else pinned + b"x"
    (setup.archives / name).write_bytes(other)
    with pytest.raises(FetchError, match=r"SHA-256|size"):
        setup.bundle()
    assert not (setup.dest / "mediainfo").exists()
    assert not [p for p in setup.dest.iterdir() if p.name.startswith(".bundle-")]


@pytest.mark.usefixtures("no_discovery")
def test_a_rerun_keeps_an_intact_layout_and_repairs_a_changed_one(
    setup: Setup, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(bt.fetch, "_sleep", lambda seconds, cancel: None)
    setup.bundle()
    archive = setup.archives / "MediaInfo_CLI_x64.zip"
    archive.unlink()
    setup.bundle()  # nothing to download: every folder still matches its marker
    exe = setup.dest / "mediainfo" / "MediaInfo.exe"
    exe.write_bytes(b"changed")
    with pytest.raises(FetchError, match="download failed"):
        setup.bundle()
    archive.write_bytes(setup.files["MediaInfo_CLI_x64.zip"])
    setup.bundle()
    assert exe.read_bytes() == b"MZ mediainfo"


@pytest.mark.usefixtures("no_discovery")
def test_a_changed_list_of_kept_files_is_laid_out_again(setup: Setup) -> None:
    setup.bundle()
    setup.mediainfo_files = '["MediaInfo.exe", "LICENSE", "doc/History.txt"]'
    setup.write()
    setup.bundle()
    assert (setup.dest / "mediainfo" / "doc" / "History.txt").read_bytes() == b"history"


@pytest.mark.usefixtures("no_discovery")
def test_a_linux_layout_after_a_windows_one_drops_the_windows_tools(setup: Setup) -> None:
    setup.bundle()
    (setup.dest / ".bundle-killed").mkdir()  # the work folder of a killed run
    setup.bundle("linux-x64")
    assert setup.tree() == [
        "README.md",
        "ffmpeg/LICENSE.txt",
        "ffmpeg/bin/ffmpeg",
        "ffmpeg/bin/ffprobe",
        "ffmpeg/lib/libavcodec.so.63",
    ]
    assert sorted(p.name for p in setup.dest.iterdir()) == ["README.md", "ffmpeg"]


@pytest.mark.usefixtures("no_discovery")
@pytest.mark.parametrize(
    "foreign", ["notes.txt", "ffmpeg/ffmpeg.exe", "other/x", "mkvtoolnix/mkvpropedit.exe"]
)
def test_files_the_script_did_not_make_are_refused_and_kept(setup: Setup, foreign: str) -> None:
    path = setup.dest / foreign
    path.parent.mkdir(exist_ok=True)
    path.write_text("mine")
    (setup.archives / f"{FF_ROOT}.zip").unlink()  # it must fail before any download
    with pytest.raises(FetchError, match="did not make"):
        setup.bundle()
    assert path.read_text() == "mine"


@pytest.mark.usefixtures("no_discovery")
def test_an_archive_without_a_pinned_file_lays_out_nothing(setup: Setup) -> None:
    setup.mediainfo_files = '["MediaInfo.exe", "LICENSE", "MediaInfo.dll"]'
    setup.write()
    with pytest.raises(FetchError, match=r"has no MediaInfo\.dll"):
        setup.bundle()
    assert not (setup.dest / "mediainfo").exists()


def test_the_bundled_libva_searches_the_cores_driver_folders(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from reframe.tools import discovery

    calls: list[list[str]] = []
    monkeypatch.setattr(bt.shutil, "which", lambda tool: f"/usr/bin/{tool}")
    monkeypatch.setattr(bt, "_run", calls.append)

    bt.LIBRARY_BUILDERS["libva"](tmp_path, tmp_path / "build")

    folders = ":".join(d.as_posix() for d in discovery.LIBVA_DRIVER_DIRS)
    assert folders == (
        "/usr/lib/x86_64-linux-gnu/dri:/usr/lib64/dri-nonfree:/usr/lib64/dri-freeworld"
        ":/usr/lib64/dri:/usr/lib/dri"
    )
    assert f"-Ddriverdir={folders}" in calls[0]


@pytest.mark.parametrize(
    ("change", "error"),
    [
        (('files = ["MediaInfo.exe", "LICENSE"]', 'files = ["MediaInfo.exe"]'),
         "does not keep LICENSE"),
        (('root = "MediaInfo"\n', ""), None),
        (('format = "zip"\nroot', 'format = "tar.xz"\nroot'), "format"),
        (("file://", "http://"), "https"),
        (('binary = "MediaInfo.exe"', 'binary = "../MediaInfo.exe"'), "relative"),
        (("[tools.mediainfo]\n", "[tools.mkvtoolnix]\n"), "unknown tool"),
        (('version = "26.10"\n', ""), "version"),
    ],
)  # fmt: skip
def test_bad_tool_pins_are_refused(
    setup: Setup, change: tuple[str, str], error: str | None
) -> None:
    text = setup.tools_manifest.read_text(encoding="utf-8")
    assert change[0] in text
    setup.tools_manifest.write_text(text.replace(change[0], change[1], 1), encoding="utf-8")
    if error is None:  # a zip without its top folder is fine to parse
        assert [a.root for a in bt.tool_archives(setup.tools_manifest, "windows-x64")] == [None]
        return
    with pytest.raises(FetchError, match=error):
        bt.tool_archives(setup.tools_manifest, "windows-x64")


def test_a_tar_xz_tool_archive_needs_its_top_folder(setup: Setup) -> None:
    text = setup.tools_manifest.read_text(encoding="utf-8")
    text = (
        text.replace("MediaInfo_CLI_x64.zip", "mi.tar.xz")
        .replace('format = "zip"', 'format = "tar.xz"')
        .replace('root = "MediaInfo"\n', "")
    )
    setup.tools_manifest.write_text(text, encoding="utf-8")
    with pytest.raises(FetchError, match="needs its top folder"):
        bt.tool_archives(setup.tools_manifest, "windows-x64")


def test_the_real_pins_keep_each_binary_and_licence() -> None:
    windows = bt.tool_archives(bt.TOOLS_MANIFEST, "windows-x64")
    # MKVToolNix's Windows build links OpenSSL (Apache-2.0) into GPL-2.0-only code.
    assert {a.folder: a.required[0] for a in windows} == {"mediainfo": "MediaInfo.exe"}
    for archive in windows:
        assert archive.files is not None
        assert set(archive.required) <= set(archive.files)
        assert archive.url.startswith("https://")
    assert bt.tool_archives(bt.TOOLS_MANIFEST, "linux-x64") == []
    for platform in ("linux-x64", "windows-x64"):
        ffmpeg = bt.ffmpeg_archive(bt.FFMPEG_MANIFEST, platform)
        assert ffmpeg.files is None
        assert len(ffmpeg.required) == 3


@pytest.mark.skipif(sys.platform == "win32", reason="the fake binaries are shell scripts")
def test_on_its_own_platform_discovery_must_find_the_pinned_version(
    setup: Setup, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(bt.fetch, "host_platform", lambda: "linux-x64")
    monkeypatch.setenv("REFRAME_FFMPEG", "/nonexistent/ffmpeg")  # an override is ignored
    setup.bundle("linux-x64")
    setup.ffmpeg_version = "n9.0.3-test"
    setup.files[f"{LINUX_ROOT}.tar.xz"] = _tar_xz(
        {
            f"{LINUX_ROOT}/bin/ffmpeg": _fake_ffmpeg("ffmpeg", "n9.0.2-test"),
            f"{LINUX_ROOT}/bin/ffprobe": _fake_ffmpeg("ffprobe", "n9.0.2-test"),
            f"{LINUX_ROOT}/LICENSE.txt": b"GPL-3",
        }
    )
    setup.write()
    with pytest.raises(FetchError, match=r"expected 'n9\.0\.3-test'"):
        setup.bundle("linux-x64")


def test_main_reports_an_error_with_exit_code_1(
    setup: Setup, capsys: pytest.CaptureFixture[str]
) -> None:
    (setup.dest / "notes.txt").write_text("mine")
    code = bt.main(
        [
            "--platform",
            "windows-x64",
            "--dest",
            str(setup.dest),
            "--ffmpeg-manifest",
            str(setup.ffmpeg_manifest),
            "--tools-manifest",
            str(setup.tools_manifest),
        ]
    )
    assert code == 1
    assert "notes.txt" in capsys.readouterr().err


def test_main_refuses_the_arm64_ffmpeg_pin_that_no_desktop_package_ships(
    capsys: pytest.CaptureFixture[str],
) -> None:
    # It has no libva pin: a layout would lack the VAAPI library the x64 layouts have.
    with pytest.raises(SystemExit) as exit_info:
        bt.main(["--platform", "linux-arm64"])
    assert exit_info.value.code == 2
    assert "invalid choice: 'linux-arm64'" in capsys.readouterr().err


@pytest.fixture
def fake_libva_build(monkeypatch: pytest.MonkeyPatch) -> list[Path]:
    """Replaces the meson build of libva: writes two libraries named as libva's are; the
    source folders it was called with."""
    calls: list[Path] = []

    def build(source: Path, build_dir: Path) -> dict[str, Path]:
        calls.append(source)
        assert (source / "meson.build").is_file()
        va = build_dir / "va"
        va.mkdir(parents=True)
        (va / "libva.so.2.2401.0").write_bytes(b"ELF libva")
        (va / "libva-drm.so.2.2401.0").write_bytes(b"ELF libva-drm")
        return {
            "libva.so.2": va / "libva.so.2.2401.0",
            "libva-drm.so.2": va / "libva-drm.so.2.2401.0",
        }

    monkeypatch.setitem(bt.LIBRARY_BUILDERS, "libva", build)
    return calls


@pytest.mark.usefixtures("no_discovery")
def test_the_linux_layout_ships_the_built_libva_next_to_ffmpeg(
    setup: Setup, fake_libva_build: list[Path]
) -> None:
    setup.add_libva(copying=b"MIT licence of libva")
    setup.bundle("linux-x64")
    lib = setup.dest / "ffmpeg" / "lib"
    assert os.readlink(lib / "libva.so.2") == "libva.so.2.2401.0"
    assert os.readlink(lib / "libva-drm.so.2") == "libva-drm.so.2.2401.0"
    assert (lib / "libva.so.2").read_bytes() == b"ELF libva"
    assert (setup.dest / "ffmpeg" / "LICENSE-libva.txt").read_bytes() == b"MIT licence of libva"
    assert len(fake_libva_build) == 1
    setup.bundle("windows-x64")  # the library is Linux only
    assert not (setup.dest / "ffmpeg" / "LICENSE-libva.txt").exists()
    assert len(fake_libva_build) == 1


@pytest.mark.usefixtures("no_discovery")
def test_a_new_library_pin_builds_the_ffmpeg_folder_again(
    setup: Setup, fake_libva_build: list[Path]
) -> None:
    setup.add_libva(copying=b"old")
    setup.bundle("linux-x64")
    setup.bundle("linux-x64")
    assert len(fake_libva_build) == 1  # a rerun keeps it
    setup.add_libva(copying=b"new")
    setup.bundle("linux-x64")
    assert len(fake_libva_build) == 2
    assert (setup.dest / "ffmpeg" / "LICENSE-libva.txt").read_bytes() == b"new"


def test_building_libva_without_its_tools_names_them(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PATH", str(tmp_path))
    with pytest.raises(FetchError, match="needs meson, ninja, pkg-config, cc"):
        bt.LIBRARY_BUILDERS["libva"](tmp_path, tmp_path / "build")


@pytest.mark.parametrize(
    ("change", "error"),
    [
        (("[libraries.libva]", "[libraries.libfoo]"), "no build is known"),
        (('root = "libva-9.9"\n', ""), "needs its top folder"),
        (('license_file = "COPYING"', 'license_file = "/COPYING"'), "relative"),
    ],
)
def test_bad_library_pins_are_refused(setup: Setup, change: tuple[str, str], error: str) -> None:
    setup.add_libva()
    text = setup.tools_manifest.read_text(encoding="utf-8")
    assert change[0] in text
    setup.tools_manifest.write_text(text.replace(change[0], change[1], 1), encoding="utf-8")
    with pytest.raises(FetchError, match=error):
        bt.libraries(setup.tools_manifest, "linux-x64")


def test_the_real_libva_pin_is_for_linux_only() -> None:
    (libva,) = bt.libraries(bt.TOOLS_MANIFEST, "linux-x64")
    assert (libva.name, libva.format, libva.license_file) == ("libva", "tar.bz2", "COPYING")
    assert libva.url.startswith("https://")
    assert bt.libraries(bt.TOOLS_MANIFEST, "windows-x64") == []
