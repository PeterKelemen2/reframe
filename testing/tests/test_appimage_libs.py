"""scripts/appimage-libs.py: the AppImage's distro packages before the build, and the check of
the built AppDir against them."""

from __future__ import annotations

import json
import os
import stat
import struct
import sys
from pathlib import Path

import pytest

from reframe_testing.scripts import load_script

al = load_script("appimage-libs.py")

# dpkg's info files are named "package:arch.list", which is not a Windows file name, and
# dpkg-query exists only in the Linux build image the script runs in.
dpkg_only = pytest.mark.skipif(sys.platform == "win32", reason="dpkg exists only on Linux")

# What dpkg-query prints for the fake installed packages; the last one is removed (config left).
DPKG_ROWS = {
    "libgtk-3-0": "libgtk-3-0\tamd64\t3.24.33-1ubuntu2.2\tgtk+3.0\t3.24.33-1ubuntu2.2\tii ",
    "libxau6": "libxau6\tamd64\t1:1.0.9-1build5\tlibxau\t1:1.0.9-1build5\tii ",
    "libold1": "libold1\tamd64\t1.0-1\told\t1.0-1\trc ",
}


@pytest.fixture
def fake_dpkg(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A dpkg-query on PATH that knows :data:`DPKG_ROWS`, and an os-release of Ubuntu 22.04."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    script = bin_dir / "dpkg-query"
    script.write_text(
        f"#!{sys.executable}\n"
        "import sys\n"
        f"rows = {DPKG_ROWS!r}\n"
        "for name in sys.argv[3:]:\n"
        "    print(rows[name]) if name in rows else sys.exit(1)\n"
    )
    script.chmod(script.stat().st_mode | stat.S_IXUSR)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    os_release = tmp_path / "os-release"
    os_release.write_text('NAME="Ubuntu"\nID=ubuntu\nVERSION_ID="22.04"\n')
    monkeypatch.setattr(al, "OS_RELEASE", os_release)
    return tmp_path


def _dpkg_info(folder: Path, owned: dict[str, list[str]]) -> Path:
    folder.mkdir(parents=True)
    for package, paths in owned.items():
        (folder / f"{package}:amd64.list").write_text("\n".join(paths) + "\n")
    return folder


INDEX_FILES = {
    "libgtk-3-0": [
        "/usr/lib/x86_64-linux-gnu/libgtk-3.so.0",
        "/usr/lib/x86_64-linux-gnu/gtk-3.0/3.0.0/immodules/im-xim.so",
    ],
    "libxau6": ["/usr/lib/x86_64-linux-gnu/libXau.so.6", "/usr/share/doc/libxau6"],
    "libblkid1": ["/lib/x86_64-linux-gnu/libblkid.so.1"],
}


def _index(tmp_path: Path) -> dict[str, list[tuple[str, str]]]:
    index: dict[str, list[tuple[str, str]]] = al.file_index(
        _dpkg_info(tmp_path / "info", INDEX_FILES)
    )
    return index


def _appdir(root: Path, files: list[str]) -> Path:
    for name in files:
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"\x7fELF")
    return root


def test_the_package_list_ignores_comments_and_blank_lines(tmp_path: Path) -> None:
    listing = tmp_path / "packages.txt"
    listing.write_text("# header\nlibxau6\n\nlibgtk-3-0  # GTK\nlibxau6\n")

    assert al.read_package_list(listing) == ["libgtk-3-0", "libxau6"]


def test_an_empty_package_list_is_an_error(tmp_path: Path) -> None:
    listing = tmp_path / "packages.txt"
    listing.write_text("# nothing\n")

    with pytest.raises(al.AppImageLibsError, match="lists no package"):
        al.read_package_list(listing)


@dpkg_only
def test_resolve_gives_each_packages_source_and_version(fake_dpkg: Path, tmp_path: Path) -> None:
    listing = tmp_path / "packages.txt"
    listing.write_text("libxau6\nlibgtk-3-0\n")
    out = tmp_path / "out" / "appimage-libs.json"

    assert al.main(["--packages", str(listing), "resolve", "--out", str(out)]) == 0

    data = json.loads(out.read_text())
    assert data["distribution"] == {"id": "ubuntu", "version_id": "22.04"}
    assert data["packages"] == [
        {
            "package": "libgtk-3-0",
            "architecture": "amd64",
            "version": "3.24.33-1ubuntu2.2",
            "source": "gtk+3.0",
            "source_version": "3.24.33-1ubuntu2.2",
        },
        {
            "package": "libxau6",
            "architecture": "amd64",
            "version": "1:1.0.9-1build5",
            "source": "libxau",
            "source_version": "1:1.0.9-1build5",
        },
    ]


@dpkg_only
@pytest.mark.parametrize("package", ["libmissing", "libold1"])
def test_a_listed_package_that_is_not_installed_is_an_error(fake_dpkg: Path, package: str) -> None:
    with pytest.raises(al.AppImageLibsError, match=f"not installed in this image: {package}"):
        al.query_packages(["libxau6", package])


@dpkg_only
@pytest.mark.parametrize(
    ("relative", "package"),
    [
        ("usr/lib/gtk-3.0/3.0.0/immodules/im-xim.so", "libgtk-3-0"),
        ("usr/lib/im-xim.so", "libgtk-3-0"),
        ("usr/share/doc/libxau6/copyright", "libxau6"),
    ],
)
def test_each_appdir_file_maps_to_the_package_it_was_copied_from(
    tmp_path: Path, relative: str, package: str
) -> None:
    assert al.owner(relative, _index(tmp_path)) == {package}


@dpkg_only
def test_the_appdir_gives_the_packages_of_its_distro_files_only(tmp_path: Path) -> None:
    appdir = _appdir(
        tmp_path / "Reframe.AppDir",
        [
            "AppRun",
            "usr/bin/reframe-desktop",
            "usr/lib/Reframe/sidecar/reframe-server",
            "usr/share/icons/hicolor/32x32/apps/reframe-desktop.png",
            "usr/lib/libgtk-3.so.0",
            "usr/lib/libblkid.so.1",
            "usr/lib/gtk-3.0/3.0.0/immodules.cache",
        ],
    )

    assert al.appdir_packages(appdir, _index(tmp_path)) == ["libblkid1", "libgtk-3-0"]


@dpkg_only
def test_an_appdir_library_that_no_package_owns_is_an_error(tmp_path: Path) -> None:
    appdir = _appdir(tmp_path / "Reframe.AppDir", ["usr/lib/libgtk-3.so.0", "usr/lib/libmine.so"])

    with pytest.raises(al.AppImageLibsError, match=r"usr/lib/libmine\.so \(no package\)"):
        al.appdir_packages(appdir, _index(tmp_path))


def _row(package: str, version: str) -> dict[str, str]:
    return {
        "package": package,
        "architecture": "amd64",
        "version": version,
        "source": package,
        "source_version": version,
    }


def test_the_comparison_names_every_change() -> None:
    dist = {"id": "ubuntu", "version_id": "22.04"}
    expected = al.document([_row("liba", "1"), _row("libb", "1"), _row("libc", "1")], dist)
    actual = al.document([_row("libb", "2"), _row("libc", "1"), _row("libd", "1")], dist)

    problems = al.compare(expected, actual)

    assert [line.split(":")[0] for line in problems] == ["liba", "libd", "libb"]
    assert al.compare(expected, expected) == []


@dpkg_only
def test_the_check_passes_only_for_the_packages_and_versions_the_manifest_has(
    fake_dpkg: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    index = _index(tmp_path)
    monkeypatch.setattr(al, "file_index", lambda: index)
    appdir = _appdir(tmp_path / "Reframe.AppDir", ["usr/lib/libgtk-3.so.0", "usr/lib/libXau.so.6"])
    listing = tmp_path / "packages.txt"
    listing.write_text("libgtk-3-0\nlibxau6\n")
    expected = tmp_path / "expected.json"
    al.resolve(listing, expected)

    assert al.check(appdir, expected, listing) == []

    data = json.loads(expected.read_text())
    data["packages"][0]["source_version"] = "3.24.33-1ubuntu2.1"
    expected.write_text(json.dumps(data))
    [problem] = al.check(appdir, expected, listing)
    assert problem.startswith("libgtk-3-0: ")


@dpkg_only
def test_the_check_prints_the_list_to_commit_when_the_appimage_has_other_packages(
    fake_dpkg: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    index = _index(tmp_path)
    monkeypatch.setattr(al, "file_index", lambda: index)
    appdir = _appdir(tmp_path / "Reframe.AppDir", ["usr/lib/libgtk-3.so.0", "usr/lib/libXau.so.6"])
    listing = tmp_path / "packages.txt"
    listing.write_text("libgtk-3-0\n")
    expected = tmp_path / "expected.json"
    al.resolve(listing, expected)

    code = al.main(["--packages", str(listing), "check", str(appdir), "--expected", str(expected)])

    assert code == 1
    err = capsys.readouterr().err
    assert "libxau6: in the AppImage, but not in the list" in err
    assert err.endswith("update packages.txt to the AppImage's packages:\nlibgtk-3-0\nlibxau6\n")


def test_the_committed_list_is_one_package_name_per_line() -> None:
    names = al.read_package_list(al.DEFAULT_PACKAGES)

    assert all(name.replace(".", "").replace("+", "").replace("-", "").isalnum() for name in names)
    assert {"libwebkit2gtk-4.1-0", "libgtk-3-0", "libayatana-appindicator3-1"} <= set(names)
    # The frozen sidecar's system libraries, in the .deb and .rpm too.
    assert {"libgcc-s1", "libstdc++6", "zlib1g"} <= set(names)


SIDECAR_INDEX = {
    "zlib1g": ["/lib/x86_64-linux-gnu/libz.so.1", "/lib/x86_64-linux-gnu/libz.so.1.2.11"],
    "libstdc++6": [
        "/usr/lib/x86_64-linux-gnu/libstdc++.so.6",
        "/usr/share/gdb/auto-load/usr/lib/x86_64-linux-gnu/libstdc++.so.6.0.30-gdb.py",
    ],
    "python3-docs": ["/usr/share/doc/python3/base_library.zip"],
    "libyaml-0-2": ["/usr/lib/x86_64-linux-gnu/libyaml-0.so.2"],
    "libva2": ["/usr/lib/x86_64-linux-gnu/libva.so.2"],
}


@dpkg_only
def test_the_sidecars_system_libraries_map_to_their_packages(tmp_path: Path) -> None:
    index = al.file_index(_dpkg_info(tmp_path / "info", SIDECAR_INDEX))
    internal = "usr/lib/Reframe/sidecar/_internal"
    appdir = _appdir(
        tmp_path / "Reframe.AppDir",
        [
            f"{internal}/libz.so.1",
            f"{internal}/libstdc++.so.6",
            f"{internal}/libpython3.14.so.1.0",
            f"{internal}/base_library.zip",
            # A wheel's own copy and the bundled tools' libraries are not the image's.
            f"{internal}/yaml/libyaml-0.so.2",
            "usr/lib/Reframe/tools/ffmpeg/lib/libva.so.2",
        ],
    )

    assert al.appdir_packages(appdir, index) == ["libstdc++6", "zlib1g"]


@dpkg_only
def test_a_file_that_two_packages_own_is_an_error(tmp_path: Path) -> None:
    owned = {"libfoo1": ["/usr/lib/x86_64-linux-gnu/libfoo.so.1"]}
    owned["libfoo1-compat"] = owned["libfoo1"]
    index = al.file_index(_dpkg_info(tmp_path / "info", owned))
    appdir = _appdir(
        tmp_path / "Reframe.AppDir",
        ["usr/lib/libfoo.so.1", "usr/lib/Reframe/sidecar/_internal/libfoo.so.1"],
    )

    with pytest.raises(al.AppImageLibsError) as error:
        al.appdir_packages(appdir, index)

    for path in ("usr/lib/libfoo.so.1", "usr/lib/Reframe/sidecar/_internal/libfoo.so.1"):
        assert f"{path} (libfoo1, libfoo1-compat)" in str(error.value)


def test_a_list_resolved_on_another_distribution_does_not_match() -> None:
    packages = [_row("liba", "1")]
    expected = al.document(packages, {"id": "ubuntu", "version_id": "24.04"})
    actual = al.document(packages, {"id": "ubuntu", "version_id": "22.04"})

    [problem] = al.compare(expected, actual)

    assert problem.startswith("distribution: ")


RUNTIME_SECTIONS = (".text", ".digest_md5", ".upd_info", ".sha256_sig", ".sig_key")


def _elf(sections: dict[str, bytes]) -> bytes:
    """A 64-bit little-endian ELF file with ``sections``, their header table at its end."""
    names = b"\0" + b"".join(name.encode() + b"\0" for name in [*sections, ".shstrtab"])
    body, headers, offset = b"", [bytes(64)], 64
    for name, data in [*sections.items(), (".shstrtab", names)]:
        headers.append(
            struct.pack(
                "<IIQQQQIIQQ", names.index(name.encode()), 1, 0, 0, offset, len(data), 0, 0, 1, 0
            )
        )
        body, offset = body + data, offset + len(data)
    header = b"\x7fELF\x02\x01\x01" + bytes(9)
    header += struct.pack(
        "<HHIQQQIHHHHHH", 2, 62, 1, 0, 0, offset, 0, 64, 0, 0, 64, len(headers), len(headers) - 1
    )
    return header + body + b"".join(headers)


def _runtime(text: bytes = b"runtime code") -> bytes:
    return _elf({name: text if name == ".text" else bytes(16) for name in RUNTIME_SECTIONS})


def _written(runtime: bytes, section: str, data: bytes) -> bytes:
    """``runtime`` with ``data`` at the start of ``section``."""
    offset = al._elf_sections(runtime)[section][0]
    return runtime[:offset] + data + runtime[offset + len(data) :]


def test_an_appimage_starts_with_its_runtime_apart_from_what_appimagetool_writes() -> None:
    runtime = _runtime()
    appimage = _written(runtime, ".digest_md5", b"\x01" * 16)
    appimage = _written(appimage, ".upd_info", b"zsync|owner/repo") + b"hsqs squashfs"

    assert al.runtime_matches(appimage, runtime)
    assert not al.runtime_matches(_written(runtime, ".text", b"other  code!"), runtime)
    assert not al.runtime_matches(_runtime(b"runtime-code"), runtime)
    assert not al.runtime_matches(runtime[:-1], runtime)


def test_a_file_that_is_not_a_type_2_runtime_is_refused(tmp_path: Path) -> None:
    with pytest.raises(al.AppImageLibsError, match="data sections are missing"):
        al.runtime_matches(b"", _elf({".text": b"code"}))
    with pytest.raises(al.AppImageLibsError, match="not a 64-bit"):
        al.runtime_matches(b"", b"\x89PNG\r\n")


def test_check_runtime_exits_1_for_another_runtime(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / "runtime").write_bytes(_runtime())
    (tmp_path / "Reframe.AppImage").write_bytes(_runtime(b"other  code!") + b"hsqs")

    code = al.main(
        [
            "check-runtime",
            str(tmp_path / "Reframe.AppImage"),
            "--runtime",
            str(tmp_path / "runtime"),
        ]
    )

    assert code == 1
    assert "does not start with the runtime" in capsys.readouterr().err
