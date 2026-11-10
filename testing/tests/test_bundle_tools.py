"""Unit tests for scripts/bundle-tools.py. No network and no Docker: downloads and builds are
replaced with local files."""

from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import os
import sys
import zipfile
from pathlib import Path
from types import ModuleType

import pytest

from reframe.platform.libva import SYSTEM_LIBRARIES
from reframe.tools.discovery import LIBVA_FALLBACK_DIR

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "bundle-tools.py"


def _load_script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("bundle_tools", SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


bt = _load_script()


def test_the_shipped_libva_pin_gives_what_discovery_checks() -> None:
    libva = bt.load_libva()
    assert libva.libraries == SYSTEM_LIBRARIES
    assert libva.driver_dirs[0] == "/usr/lib/x86_64-linux-gnu/dri"
    assert libva.source.url.endswith(f"/{libva.version}/{libva.root}.tar.bz2")


def test_the_libva_goes_where_discovery_looks() -> None:
    assert bt.LIBVA_DIR == LIBVA_FALLBACK_DIR


def test_the_shipped_mkvtoolnix_pin() -> None:
    mkv = bt.load_mkvtoolnix("windows-x64")
    assert mkv.files["mkvtoolnix/mkvpropedit.exe"] == "mkvpropedit.exe"
    assert mkv.version in mkv.archive.url
    with pytest.raises(bt.BundleError, match=r"no \[platforms.linux-x64\]"):
        bt.load_mkvtoolnix("linux-x64")


def test_a_file_name_with_a_folder_is_refused(tmp_path: Path) -> None:
    manifest = tmp_path / "mkvtoolnix.toml"
    manifest.write_text(
        'schema_version = 1\nversion = "1"\n[platforms.windows-x64]\n'
        f'url = "https://x/a.zip"\nsha256 = "{"0" * 64}"\nsize = 1\n'
        'files = { "a/b.exe" = "../b.exe" }\n',
        encoding="utf-8",
    )
    with pytest.raises(bt.BundleError, match="plain file name"):
        bt.load_mkvtoolnix("windows-x64", manifest)


def test_the_libva_build_uses_the_pinned_driver_folders() -> None:
    libva = bt.load_libva()
    script = bt._libva_build_script(libva)
    assert f"-Ddriverdir={':'.join(libva.driver_dirs)}" in script
    assert "-Dwith_x11=no" in script
    assert f"tar xjf {libva.source.file_name}" in script


def _fake_install(tmp_path: Path, platform: str, monkeypatch: pytest.MonkeyPatch) -> Path:
    """An extracted archive as fetch-tools leaves it; returns the archive root."""
    build = bt.ft.load_manifest(bt.TOOLS_DIR / "ffmpeg.toml")["default"]
    pbuild = build.platforms[platform]
    base = tmp_path / "cache"
    root = Path(base, pbuild.root)
    exe = ".exe" if platform == "windows-x64" else ""
    for name in ("ffmpeg", "ffprobe", "ffplay"):
        path = root / "bin" / f"{name}{exe}"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(name.encode())
        path.chmod(0o755)
    (root / "include").mkdir()
    (root / "include" / "avcodec.h").write_text("", encoding="utf-8")
    (root / "LICENSE.txt").write_text("GPL", encoding="utf-8")
    if platform == "windows-x64":
        (root / "bin" / "avcodec-63.dll").write_bytes(b"dll")
    else:
        lib = root / "lib"
        lib.mkdir()
        (lib / "libavcodec.so.63.1.102").write_bytes(b"codec")
        (lib / "libavcodec.so.63").symlink_to("libavcodec.so.63.1.102")
        (lib / "libavcodec.so").symlink_to("libavcodec.so.63.1.102")
    monkeypatch.setattr(bt.ft, "install", lambda *_args, **_kw: base)
    return root


@pytest.mark.skipif(sys.platform == "win32", reason="symbolic links need extra rights on Windows")
def test_linux_ffmpeg_ships_each_library_once_under_its_soname(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _fake_install(tmp_path, "linux-x64", monkeypatch)
    out = tmp_path / "out"
    versions = bt.bundle_ffmpeg("linux-x64", out)
    files = sorted(p.relative_to(out).as_posix() for p in out.rglob("*") if p.is_file())
    assert files == ["ffmpeg/LICENSE.txt", "ffmpeg/bin/ffmpeg", "ffmpeg/bin/ffprobe",
                     "ffmpeg/lib/libavcodec.so.63"]  # fmt: skip
    library = out / "ffmpeg" / "lib" / "libavcodec.so.63"
    assert not library.is_symlink()
    assert library.read_bytes() == b"codec"
    assert os.access(out / "ffmpeg" / "bin" / "ffmpeg", os.X_OK) is (sys.platform != "win32")
    assert versions["ffmpeg"].startswith("n")


def test_windows_ffmpeg_ships_the_dlls_next_to_the_binaries(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _fake_install(tmp_path, "windows-x64", monkeypatch)
    out = tmp_path / "out"
    bt.bundle_ffmpeg("windows-x64", out)
    files = sorted(p.relative_to(out).as_posix() for p in out.rglob("*") if p.is_file())
    assert files == ["ffmpeg/LICENSE.txt", "ffmpeg/bin/avcodec-63.dll", "ffmpeg/bin/ffmpeg.exe",
                     "ffmpeg/bin/ffprobe.exe"]  # fmt: skip


def _zip(members: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, data in members.items():
            z.writestr(name, data)
    return buf.getvalue()


def test_mkvtoolnix_ships_only_the_listed_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    archive = tmp_path / "mkv.zip"
    archive.write_bytes(
        _zip(
            {
                "mkvtoolnix/mkvpropedit.exe": b"exe",
                "mkvtoolnix/mkvmerge.exe": b"other",
                "mkvtoolnix/doc/COPYING.txt": b"GPL",
            }
        )
    )
    monkeypatch.setattr(bt, "fetch", lambda *_a: archive)
    out = tmp_path / "out"
    bt.bundle_mkvtoolnix(bt.load_mkvtoolnix("windows-x64"), out)
    assert sorted(p.name for p in (out / "mkvtoolnix").iterdir()) == [
        "COPYING.txt",
        "mkvpropedit.exe",
    ]


def test_a_missing_archive_member_is_an_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    archive = tmp_path / "mkv.zip"
    archive.write_bytes(_zip({"mkvtoolnix/mkvmerge.exe": b"other"}))
    monkeypatch.setattr(bt, "fetch", lambda *_a: archive)
    with pytest.raises(bt.BundleError, match="has no mkvtoolnix/"):
        bt.bundle_mkvtoolnix(bt.load_mkvtoolnix("windows-x64"), tmp_path / "out")


def test_a_cached_download_is_checked_and_replaced_when_wrong(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data = b"archive"
    download = bt.Download("https://x/a.zip", hashlib.sha256(data).hexdigest(), len(data))
    (tmp_path / "a.zip").write_bytes(b"damaged")
    fetched: list[str] = []

    def fake_download(url: str, dest: Path, **_kw: object) -> None:
        fetched.append(url)
        dest.write_bytes(data)

    monkeypatch.setattr(bt.ft, "download", fake_download)
    assert bt.fetch(download, tmp_path).read_bytes() == data
    assert bt.fetch(download, tmp_path).read_bytes() == data
    assert fetched == ["https://x/a.zip"]


@pytest.mark.skipif(sys.platform == "win32", reason="symbolic links need extra rights on Windows")
def test_bundle_puts_the_libva_where_discovery_looks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _fake_install(tmp_path, "linux-x64", monkeypatch)

    def fake_libva(libva: object, ffmpeg_dir: Path, *, docker: bool) -> dict[str, str]:
        assert docker is True
        (ffmpeg_dir / LIBVA_FALLBACK_DIR).mkdir()
        (ffmpeg_dir / LIBVA_FALLBACK_DIR / "libva.so.2").write_bytes(b"")
        return {"libva": "x"}

    monkeypatch.setattr(bt, "bundle_libva", fake_libva)
    dest = tmp_path / "tools"
    versions = bt.bundle("linux-x64", dest)
    assert (dest / "ffmpeg" / LIBVA_FALLBACK_DIR / "libva.so.2").is_file()
    marker = json.loads((dest / bt.MARKER_NAME).read_text(encoding="utf-8"))
    assert marker == {"platform": "linux-x64", "versions": versions}
    assert set(versions) == {"ffmpeg", "libva"}
    bt.bundle("linux-x64", dest, libva_build="skip")  # its own folder is replaced
    assert not (dest / "ffmpeg" / LIBVA_FALLBACK_DIR).exists()


@pytest.mark.skipif(sys.platform == "win32", reason="symbolic links need extra rights on Windows")
def test_bundle_keeps_the_committed_readme(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _fake_install(tmp_path, "linux-x64", monkeypatch)
    dest = tmp_path / "tools"
    dest.mkdir()
    (dest / "README.md").write_text("keep", encoding="utf-8")
    bt.bundle("linux-x64", dest, libva_build="skip")
    assert (dest / "README.md").read_text(encoding="utf-8") == "keep"
    assert (dest / "ffmpeg" / "LICENSE.txt").is_file()


def test_bundle_refuses_a_folder_it_did_not_make(tmp_path: Path) -> None:
    dest = tmp_path / "tools"
    dest.mkdir()
    (dest / "mine.txt").write_text("", encoding="utf-8")
    with pytest.raises(bt.BundleError, match="not made by bundle-tools"):
        bt.bundle("linux-x64", dest)
    assert (dest / "mine.txt").is_file()
