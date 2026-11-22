"""The Docker image's architectures, notices and Debian package list."""

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


def test_each_image_architecture_can_download_the_default_build() -> None:
    # The image contains no FFmpeg: a container downloads the default build for its platform
    # at the first start, so every architecture the image is built for needs a pinned archive.
    architectures = dict(re.findall(r"(\w+)\) want=docker-([\w-]+) ;;", _stage("notices")))
    manifest = tomllib.loads((REPO_ROOT / "tools" / "ffmpeg.toml").read_text(encoding="utf-8"))

    assert architectures == {"amd64": "linux-x64", "arm64": "linux-arm64"}
    assert set(architectures.values()) <= set(manifest["builds"]["default"]["platforms"])


def test_each_image_architecture_wants_the_notices_of_its_own_platform() -> None:
    mapping = dict(re.findall(r"(\w+)\) want=([\w-]+) ;;", _stage("notices")))

    assert mapping == {"amd64": "docker-linux-x64", "arm64": "docker-linux-arm64"}


DPKG_ROWS = [
    # Status, package, version, source package, source version.
    ("ii ", "tini", "0.19.0-3+b8", "tini", "0.19.0-3"),
    ("ii ", "login", "1:4.17.4-2", "shadow", "1:4.17.4-2"),
    ("ii ", "libc6:amd64", "2.41-12", "glibc", "2.41-12"),
    ("rc ", "removed-package", "1.0-1", "removed-package", "1.0-1"),
    ("ii ", "mesa-va-drivers", "25.0.7-2+deb13u1", "mesa", "25.0.7-2+deb13u1"),
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
        "mesa-va-drivers 25.0.7-2+deb13u1 mesa 25.0.7-2+deb13u1"
        f" {snapshot}/mesa/25.0.7-2%2Bdeb13u1/",
        f"tini 0.19.0-3+b8 tini 0.19.0-3 {snapshot}/tini/0.19.0-3/",
    ]
    assert not out.with_name("DEBIAN_PACKAGES.part").exists()


def _notices_check(notices: Path, arch: str) -> subprocess.CompletedProcess[str]:
    """The notices stage's RUN command against the folder ``notices`` in place of /notices."""
    run = _stage("notices").split("\nRUN ", 1)[1].replace("\\\n", "")
    return subprocess.run(
        ["sh", "-c", re.sub("(?<!docker)/notices/", f"{notices}/", run)],
        env={"PATH": "/usr/bin:/bin", "TARGETARCH": arch},
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )


@skip_windows
@pytest.mark.parametrize("content", [None, ""])
def test_the_build_stops_without_the_notices_and_says_how_to_write_them(
    tmp_path: Path, content: str | None
) -> None:
    (tmp_path / "notices").mkdir()
    if content is not None:
        (tmp_path / "notices" / "THIRD_PARTY_NOTICES").write_text(content)

    result = _notices_check(tmp_path / "notices", "amd64")

    assert result.returncode == 1
    assert "docker/notices/THIRD_PARTY_NOTICES is missing: write it with" in result.stderr


@skip_windows
@pytest.mark.parametrize(("arch", "ok"), [("amd64", False), ("arm64", True)])
def test_the_build_takes_only_the_notices_of_its_own_platform(
    tmp_path: Path, arch: str, ok: bool
) -> None:
    (tmp_path / "notices").mkdir()
    (tmp_path / "notices" / "THIRD_PARTY_NOTICES").write_text(
        "Third-party notices for Reframe 1.0.0 (docker-linux-arm64)\n"
    )

    result = _notices_check(tmp_path / "notices", arch)

    assert (result.returncode == 0) == ok, result.stderr
    assert ("is not the one for docker-linux-x64" in result.stderr) == (not ok)


def _doc_root(tmp_path: Path, texts: dict[str, str]) -> Path:
    """``/usr/share/doc`` with a copyright file per package (``name`` → text)."""
    doc = tmp_path / "doc"
    for name, text in texts.items():
        (doc / name).mkdir(parents=True)
        (doc / name / "copyright").write_text(text, encoding="utf-8")
    return doc


COPYRIGHTS = {
    "libc6": "glibc: LGPL-2.1+\n",
    "login": "shadow: BSD-3-Clause\n",
    "mesa-va-drivers": "Mesa: MIT\n",
    "tini": "tini: MIT, Copyright (c) Thomas Orozco\n",
}


@skip_windows
def test_the_notices_get_each_installed_packages_copyright_file_once(
    tmp_path: Path, fake_dpkg: dict[str, str]
) -> None:
    """The owner's rule: every bundled part's licence text, the image's Debian packages too."""
    notices = tmp_path / "THIRD_PARTY_NOTICES"
    notices.write_text("Third-party notices for Reframe 1.0.0 (docker-linux-x64)\n")
    texts = COPYRIGHTS | {"login": "glibc: LGPL-2.1+\n", "removed-package": "not installed\n"}
    env = fake_dpkg | {"REFRAME_DOC_ROOT": str(_doc_root(tmp_path, texts))}

    subprocess.run(
        ["sh", str(DOCKER / "debian-packages.sh"), str(tmp_path / "LIST"), str(notices)],
        env=env,
        check=True,
        timeout=30,
    )

    text = notices.read_text(encoding="utf-8")
    assert text.startswith("Third-party notices for Reframe 1.0.0 (docker-linux-x64)\n\n")
    section = text.split("the copyright file of each\n", 1)[1]
    packages = re.findall(r"^-{78}\n(\S+)\n-{78}$", section, re.MULTILINE)
    assert packages == ["libc6:amd64", "login", "mesa-va-drivers", "tini"]
    assert section.count("glibc: LGPL-2.1+") == 1
    assert "The same text as libc6:amd64 above." in section
    for package in ("mesa-va-drivers", "tini"):
        assert COPYRIGHTS[package] in section
    assert "not installed" not in section
    assert not notices.with_name("THIRD_PARTY_NOTICES.part").exists()


@skip_windows
def test_a_package_without_its_copyright_file_stops_the_image_build(
    tmp_path: Path, fake_dpkg: dict[str, str]
) -> None:
    notices = tmp_path / "THIRD_PARTY_NOTICES"
    notices.write_text("notices\n")
    texts = {name: text for name, text in COPYRIGHTS.items() if name != "tini"}
    env = fake_dpkg | {"REFRAME_DOC_ROOT": str(_doc_root(tmp_path, texts))}

    result = subprocess.run(
        ["sh", str(DOCKER / "debian-packages.sh"), str(tmp_path / "LIST"), str(notices)],
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )

    assert result.returncode != 0
    assert "tini has no" in result.stderr
    assert notices.read_text() == "notices\n"


def test_the_image_build_adds_the_copyright_files_to_its_notices() -> None:
    dockerfile = (DOCKER / "Dockerfile").read_text(encoding="utf-8").replace("\\\n", " ")

    assert re.search(
        r"sh /tmp/debian-packages\.sh /opt/reframe/notices/DEBIAN_PACKAGES\s+"
        r"/opt/reframe/notices/THIRD_PARTY_NOTICES",
        dockerfile,
    )
