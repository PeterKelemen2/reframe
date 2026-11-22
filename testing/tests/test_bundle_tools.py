"""scripts/bundle-tools.py: the layout of what the desktop packages ship next to the sidecar. No
network: the manifest points at local archives through ``file:`` URLs."""

from __future__ import annotations

import hashlib
import io
import os
import tarfile
from pathlib import Path
from typing import Any

import pytest

from reframe.tools.fetch import FetchError
from reframe_testing.scripts import load_script

bt = load_script("bundle-tools.py")


def _tar(members: dict[str, bytes], mode: str = "w:bz2") -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode=mode) as tf:  # type: ignore[call-overload]
        for name, data in members.items():
            info = tarfile.TarInfo(name)
            info.mode = 0o644
            info.size = len(data)
            tf.addfile(info, io.BytesIO(data))
    return buf.getvalue()


class Setup:
    """A libva source archive in ``tmp/archives``, a manifest that pins it for Linux, the
    destination ``tmp/dest`` with its README."""

    def __init__(self, tmp: Path) -> None:
        self.archives = tmp / "archives"
        self.archives.mkdir()
        self.dest = tmp / "dest"
        self.dest.mkdir()
        (self.dest / "README.md").write_text("committed\n")
        self.manifest = tmp / "bundled-tools.toml"
        self.name = "libva-9.9.tar.bz2"
        self.set_source(b"MIT")

    def set_source(self, copying: bytes) -> None:
        self.data = _tar({"libva-9.9/COPYING": copying, "libva-9.9/meson.build": b"project()"})
        (self.archives / self.name).write_bytes(self.data)
        self.manifest.write_text(
            f"""schema_version = 1
[libraries.libva]
version = "9.9"
license = "MIT"
license_file = "COPYING"
source_repository = "https://example.invalid/libva"
[libraries.libva.platforms.linux-x64]
url = "{(self.archives / self.name).as_uri()}"
sha256 = "{hashlib.sha256(self.data).hexdigest()}"
size = {len(self.data)}
format = "tar.bz2"
root = "libva-9.9"
""",
            encoding="utf-8",
        )

    def bundle(self, platform: str = "linux-x64") -> Any:
        return bt.bundle(platform, self.dest, tools_manifest=self.manifest)

    def tree(self) -> list[str]:
        return sorted(
            p.relative_to(self.dest).as_posix()
            for p in self.dest.rglob("*")
            if p.name != bt.fetch.MARKER_NAME and not p.is_dir()
        )


@pytest.fixture
def setup(tmp_path: Path) -> Setup:
    return Setup(tmp_path)


@pytest.fixture(autouse=True)
def not_on_its_platform(monkeypatch: pytest.MonkeyPatch) -> None:
    """The fake libraries cannot load: lay the layout out as on another platform."""
    monkeypatch.setattr(bt.fetch, "host_platform", lambda: None)


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


@pytest.mark.usefixtures("fake_libva_build")
def test_the_linux_layout_is_libva_with_its_licence_and_no_ffmpeg(setup: Setup) -> None:
    setup.bundle()

    assert setup.tree() == [
        "README.md",
        "libva/LICENSE-libva.txt",
        "libva/libva-drm.so.2",
        "libva/libva-drm.so.2.2401.0",
        "libva/libva.so.2",
        "libva/libva.so.2.2401.0",
    ]
    libva = setup.dest / "libva"
    assert os.readlink(libva / "libva.so.2") == "libva.so.2.2401.0"
    assert os.readlink(libva / "libva-drm.so.2") == "libva-drm.so.2.2401.0"
    assert (libva / "LICENSE-libva.txt").read_bytes() == b"MIT"


@pytest.mark.usefixtures("fake_libva_build")
def test_the_windows_layout_holds_only_the_readme(setup: Setup) -> None:
    setup.bundle()
    setup.bundle("windows-x64")

    assert setup.tree() == ["README.md"]


@pytest.mark.parametrize("folder", ["ffmpeg", "mkvtoolnix", "mediainfo"])
def test_a_tool_folder_of_an_earlier_layout_does_not_stay_to_be_shipped(
    setup: Setup, folder: str
) -> None:
    """The bundler ships every folder of the layout: an FFmpeg laid out by an earlier layout
    would end up in the installers."""
    old = setup.dest / folder / "bin"
    old.mkdir(parents=True)
    (old / "tool.exe").write_bytes(b"MZ")
    (setup.dest / folder / bt.fetch.MARKER_NAME).write_text(
        f'{{"build": "{folder}", "layout": "bundled"}}'
    )
    (setup.dest / ".bundle-killed").mkdir()  # the work folder of a killed run

    setup.bundle("windows-x64")

    assert sorted(p.name for p in setup.dest.iterdir()) == ["README.md"]


@pytest.mark.parametrize("field", ["sha256", "size"])
def test_a_download_that_does_not_match_its_pin_is_never_extracted(
    setup: Setup, fake_libva_build: list[Path], field: str
) -> None:
    # The server now serves other bytes of the same size, or one byte more.
    other = bytes(len(setup.data)) if field == "sha256" else setup.data + b"x"
    (setup.archives / setup.name).write_bytes(other)

    with pytest.raises(FetchError, match=r"SHA-256|size"):
        setup.bundle()

    assert fake_libva_build == []
    assert setup.tree() == ["README.md"]
    assert not [p for p in setup.dest.iterdir() if p.name.startswith(".bundle-")]


def test_a_rerun_keeps_an_intact_layout_and_repairs_a_changed_one(
    setup: Setup, fake_libva_build: list[Path]
) -> None:
    setup.bundle()
    setup.bundle()
    assert len(fake_libva_build) == 1  # every file still matches its marker

    library = setup.dest / "libva" / "libva.so.2.2401.0"
    library.write_bytes(b"changed")
    setup.bundle()

    assert len(fake_libva_build) == 2
    assert library.read_bytes() == b"ELF libva"


def test_a_new_library_pin_builds_the_folder_again(
    setup: Setup, fake_libva_build: list[Path]
) -> None:
    setup.bundle()
    setup.set_source(b"new")
    setup.bundle()

    assert len(fake_libva_build) == 2
    assert (setup.dest / "libva" / "LICENSE-libva.txt").read_bytes() == b"new"


@pytest.mark.parametrize("foreign", ["notes.txt", "ffmpeg/ffmpeg", "libva/libva.so.2"])
def test_files_the_script_did_not_make_are_refused_and_kept(setup: Setup, foreign: str) -> None:
    path = setup.dest / foreign
    path.parent.mkdir(exist_ok=True)
    path.write_text("mine")
    (setup.archives / setup.name).unlink()  # it must fail before any download

    with pytest.raises(FetchError, match="did not make"):
        setup.bundle()

    assert path.read_text() == "mine"


def test_a_build_that_makes_no_library_lays_out_nothing(
    setup: Setup, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setitem(
        bt.LIBRARY_BUILDERS, "libva", lambda source, build: {"libva.so.2": tmp_path / "none"}
    )

    with pytest.raises(FetchError, match=r"made no libva\.so\.2"):
        setup.bundle()

    assert setup.tree() == ["README.md"]


def test_on_its_own_platform_the_libraries_must_load(
    setup: Setup, monkeypatch: pytest.MonkeyPatch, fake_libva_build: list[Path]
) -> None:
    monkeypatch.setattr(bt.fetch, "host_platform", lambda: "linux-x64")

    with pytest.raises(FetchError, match=r"libva\.so\.2 does not load"):
        setup.bundle()


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


def test_building_libva_without_its_tools_names_them(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PATH", str(tmp_path))
    with pytest.raises(FetchError, match="needs meson, ninja, pkg-config, cc"):
        bt.LIBRARY_BUILDERS["libva"](tmp_path, tmp_path / "build")


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
            "--tools-manifest",
            str(setup.manifest),
        ]
    )
    assert code == 1
    assert "notes.txt" in capsys.readouterr().err


def test_main_refuses_a_platform_that_no_desktop_package_ships(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as exit_info:
        bt.main(["--platform", "linux-arm64"])
    assert exit_info.value.code == 2
    assert "invalid choice: 'linux-arm64'" in capsys.readouterr().err


@pytest.mark.parametrize(
    ("change", "error"),
    [
        (("[libraries.libva]", "[libraries.libfoo]"), "no build is known"),
        (('root = "libva-9.9"\n', ""), "needs its top folder"),
        (('format = "tar.bz2"', 'format = "tar.xz"'), "format"),
        (("file://", "http://"), "https"),
        (('version = "9.9"\n', ""), "version"),
        (('license_file = "COPYING"', 'license_file = "/COPYING"'), "relative"),
        (("schema_version = 1", "schema_version = 2"), "schema_version"),
    ],
)
def test_bad_library_pins_are_refused(setup: Setup, change: tuple[str, str], error: str) -> None:
    text = setup.manifest.read_text(encoding="utf-8")
    assert change[0] in text
    setup.manifest.write_text(text.replace(change[0], change[1], 1), encoding="utf-8")
    with pytest.raises(FetchError, match=error):
        bt.libraries(setup.manifest, "linux-x64")


def test_the_real_libva_pin_is_for_linux_only() -> None:
    (libva,) = bt.libraries(bt.TOOLS_MANIFEST, "linux-x64")
    assert (libva.name, libva.format, libva.license_file) == ("libva", "tar.bz2", "COPYING")
    assert libva.url.startswith("https://")
    assert bt.libraries(bt.TOOLS_MANIFEST, "windows-x64") == []
