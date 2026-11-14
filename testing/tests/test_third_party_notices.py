"""scripts/third-party-notices.py: which components get a notice, and what each notice says."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import re
import shutil
import sys
from collections.abc import Mapping
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "third-party-notices.py"
SIDECAR = REPO_ROOT / "desktop" / "src-tauri" / "resources" / "sidecar"


def _load_script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("third_party_notices", SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # dataclasses look the module up by name
    spec.loader.exec_module(module)
    return module


tpn = _load_script()

needs_sidecar = pytest.mark.skipif(
    not (SIDECAR / "reframe-server").is_file(),
    reason="no frozen sidecar: run uv run python desktop/sidecar/build.py",
)


def test_every_distribution_that_provides_a_shipped_module_is_listed() -> None:
    packages = {
        "pydantic": ["pydantic"],
        "pydantic_core": ["pydantic_core"],
        "yaml": ["PyYAML"],
        "reframe": ["reframe"],
        "reframe_server": ["reframe-server"],
        "_pytest": ["pytest"],
    }
    shipped = {"pydantic", "pydantic_core", "yaml", "reframe", "reframe_server", "json", "asyncio"}

    found = tpn.shipped_distributions(shipped, packages)

    assert found == ["pydantic", "pydantic-core", "pyinstaller", "pyyaml"]


@needs_sidecar
def test_the_frozen_sidecars_modules_and_libraries_are_read() -> None:
    names = tpn.shipped_top_level_names(SIDECAR)

    # pydantic is pure Python inside the executables' archives; pydantic_core and pymediainfo
    # are folders in _internal.
    assert {"pydantic", "guessit", "uvicorn", "typer", "pydantic_core", "pymediainfo"} <= names


def test_a_missing_sidecar_is_an_error(tmp_path: Path) -> None:
    with pytest.raises(tpn.NoticesError, match="no frozen sidecar"):
        tpn.shipped_top_level_names(tmp_path)


def _pip_row(name: str, text: str = "Copyright text", notice: str = "UNKNOWN") -> dict[str, str]:
    return {
        "Name": name,
        "Version": "1.0",
        "License": "MIT",
        "URL": "UNKNOWN",
        "LicenseText": text,
        "NoticeText": notice,
    }


def test_pip_licenses_rows_keep_licence_and_notice_texts() -> None:
    rows = [_pip_row("Foo_Bar", notice="Notice of foo"), _pip_row("baz", text="UNKNOWN")]

    entries = tpn.parse_pip_licenses(rows, ["foo-bar", "baz"])

    assert [(e.name, e.url, e.text) for e in entries] == [
        ("baz", "", ""),
        ("Foo_Bar", "", "Copyright text\n\nNotice of foo"),
    ]


def test_a_shipped_distribution_that_pip_licenses_skipped_is_an_error() -> None:
    with pytest.raises(tpn.NoticesError, match="no data for missing"):
        tpn.parse_pip_licenses([_pip_row("present")], ["present", "missing"])


def test_license_checker_reads_licence_files_but_not_readmes(tmp_path: Path) -> None:
    (tmp_path / "LICENSE.md").write_text("MIT License, Vue authors")
    (tmp_path / "README.md").write_text("# rfc6902\nusage …")
    report = {
        "@vue/shared@3.5.0": {
            "licenses": "MIT",
            "repository": "https://github.com/vuejs/core",
            "licenseFile": str(tmp_path / "LICENSE.md"),
        },
        "rfc6902@5.3.0": {
            "licenses": ["MIT", "BSD-2-Clause"],
            "licenseFile": str(tmp_path / "README.md"),
        },
    }

    entries = tpn.parse_license_checker(report)

    assert [(e.name, e.version, e.license, e.text) for e in entries] == [
        ("@vue/shared", "3.5.0", "MIT", "MIT License, Vue authors"),
        ("rfc6902", "5.3.0", "MIT AND BSD-2-Clause", ""),
    ]


def _crate(name: str, version: str) -> dict[str, Any]:
    return {"crate": {"name": name, "version": version}}


def test_cargo_about_licences_list_the_crates_but_not_reframes_own() -> None:
    report = {
        "licenses": [
            {
                "name": "MIT License",
                "id": "MIT",
                "text": "MIT text",
                "used_by": [_crate("serde", "1.0.0"), _crate("tauri", "2.12.5")],
            },
            {
                "name": "GNU General Public License v3.0 or later",
                "id": "GPL-3.0-or-later",
                "text": "GPL text",
                "used_by": [_crate("reframe-desktop", "0.1.0")],
            },
        ]
    }

    entries = tpn.parse_cargo_about(report)

    assert len(entries) == 1
    assert entries[0].license == "MIT"
    assert entries[0].text == "Used by: serde 1.0.0, tauri 2.12.5\n\nMIT text"


@pytest.mark.parametrize("platform", ["linux-x64", "windows-x64"])
def test_cargo_about_is_limited_to_the_packages_target(platform: str) -> None:
    config = tpn._about_config(tpn.RUST_TARGETS[platform])

    assert f'targets = ["{tpn.RUST_TARGETS[platform]}"]' in config
    assert "ignore-build-dependencies = true" in config


def _layout(tools: Path, name: str, licence: str = "LICENSE.txt") -> None:
    (tools / name / "bin").mkdir(parents=True)
    (tools / name / licence).write_text(f"{name} licence text")


def test_the_bundled_ffmpeg_gets_its_pin_with_the_source_links(tmp_path: Path) -> None:
    tools = tmp_path / "resources" / "tools"
    _layout(tools, "ffmpeg")
    (tools / "ffmpeg" / "LICENSE-libva.txt").write_text("libva licence text")
    manifests = REPO_ROOT / "tools"

    [entry, _libva] = tpn.tool_entries(tools, manifests, "linux-x64")

    pin = tpn.tomllib.loads((manifests / "ffmpeg.toml").read_text())["builds"]["default"]
    archive = pin["platforms"]["linux-x64"]
    assert entry.name == "ffmpeg"
    assert entry.version == pin["version"]
    assert entry.license == pin["license"]
    for value in (
        pin["source_repository"],
        pin["source_commit"],
        pin["build_scripts_repository"],
        pin["build_scripts_commit"],
        archive["url"],
        archive["sha256"],
    ):
        assert value in entry.text
    assert pin["platforms"]["windows-x64"]["url"] not in entry.text
    assert entry.text.endswith("ffmpeg licence text")


def test_a_library_built_into_a_tool_gets_its_pin_and_licence(tmp_path: Path) -> None:
    tools = tmp_path / "tools"
    _layout(tools, "ffmpeg")
    (tools / "ffmpeg" / "LICENSE-libva.txt").write_text("libva licence text")
    manifests = REPO_ROOT / "tools"

    entries = tpn.tool_entries(tools, manifests, "linux-x64")

    pin = tpn.tomllib.loads((manifests / "bundled-tools.toml").read_text())["libraries"]["libva"]
    assert [entry.name for entry in entries] == ["ffmpeg", "libva"]
    libva = entries[1]
    assert (libva.version, libva.license, libva.url) == (
        pin["version"],
        pin["license"],
        pin["release_url"],
    )
    for value in (
        pin["source_repository"],
        pin["source_tag"],
        pin["platforms"]["linux-x64"]["url"],
        pin["platforms"]["linux-x64"]["sha256"],
        "tools/ffmpeg/LICENSE-libva.txt",
    ):
        assert value in libva.text
    assert libva.text.endswith("libva licence text")


def test_a_library_without_its_licence_file_is_an_error(tmp_path: Path) -> None:
    tools = tmp_path / "tools"
    _layout(tools, "ffmpeg")

    with pytest.raises(tpn.NoticesError, match=r"LICENSE-libva\.txt"):
        tpn.tool_entries(tools, REPO_ROOT / "tools", "linux-x64")


def test_a_library_pinned_for_another_platform_gets_no_entry(tmp_path: Path) -> None:
    tools = tmp_path / "tools"
    _layout(tools, "ffmpeg")

    [entry] = tpn.tool_entries(tools, REPO_ROOT / "tools", "windows-x64")

    assert entry.name == "ffmpeg"


def _write_pin(path: Path, table: str) -> None:
    path.write_text(
        f"[{table}]\n"
        'version = "103.0"\nlicense = "GPL-2.0-only"\nlicense_file = "COPYING"\n'
        'source_url = "https://mkvtoolnix.download/sources/mkvtoolnix-103.0.tar.xz"\n'
        f"[{table}.platforms.windows-x64]\n"
        'url = "https://mkvtoolnix.download/windows/mkvtoolnix-64-bit-103.0.7z"\n'
    )


@pytest.mark.parametrize("table", ["builds.default", "tools.mkvtoolnix"])
def test_another_tools_pin_is_found_in_its_own_or_a_shared_manifest(
    tmp_path: Path, table: str
) -> None:
    manifests = tmp_path / "manifests"
    manifests.mkdir()
    _write_pin(
        manifests / ("mkvtoolnix.toml" if table == "builds.default" else "bundled.toml"), table
    )
    tools = tmp_path / "tools"
    _layout(tools, "mkvtoolnix", licence="COPYING")

    [entry] = tpn.tool_entries(tools, manifests, "windows-x64")

    assert (entry.name, entry.version, entry.license) == ("mkvtoolnix", "103.0", "GPL-2.0-only")
    assert "source_url: https://mkvtoolnix.download/sources/mkvtoolnix-103.0.tar.xz" in entry.text
    assert "windows-x64.url: https://mkvtoolnix.download/windows/" in entry.text
    assert entry.text.endswith("mkvtoolnix licence text")


def test_the_windows_tools_get_their_pins_from_the_repositorys_manifest(tmp_path: Path) -> None:
    tools = tmp_path / "tools"
    (tools / "mkvtoolnix" / "doc").mkdir(parents=True)
    (tools / "mkvtoolnix" / "doc" / "COPYING.txt").write_text("GPL-2.0 text")
    (tools / "mediainfo").mkdir()
    (tools / "mediainfo" / "LICENSE").write_text("BSD-2-Clause text")
    manifest = tpn.tomllib.loads((REPO_ROOT / "tools" / "bundled-tools.toml").read_text())

    entries = tpn.tool_entries(tools, REPO_ROOT / "tools", "windows-x64")

    assert [entry.name for entry in entries] == ["mediainfo", "mkvtoolnix"]
    for entry in entries:
        pin = manifest["tools"][entry.name]
        assert (entry.version, entry.license) == (pin["version"], pin["license"])
        for value in (
            pin["source_url"],
            pin["source_tag"],
            pin["platforms"]["windows-x64"]["sha256"],
        ):
            assert value in entry.text
    assert entries[1].text.endswith("GPL-2.0 text")


def test_a_bundled_tool_without_a_pin_is_an_error(tmp_path: Path) -> None:
    manifests = tmp_path / "manifests"
    manifests.mkdir()
    shutil.copy(REPO_ROOT / "tools" / "ffmpeg.toml", manifests)
    tools = tmp_path / "tools"
    _layout(tools, "ffmpeg")
    _layout(tools, "mediainfo")

    with pytest.raises(tpn.NoticesError, match="mediainfo is bundled but no manifest"):
        tpn.tool_entries(tools, manifests, "linux-x64")


def test_a_bundled_tool_without_a_licence_file_is_an_error(tmp_path: Path) -> None:
    tools = tmp_path / "tools"
    (tools / "ffmpeg" / "bin").mkdir(parents=True)

    with pytest.raises(tpn.NoticesError, match="has no licence file"):
        tpn.tool_entries(tools, REPO_ROOT / "tools", "linux-x64")


def test_no_tools_folder_gives_no_tool_entries(tmp_path: Path) -> None:
    assert tpn.tool_entries(tmp_path / "missing", REPO_ROOT / "tools", "linux-x64") == []


def test_the_mediainfo_library_licence_is_read_for_the_bundled_version(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from pymediainfo import MediaInfo

    (tmp_path / "_internal" / "pymediainfo").mkdir(parents=True)
    (tmp_path / "_internal" / "pymediainfo" / "libmediainfo.so.0").write_bytes(b"")
    requested: list[str] = []

    class Response:
        def __enter__(self) -> Response:
            return self

        def __exit__(self, *args: object) -> None:
            pass

        def read(self) -> bytes:
            return b"BSD 2-Clause License"

    def urlopen(request: Any, timeout: float) -> Response:
        requested.append(request.full_url)
        return Response()

    monkeypatch.setattr(tpn.urllib.request, "urlopen", urlopen)

    [entry] = tpn.mediainfo_library_entry(tmp_path)

    version = MediaInfo._get_library()[2]
    assert requested == [
        f"https://raw.githubusercontent.com/MediaArea/MediaInfoLib/v{version}/LICENSE"
    ]
    assert (entry.version, entry.text) == (version, "BSD 2-Clause License")


def test_no_mediainfo_library_in_the_sidecar_needs_no_notice(tmp_path: Path) -> None:
    (tmp_path / "_internal").mkdir()

    assert tpn.mediainfo_library_entry(tmp_path) == []


def test_every_entry_and_its_text_are_written() -> None:
    sections = [
        ("Bundled tools", [tpn.Entry("ffmpeg", "n9.0", "GPL-3.0-or-later", "https://x", "GPL")]),
        ("Rust crates", [tpn.Entry("MIT License", "", "MIT", text="Used by: a 1\n\nMIT")]),
    ]

    text = tpn.render(sections, version="0.1.0", platform="linux-x64")

    for line in (
        "Third-party notices for Reframe 0.1.0 (linux-x64)",
        "Bundled tools",
        "ffmpeg n9.0",
        "Licence: GPL-3.0-or-later",
        "URL: https://x",
        "Rust crates",
        "MIT License",
        "Used by: a 1",
    ):
        assert line in text.splitlines()


def test_the_header_names_the_packages_version(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    for name in ("shipped_top_level_names", "shipped_distributions", "python_entries"):
        monkeypatch.setattr(tpn, name, lambda *args: [])
    for name in ("mediainfo_library_entry", "javascript_entries", "rust_entries"):
        monkeypatch.setattr(tpn, name, lambda *args: [])
    monkeypatch.setattr(tpn, "python_interpreter_entry", lambda: tpn.Entry("Python", "3", "PSF"))
    monkeypatch.setattr(tpn, "DEFAULT_TOOLS", tmp_path / "no-tools")
    out = tmp_path / "THIRD_PARTY_NOTICES"

    assert tpn.main(["--platform", "linux-x64", "--out", str(out)]) == 0

    config = json.loads((REPO_ROOT / "desktop" / "src-tauri" / "tauri.conf.json").read_text())
    header = out.read_text().splitlines()[0]
    assert header == f"Third-party notices for Reframe {config['version']} (linux-x64)"


def test_the_notices_ship_in_every_desktop_package() -> None:
    config = json.loads((REPO_ROOT / "desktop" / "src-tauri" / "tauri.conf.json").read_text())

    assert config["bundle"]["resources"]["resources/notices/"] == "notices/"
    assert tpn.DEFAULT_OUT.parent == REPO_ROOT / "desktop" / "src-tauri" / "resources" / "notices"


ALL_FFMPEG = ["linux-arm64", "linux-x64", "windows-x64"]
#: A small source manifest: archive name → (kind, platforms), one of each kind of entry that
#: decides which package bundles it.
MANIFEST = {
    "ffmpeg-2a571b606854.tar.xz": ("git", ALL_FFMPEG),
    "ffmpeg-builds-6c9aec5d1a2b.tar.xz": ("git", ALL_FFMPEG),
    "btbn-x264-0123456789ab.tar.xz": ("btbn-stage", ALL_FFMPEG),
    "btbn-davs2-0123456789ab.tar.xz": ("btbn-stage", ["linux-x64"]),
    "btbn-mingw-0123456789ab.tar.xz": ("btbn-stage", ["windows-x64"]),
    "btbn-armonly-0123456789ab.tar.xz": ("btbn-stage", ["linux-arm64"]),
    "mkvtoolnix-103.0.tar.xz": ("url", ["windows-x64"]),
    "MediaInfo_CLI_26.10_GNU_FromSource.tar.xz": ("url", ["windows-x64"]),
    "libva-2.24.1.tar.bz2": ("url", ["linux-x64"]),
    "ubuntu-gtk_3.0_3.24.33-1ubuntu2.2.tar": ("ubuntu-source", ["linux-x64"]),
}
EVERY_PLATFORM = ["ffmpeg-2a571b606854.tar.xz", "ffmpeg-builds-6c9aec5d1a2b.tar.xz"]
EVERY_PLATFORM += ["btbn-x264-0123456789ab.tar.xz"]
BUNDLED = {
    "linux-x64": [
        *EVERY_PLATFORM,
        "btbn-davs2-0123456789ab.tar.xz",
        "libva-2.24.1.tar.bz2",
        "ubuntu-gtk_3.0_3.24.33-1ubuntu2.2.tar",
    ],
    "windows-x64": [
        *EVERY_PLATFORM,
        "btbn-mingw-0123456789ab.tar.xz",
        "mkvtoolnix-103.0.tar.xz",
        "MediaInfo_CLI_26.10_GNU_FromSource.tar.xz",
    ],
    "docker-linux-x64": [*EVERY_PLATFORM, "btbn-davs2-0123456789ab.tar.xz"],
    "docker-linux-arm64": [*EVERY_PLATFORM, "btbn-armonly-0123456789ab.tar.xz"],
}
SOURCES_URL = "https://github.com/owner/reframe/releases/tag/sources-0123456789ab"


def _checksum(archive: str) -> str:
    return hashlib.sha256(archive.encode()).hexdigest()


def _sources(
    folder: Path, manifest: Mapping[str, tuple[str, list[str]]] = MANIFEST, sums: str = ""
) -> list[str]:
    """The ``--sources-*`` options for ``manifest`` and its sums (by default one line each)."""
    entries = [
        {"archive": name, "kind": kind, "name": name, "platforms": platforms}
        for name, (kind, platforms) in sorted(manifest.items())
    ]
    path = folder / "manifest.json"
    path.write_text(json.dumps({"schema_version": 1, "entries": entries}))
    if not sums:
        sums = "".join(f"{_checksum(name)}  {name}\n" for name in sorted(manifest))
    (folder / "SHA256SUMS").write_text(sums)
    return [
        "--sources-url",
        SOURCES_URL,
        "--sources-sums",
        str(folder / "SHA256SUMS"),
        "--sources-manifest",
        str(path),
    ]


@pytest.fixture
def no_sections(monkeypatch: pytest.MonkeyPatch) -> None:
    entry = tpn.Entry("ffmpeg", "n9.0", "GPL-3.0-or-later")
    monkeypatch.setattr(tpn, "docker_sections", lambda *args: [("Bundled tools", [entry])])
    monkeypatch.setattr(tpn, "desktop_sections", lambda *args: [("Bundled tools", [entry])])


def _listed_archives(text: str) -> list[str]:
    return [line.split()[1] for line in text.splitlines() if re.match(r"^  [0-9a-f]{64}  ", line)]


@pytest.mark.usefixtures("no_sections")
@pytest.mark.parametrize("platform", sorted(BUNDLED))
def test_the_notices_list_only_the_archives_that_the_platform_bundles(
    tmp_path: Path, platform: str
) -> None:
    out = tmp_path / "THIRD_PARTY_NOTICES"

    code = tpn.main(["--platform", platform, "--out", str(out), *_sources(tmp_path)])

    assert code == 0
    text = out.read_text()
    assert f"  {SOURCES_URL}" in text.splitlines()
    assert sorted(_listed_archives(text)) == sorted(BUNDLED[platform])
    for name in BUNDLED[platform]:
        assert f"  {_checksum(name)}  {name}" in text.splitlines()


@pytest.mark.parametrize(
    ("archive", "platforms"),
    [
        ("mkvtoolnix-103.0.tar.xz", {"windows-x64"}),
        ("ubuntu-gtk_3.0_3.24.33-1ubuntu2.2.tar", {"linux-x64"}),
        ("libva-2.24.1.tar.bz2", {"linux-x64"}),
        ("btbn-armonly-0123456789ab.tar.xz", {"docker-linux-arm64"}),
        ("btbn-mingw-0123456789ab.tar.xz", {"windows-x64"}),
        ("ffmpeg-2a571b606854.tar.xz", set(BUNDLED)),
    ],
)
def test_each_kind_of_source_goes_to_the_packages_that_bundle_it(
    archive: str, platforms: set[str]
) -> None:
    kind, ffmpeg_platforms = MANIFEST[archive]
    entry = {"archive": archive, "kind": kind, "platforms": ffmpeg_platforms}

    assert {p for p in BUNDLED if tpn.bundles(entry, p)} == platforms


def test_the_platforms_with_notices_all_have_a_sources_selection() -> None:
    assert set(BUNDLED) == {*tpn.RUST_TARGETS, *tpn.DOCKER_PLATFORMS}


def test_an_unknown_kind_of_source_is_an_error() -> None:
    with pytest.raises(tpn.NoticesError, match="unknown source kind"):
        tpn.bundles({"archive": "x.tar", "kind": "svn", "platforms": ["linux-x64"]}, "linux-x64")


@pytest.mark.usefixtures("no_sections")
def test_an_archive_in_the_sums_that_no_manifest_entry_names_is_an_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    sums = "".join(f"{_checksum(n)}  {n}\n" for n in [*MANIFEST, "btbn-stray-0123.tar.xz"])
    out = tmp_path / "THIRD_PARTY_NOTICES"

    code = tpn.main(["--platform", "linux-x64", "--out", str(out), *_sources(tmp_path, sums=sums)])

    assert code == 1
    assert "btbn-stray-0123.tar.xz" in capsys.readouterr().err
    assert not out.exists()


@pytest.mark.usefixtures("no_sections")
def test_a_bundled_archive_missing_from_the_sums_is_an_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    sums = "".join(f"{_checksum(n)}  {n}\n" for n in MANIFEST if not n.startswith("libva"))
    out = tmp_path / "THIRD_PARTY_NOTICES"

    code = tpn.main(["--platform", "linux-x64", "--out", str(out), *_sources(tmp_path, sums=sums)])

    assert code == 1
    assert "the sums have no line for libva-2.24.1.tar.bz2" in capsys.readouterr().err
    assert not out.exists()


@pytest.mark.usefixtures("no_sections")
def test_another_platforms_archive_missing_from_the_sums_is_not_this_ones_concern(
    tmp_path: Path,
) -> None:
    sums = "".join(f"{_checksum(n)}  {n}\n" for n in MANIFEST if not n.startswith("libva"))
    out = tmp_path / "THIRD_PARTY_NOTICES"

    code = tpn.main(
        ["--platform", "windows-x64", "--out", str(out), *_sources(tmp_path, sums=sums)]
    )

    assert code == 0


@pytest.mark.usefixtures("no_sections")
def test_a_manifest_without_the_platforms_ffmpeg_is_an_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    manifest = {
        name: (kind, [p for p in platforms if p != "linux-arm64"])
        for name, (kind, platforms) in MANIFEST.items()
        if platforms != ["linux-arm64"]
    }
    out = tmp_path / "THIRD_PARTY_NOTICES"
    options = _sources(tmp_path, manifest)

    code = tpn.main(["--platform", "docker-linux-arm64", "--out", str(out), *options])

    assert code == 1
    assert "no source of docker-linux-arm64" in capsys.readouterr().err


@pytest.mark.parametrize(
    "content",
    [
        "not json",
        '{"schema_version": 2, "entries": [{"archive": "a.tar", "platforms": []}]}',
        '{"schema_version": 1, "entries": []}',
        '{"schema_version": 1, "entries": [{"archive": "a.tar"}]}',
        "[]",
    ],
)
def test_a_file_that_is_not_a_source_manifest_is_an_error(tmp_path: Path, content: str) -> None:
    path = tmp_path / "manifest.json"
    path.write_text(content)

    with pytest.raises(tpn.NoticesError):
        tpn.read_sources_manifest(path)


@pytest.mark.parametrize("given", [[0], [1], [2], [0, 1], [0, 2], [1, 2]])
def test_the_sources_options_are_given_all_three_or_none(tmp_path: Path, given: list[int]) -> None:
    options = _sources(tmp_path)
    pairs = [options[i : i + 2] for i in range(0, 6, 2)]
    partial = [word for i in given for word in pairs[i]]

    with pytest.raises(SystemExit) as exit_info:
        tpn.main(["--platform", "linux-x64", "--out", str(tmp_path / "N"), *partial])

    assert exit_info.value.code == 2


@pytest.mark.parametrize("content", ["", "abc  file.tar\n", f"{'a' * 64}  ../file.tar\n"])
def test_a_sums_file_that_is_not_sha256sums_output_is_an_error(
    tmp_path: Path, content: str
) -> None:
    sums = tmp_path / "SHA256SUMS"
    sums.write_text(content)

    with pytest.raises(tpn.NoticesError):
        tpn.read_sources_sums(sums)


@pytest.mark.usefixtures("no_sections")
def test_the_sources_release_comes_before_the_entries_in_the_written_file(tmp_path: Path) -> None:
    out = tmp_path / "THIRD_PARTY_NOTICES"

    code = tpn.main(["--platform", "docker-linux-arm64", "--out", str(out), *_sources(tmp_path)])

    assert code == 0
    text = out.read_text()
    assert text.splitlines()[0].endswith("(docker-linux-arm64)")
    assert text.index(SOURCES_URL) < text.index("Debian packages") < text.index("ffmpeg n9.0")


EXPORT = """\
annotated-types==0.8.0
colorama==0.4.6 ; sys_platform == 'win32'
fastapi==0.159.1
reframe-server==0.1.0
uvloop==0.21.0 ; platform_machine == 'x86_64'
Typing_Extensions==4.16.0
"""


@pytest.mark.parametrize(("machine", "extra"), [("x86_64", ["uvloop"]), ("aarch64", [])])
def test_the_images_python_packages_are_those_its_platform_installs(
    machine: str, extra: list[str]
) -> None:
    assert tpn.parse_uv_export(EXPORT, machine) == sorted(
        ["annotated-types", "fastapi", "typing-extensions", *extra]
    )


def test_the_export_selects_the_packages_the_images_uv_sync_installs() -> None:
    syncs = [line.split() for line in tpn.DOCKERFILE.read_text().splitlines() if "uv sync" in line]

    assert syncs
    for words in syncs:
        selection = [w for w in words if w in {"--frozen", "--no-dev", "--all-packages"}]
        extras = [arg for i, w in enumerate(words) if w == "--extra" for arg in (w, words[i + 1])]
        assert not {"--group", "--all-extras", "--only-group", "--dev"} & set(words)
        assert (*selection, *extras) == tpn.DOCKER_EXPORT


def test_the_image_notices_refuse_another_python_than_the_images(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(tpn.host_platform, "python_version", lambda: "3.13.0")

    with pytest.raises(tpn.NoticesError, match=r"uv run --python 3\.\d+\.\d+"):
        tpn.docker_sections("docker-linux-x64", tmp_path)


@pytest.mark.parametrize(
    ("platform", "other"),
    [("docker-linux-x64", "linux-arm64"), ("docker-linux-arm64", "linux-x64")],
)
def test_the_images_ffmpeg_gets_the_pin_of_its_platform_without_the_desktop_libva(
    tmp_path: Path, platform: str, other: str
) -> None:
    manifests = tmp_path / "manifests"
    manifests.mkdir()
    pin = (REPO_ROOT / "tools" / "ffmpeg.toml").read_text()
    if "platforms.linux-arm64]" not in pin:
        arm64 = "https://example.invalid/ffmpeg-n9.0.2-linuxarm64-gpl-shared-9.0.tar.xz"
        pin += f'\n[builds.default.platforms.linux-arm64]\nurl = "{arm64}"\n'
    (manifests / "ffmpeg.toml").write_text(pin)
    shutil.copy(REPO_ROOT / "tools" / "bundled-tools.toml", manifests)
    tools = tmp_path / "tools"
    _layout(tools, "ffmpeg")
    ffmpeg_platform = tpn.DOCKER_PLATFORMS[platform][0]

    [entry] = tpn.tool_entries(tools, manifests, ffmpeg_platform, libraries=False)

    assert f"{ffmpeg_platform}.url: " in entry.text
    assert f"{other}.url" not in entry.text
