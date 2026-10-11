"""Unit tests for scripts/fetch-tools.py (Q-1.2): manifest, checksums, safe extraction.

No network: downloads are replaced by a function that copies a local archive.
"""

from __future__ import annotations

import copy
import hashlib
import importlib.util
import io
import os
import stat
import sys
import tarfile
import tomllib
import urllib.error
import urllib.request
import zipfile
from collections.abc import Callable
from email.message import Message
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "fetch-tools.py"
MANIFEST = REPO_ROOT / "tools" / "ffmpeg.toml"
ROOT = "ffmpeg-test-linux64"


def _load_script() -> ModuleType:
    # The script name has a hyphen, so it cannot be imported by name.
    spec = importlib.util.spec_from_file_location("fetch_tools", SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # dataclasses look the module up by name
    spec.loader.exec_module(module)
    return module


ft = _load_script()


def _manifest_data() -> dict[str, Any]:
    with MANIFEST.open("rb") as f:
        return tomllib.load(f)


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _tar_xz(members: list[tuple[tarfile.TarInfo, bytes | None]]) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:xz") as tf:
        for info, data in members:
            if data is not None:
                info.size = len(data)
                tf.addfile(info, io.BytesIO(data))
            else:
                tf.addfile(info)
    return buf.getvalue()


def _file(name: str, mode: int = 0o644) -> tarfile.TarInfo:
    info = tarfile.TarInfo(name)
    info.mode = mode
    return info


def _symlink(name: str, target: str) -> tarfile.TarInfo:
    info = tarfile.TarInfo(name)
    info.type = tarfile.SYMTYPE
    info.linkname = target
    return info


def _zip(members: list[tuple[str, bytes, int]]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, data, mode in members:
            info = zipfile.ZipInfo(name)
            info.external_attr = (stat.S_IFREG | mode) << 16
            zf.writestr(info, data)
    return buf.getvalue()


def _good_tar() -> bytes:
    return _tar_xz(
        [
            (_file(f"{ROOT}/bin/ffmpeg", 0o755), b"#!/bin/sh\necho ffmpeg\n"),
            (_file(f"{ROOT}/bin/ffprobe", 0o755), b"#!/bin/sh\necho ffprobe\n"),
            (_file(f"{ROOT}/lib/libavutil.so.61"), b"library"),
            (_file(f"{ROOT}/LICENSE.txt"), b"GPL"),
        ]
    )


def _platform_build(archive: bytes, fmt: str = "tar.xz") -> Any:
    return ft.PlatformBuild(
        platform="linux-x64",
        url=f"https://example.invalid/{ROOT}.{fmt}",
        sha256=_sha256(archive),
        size=len(archive),
        format=fmt,
        root=ROOT,
        bin_dir="bin",
        ffmpeg="bin/ffmpeg",
        ffprobe="bin/ffprobe",
    )


def _build(pbuild: Any) -> Any:
    return ft.Build(
        name="test",
        version="n9.0-test",
        release_version="9.0",
        license="GPL-3.0-or-later",
        source_commit="0" * 40,
        platforms={"linux-x64": pbuild},
    )


def _copier(archive: bytes, calls: list[str]) -> Callable[[str, Path], None]:
    def download(url: str, dest: Path) -> None:
        calls.append(url)
        dest.write_bytes(archive)

    return download


# --------------------------------------------------------------------------- manifest


def test_real_manifest_is_valid() -> None:
    builds = ft.load_manifest(MANIFEST)
    assert set(builds) == {"default", "override-test"}
    for build in builds.values():
        assert set(build.platforms) == {"linux-x64", "windows-x64"}
        assert build.license == "GPL-3.0-or-later"
        assert len(build.source_commit) == 40
        assert build.platforms["windows-x64"].ffmpeg.endswith(".exe")
    # The override job must test a *different* build.
    assert builds["default"].version != builds["override-test"].version
    assert builds["default"].platforms["linux-x64"].sha256 != (
        builds["override-test"].platforms["linux-x64"].sha256
    )


def test_real_manifest_pins_immutable_assets() -> None:
    for build in ft.load_manifest(MANIFEST).values():
        for pbuild in build.platforms.values():
            assert "/releases/download/autobuild-" in pbuild.url
            assert "latest" not in pbuild.url
            assert pbuild.file_name.startswith(pbuild.root)


def _set(data: dict[str, Any], path: str, value: object) -> dict[str, Any]:
    data = copy.deepcopy(data)
    *parents, last = path.split(".")
    table = data
    for key in parents:
        table = table[key]
    if value is None:
        del table[last]
    else:
        table[last] = value
    return data


LINUX = "builds.default.platforms.linux-x64"


@pytest.mark.parametrize(
    ("path", "value", "message"),
    [
        ("schema_version", 2, "schema_version"),
        (f"{LINUX}.sha256", "ABC", "sha256"),
        (f"{LINUX}.sha256", None, "sha256"),
        (f"{LINUX}.url", "http://example.com/x.tar.xz", "https://"),
        (f"{LINUX}.url", "https://example.com/x.zip", "does not end with"),
        (f"{LINUX}.size", 0, "size"),
        (f"{LINUX}.size", True, "size"),
        (f"{LINUX}.format", "7z", "format"),
        (f"{LINUX}.root", "../escape", "root"),
        (f"{LINUX}.root", "a/b", "one folder"),
        (f"{LINUX}.ffmpeg", "/usr/bin/ffmpeg", "relative"),
        (f"{LINUX}.ffprobe", "lib/ffprobe", "bin_dir"),
        ("builds.default.release_version", "6.1", "below 7.0"),
        ("builds.default.release_version", "nine", "X.Y"),
        ("builds.default.version", "n9 0", "spaces"),
        ("builds.default.license", None, "license"),
        ("builds.default.platforms.macos-arm64", {"url": "x"}, "unknown platform"),
    ],
)
def test_manifest_validation_rejects(path: str, value: object, message: str) -> None:
    data = _set(_manifest_data(), path, value)
    with pytest.raises(ft.ManifestError, match=message):
        ft.parse_manifest(data)


def test_manifest_needs_default_build() -> None:
    data = _manifest_data()
    del data["builds"]["default"]
    with pytest.raises(ft.ManifestError, match="default"):
        ft.parse_manifest(data)


@pytest.mark.parametrize(
    ("sys_platform", "machine", "expected"),
    [("linux", "x86_64", "linux-x64"), ("win32", "AMD64", "windows-x64")],
)
def test_detect_platform(sys_platform: str, machine: str, expected: str) -> None:
    assert ft.detect_platform(sys_platform, machine) == expected


@pytest.mark.parametrize(("sys_platform", "machine"), [("darwin", "arm64"), ("linux", "aarch64")])
def test_detect_platform_unsupported(sys_platform: str, machine: str) -> None:
    with pytest.raises(ft.FetchError, match="--platform"):
        ft.detect_platform(sys_platform, machine)


# --------------------------------------------------------------------------- checksums


def test_verify_file_accepts_matching_file(tmp_path: Path) -> None:
    path = tmp_path / "a.bin"
    path.write_bytes(b"payload")
    ft.verify_file(path, _sha256(b"payload"), 7)


def test_verify_file_rejects_wrong_hash(tmp_path: Path) -> None:
    path = tmp_path / "a.bin"
    path.write_bytes(b"payload")
    with pytest.raises(ft.ChecksumError, match="SHA-256"):
        ft.verify_file(path, _sha256(b"other!!"), 7)


def test_verify_file_rejects_wrong_size(tmp_path: Path) -> None:
    path = tmp_path / "a.bin"
    path.write_bytes(b"payload")
    with pytest.raises(ft.ChecksumError, match="size"):
        ft.verify_file(path, _sha256(b"payload"), 8)


def test_install_fails_on_checksum_mismatch_before_extracting(tmp_path: Path) -> None:
    good = _good_tar()
    pbuild = _platform_build(good)
    tampered = good[:-1] + bytes([good[-1] ^ 0xFF])  # same size, one byte changed
    with pytest.raises(ft.ChecksumError):
        ft.install(_build(pbuild), pbuild, tmp_path, downloader=_copier(tampered, []))
    # Nothing was extracted and no temporary folder is left behind.
    assert list((tmp_path / "ffmpeg").iterdir()) == []


# --------------------------------------------------------------------------- safe extraction


@pytest.mark.parametrize(
    "name",
    [
        "../evil",
        f"{ROOT}/../../evil",
        f"{ROOT}/bin/../../evil",
        "/etc/passwd",
        "C:/Windows/evil.dll",
        f"{ROOT}\\..\\evil",
        "other-root/bin/ffmpeg",
        f"{ROOT}/bin/ffmpeg:stream",
        "",
    ],
)
def test_member_path_rejects_unsafe_names(name: str) -> None:
    with pytest.raises(ft.UnsafeArchiveError):
        ft.member_path(name, ROOT)


def test_member_path_accepts_normal_names() -> None:
    assert ft.member_path(f"{ROOT}/bin/ffmpeg", ROOT).parts == (ROOT, "bin", "ffmpeg")
    assert ft.member_path(f"./{ROOT}/lib/", ROOT).parts == (ROOT, "lib")


def test_tar_with_parent_member_is_rejected(tmp_path: Path) -> None:
    archive = tmp_path / "evil.tar.xz"
    archive.write_bytes(
        _tar_xz([(_file(f"{ROOT}/ok"), b"ok"), (_file(f"{ROOT}/../../evil"), b"evil")])
    )
    dest = tmp_path / "dest"
    dest.mkdir()
    with pytest.raises(ft.UnsafeArchiveError):
        ft.safe_extract(archive, "tar.xz", ROOT, dest)
    # Validation runs before extraction: not even the safe member was written.
    assert list(dest.iterdir()) == []
    assert not (tmp_path / "evil").exists()


@pytest.mark.parametrize("target", ["../../../etc/passwd", "/etc/passwd", "../../outside"])
def test_tar_with_escaping_symlink_is_rejected(tmp_path: Path, target: str) -> None:
    archive = tmp_path / "evil.tar.xz"
    archive.write_bytes(_tar_xz([(_symlink(f"{ROOT}/lib/link", target), None)]))
    with pytest.raises(ft.UnsafeArchiveError, match="link"):
        ft.safe_extract(archive, "tar.xz", ROOT, tmp_path)


def test_zip_with_parent_member_is_rejected(tmp_path: Path) -> None:
    archive = tmp_path / "evil.zip"
    archive.write_bytes(_zip([(f"{ROOT}/ok", b"ok", 0o644), ("../evil", b"evil", 0o644)]))
    dest = tmp_path / "dest"
    dest.mkdir()
    with pytest.raises(ft.UnsafeArchiveError):
        ft.safe_extract(archive, "zip", ROOT, dest)
    assert list(dest.iterdir()) == []
    assert not (tmp_path / "evil").exists()


def test_tar_extraction_keeps_layout(tmp_path: Path) -> None:
    archive = tmp_path / "good.tar.xz"
    archive.write_bytes(_good_tar())
    ft.safe_extract(archive, "tar.xz", ROOT, tmp_path / "out")
    assert (tmp_path / "out" / ROOT / "lib" / "libavutil.so.61").read_bytes() == b"library"
    assert (tmp_path / "out" / ROOT / "bin" / "ffmpeg").is_file()


@pytest.mark.skipif(os.name != "posix", reason="POSIX permission bits and symlinks")
def test_tar_extraction_keeps_exec_bit_and_internal_symlinks(tmp_path: Path) -> None:
    archive = tmp_path / "good.tar.xz"
    archive.write_bytes(
        _tar_xz(
            [
                (_file(f"{ROOT}/bin/ffmpeg", 0o755), b"bin"),
                (_file(f"{ROOT}/lib/libavutil.so.61.1"), b"lib"),
                (_symlink(f"{ROOT}/lib/libavutil.so.61", "libavutil.so.61.1"), None),
            ]
        )
    )
    ft.safe_extract(archive, "tar.xz", ROOT, tmp_path)
    assert os.access(tmp_path / ROOT / "bin" / "ffmpeg", os.X_OK)
    assert (tmp_path / ROOT / "lib" / "libavutil.so.61").read_bytes() == b"lib"


@pytest.mark.skipif(os.name != "posix", reason="POSIX permission bits")
def test_zip_extraction_keeps_exec_bit(tmp_path: Path) -> None:
    archive = tmp_path / "good.zip"
    archive.write_bytes(
        _zip([(f"{ROOT}/bin/ffmpeg.exe", b"exe", 0o755), (f"{ROOT}/LICENSE.txt", b"GPL", 0o644)])
    )
    ft.safe_extract(archive, "zip", ROOT, tmp_path)
    assert os.access(tmp_path / ROOT / "bin" / "ffmpeg.exe", os.X_OK)
    assert not os.access(tmp_path / ROOT / "LICENSE.txt", os.X_OK)


# --------------------------------------------------------------------------- install


def test_install_is_idempotent_and_repairs_damage(tmp_path: Path) -> None:
    archive = _good_tar()
    pbuild = _platform_build(archive)
    build = _build(pbuild)
    calls: list[str] = []
    download = _copier(archive, calls)

    install_dir = ft.install(build, pbuild, tmp_path, downloader=download)
    ffmpeg = install_dir / ROOT / "bin" / "ffmpeg"
    assert ffmpeg.is_file()
    assert len(calls) == 1

    # Second run: already extracted and verified, no download.
    assert ft.install(build, pbuild, tmp_path, downloader=download) == install_dir
    assert len(calls) == 1

    # A changed file (corrupt cache) is detected and the build is fetched again.
    ffmpeg.write_bytes(b"corrupt")
    ft.install(build, pbuild, tmp_path, downloader=download)
    assert len(calls) == 2
    assert ffmpeg.read_bytes() == b"#!/bin/sh\necho ffmpeg\n"
    assert sorted(p.name for p in (tmp_path / "ffmpeg").iterdir()) == ["test-linux-x64"]


def test_install_fails_when_ffprobe_is_missing(tmp_path: Path) -> None:
    archive = _tar_xz([(_file(f"{ROOT}/bin/ffmpeg", 0o755), b"bin")])
    pbuild = _platform_build(archive)
    with pytest.raises(ft.FetchError, match="ffprobe"):
        ft.install(_build(pbuild), pbuild, tmp_path, downloader=_copier(archive, []))


def test_main_prints_only_the_bin_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsysbinary: pytest.CaptureFixture[bytes]
) -> None:
    archive = _good_tar()
    pbuild = _platform_build(archive)
    manifest = tmp_path / "ffmpeg.toml"
    manifest.write_text(
        f"""
schema_version = 1
[builds.default]
version = "n9.0-test"
release_version = "9.0"
license = "GPL-3.0-or-later"
source_repository = "https://example.invalid/ffmpeg"
source_commit = "{"0" * 40}"
release_tag = "test"
[builds.default.platforms.linux-x64]
url = "{pbuild.url}"
sha256 = "{pbuild.sha256}"
size = {pbuild.size}
format = "tar.xz"
root = "{ROOT}"
bin_dir = "bin"
ffmpeg = "bin/ffmpeg"
ffprobe = "bin/ffprobe"
""",
        encoding="utf-8",
    )
    monkeypatch.setattr(ft, "download", lambda url, dest: dest.write_bytes(archive))
    # Pretend the host is another platform so the fake binaries are not executed.
    monkeypatch.setattr(ft, "detect_platform", lambda *a: "windows-x64")

    code = ft.main(
        ["--platform", "linux-x64", "--dest", str(tmp_path / "tools"), "--manifest", str(manifest)]
    )
    out, err = capsysbinary.readouterr()
    assert code == 0
    expected = (tmp_path / "tools" / "ffmpeg" / "default-linux-x64" / ROOT / "bin").resolve()
    assert out == f"{expected}\n".encode()
    assert b"version check skipped" in err


def test_main_reports_unknown_build(capsys: pytest.CaptureFixture[str]) -> None:
    assert ft.main(["--build", "nope", "--platform", "linux-x64"]) == 1
    out, err = capsys.readouterr()
    assert out == ""
    assert "unknown build 'nope'" in err


# --------------------------------------------------------------------------- download retries


class _Response(io.BytesIO):
    pass


def test_download_retries_network_errors(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    errors: list[Exception] = [
        urllib.error.URLError("connection reset"),
        urllib.error.HTTPError("https://x", 503, "unavailable", Message(), None),
    ]

    def urlopen(request: object, timeout: float) -> _Response:
        if errors:
            raise errors.pop(0)
        return _Response(b"archive")

    monkeypatch.setattr(urllib.request, "urlopen", urlopen)
    delays: list[float] = []
    ft.download("https://x/a.zip", tmp_path / "a.zip", sleep=delays.append)
    assert (tmp_path / "a.zip").read_bytes() == b"archive"
    assert delays == [2.0, 4.0]


def test_download_does_not_retry_404(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[object] = []

    def urlopen(request: object, timeout: float) -> _Response:
        calls.append(request)
        raise urllib.error.HTTPError("https://x", 404, "not found", Message(), None)

    monkeypatch.setattr(urllib.request, "urlopen", urlopen)
    with pytest.raises(ft.FetchError, match="404"):
        ft.download("https://x/a.zip", tmp_path / "a.zip", sleep=lambda _: None)
    assert len(calls) == 1
    assert not (tmp_path / "a.zip").exists()
