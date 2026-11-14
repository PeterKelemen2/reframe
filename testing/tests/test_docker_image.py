"""The Docker image's FFmpeg platform per architecture and its Debian package list."""

from __future__ import annotations

import re
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
DOCKER = REPO_ROOT / "docker"

skip_windows = pytest.mark.skipif(sys.platform == "win32", reason="the image is Linux")


def _stage(name: str) -> str:
    text = (DOCKER / "Dockerfile").read_text(encoding="utf-8")
    match = re.search(rf"^FROM \S+ AS {name}\n(.*?)(?=^FROM )", text, re.M | re.S)
    assert match, name
    return match.group(1)


def test_each_image_architecture_fetches_an_ffmpeg_platform_that_is_pinned() -> None:
    # The arm64 image cannot be built on an amd64 host without emulation: a wrong name here
    # would only show in a release build.
    mapping = dict(re.findall(r"(\w+)\) platform=([\w-]+) ;;", _stage("tools")))
    manifest = tomllib.loads((REPO_ROOT / "tools" / "ffmpeg.toml").read_text(encoding="utf-8"))

    assert mapping == {"amd64": "linux-x64", "arm64": "linux-arm64"}
    assert set(mapping.values()) <= set(manifest["builds"]["default"]["platforms"])


def test_each_image_architecture_wants_the_notices_of_its_own_platform() -> None:
    mapping = dict(re.findall(r"(\w+)\) want=([\w-]+) ;;", _stage("notices")))

    assert mapping == {"amd64": "docker-linux-x64", "arm64": "docker-linux-arm64"}


DPKG_ROWS = [
    # Status, package, version, source package, source version.
    ("ii ", "tini", "0.19.0-3+b8", "tini", "0.19.0-3"),
    ("ii ", "login", "1:4.17.4-2", "shadow", "1:4.17.4-2"),
    ("ii ", "libc6:amd64", "2.41-12", "glibc", "2.41-12"),
    ("rc ", "removed-package", "1.0-1", "removed-package", "1.0-1"),
    ("ii ", "mkvtoolnix", "92.0-1+deb13u1", "mkvtoolnix", "92.0-1+deb13u1"),
]


@pytest.fixture
def fake_dpkg(tmp_path: Path) -> dict[str, str]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    rows = "".join("\t".join(row) + "\n" for row in DPKG_ROWS)
    (bin_dir / "rows.tsv").write_text(rows, encoding="utf-8")
    (bin_dir / "dpkg").write_text("#!/bin/sh\necho amd64\n", encoding="utf-8")
    (bin_dir / "dpkg-query").write_text(f'#!/bin/sh\ncat "{bin_dir}/rows.tsv"\n', encoding="utf-8")
    for tool in ("dpkg", "dpkg-query"):
        (bin_dir / tool).chmod(0o755)
    return {"PATH": f"{bin_dir}:/usr/bin:/bin"}


@skip_windows
def test_the_package_list_links_each_installed_package_to_its_source_on_snapshot(
    tmp_path: Path, fake_dpkg: dict[str, str]
) -> None:
    out = tmp_path / "DEBIAN_PACKAGES"
    subprocess.run(
        ["sh", str(DOCKER / "debian-packages.sh"), str(out)], env=fake_dpkg, check=True, timeout=30
    )
    lines = out.read_text(encoding="utf-8").splitlines()

    assert lines[0] == "Debian packages in this image (amd64), as dpkg lists them."
    snapshot = "https://snapshot.debian.org/package"
    # A binNMU's binary version (+b8) is not a source version: the link takes the source's.
    assert lines[3:] == [
        f"libc6:amd64 2.41-12 glibc 2.41-12 {snapshot}/glibc/2.41-12/",
        f"login 1:4.17.4-2 shadow 1:4.17.4-2 {snapshot}/shadow/1%3A4.17.4-2/",
        "mkvtoolnix 92.0-1+deb13u1 mkvtoolnix 92.0-1+deb13u1"
        f" {snapshot}/mkvtoolnix/92.0-1%2Bdeb13u1/",
        f"tini 0.19.0-3+b8 tini 0.19.0-3 {snapshot}/tini/0.19.0-3/",
    ]
    assert not out.with_name("DEBIAN_PACKAGES.part").exists()
