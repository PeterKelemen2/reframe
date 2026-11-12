"""scripts/third-party-notices.py: which components get a notice, and what each notice says."""

from __future__ import annotations

import importlib.util
import json
import shutil
import sys
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
    manifests = REPO_ROOT / "tools"

    [entry] = tpn.tool_entries(tools, manifests, "linux-x64")

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


def _write_pin(path: Path, table: str = "") -> None:
    prefix = f"{table}." if table else ""
    path.write_text(
        f"[{prefix}builds.default]\n"
        'version = "103.0"\nlicense = "GPL-2.0-only"\nlicense_file = "COPYING"\n'
        'source_url = "https://mkvtoolnix.download/sources/mkvtoolnix-103.0.tar.xz"\n'
        f"[{prefix}builds.default.platforms.windows-x64]\n"
        'url = "https://mkvtoolnix.download/windows/mkvtoolnix-64-bit-103.0.7z"\n'
    )


@pytest.mark.parametrize("table", ["", "mkvtoolnix"])
def test_another_tools_pin_is_found_in_its_own_or_a_shared_manifest(
    tmp_path: Path, table: str
) -> None:
    manifests = tmp_path / "manifests"
    manifests.mkdir()
    _write_pin(manifests / ("mkvtoolnix.toml" if not table else "bundled.toml"), table)
    tools = tmp_path / "tools"
    _layout(tools, "mkvtoolnix", licence="COPYING")

    [entry] = tpn.tool_entries(tools, manifests, "windows-x64")

    assert (entry.name, entry.version, entry.license) == ("mkvtoolnix", "103.0", "GPL-2.0-only")
    assert "source_url: https://mkvtoolnix.download/sources/mkvtoolnix-103.0.tar.xz" in entry.text
    assert "windows-x64.url: https://mkvtoolnix.download/windows/" in entry.text
    assert entry.text.endswith("mkvtoolnix licence text")


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


def test_the_notices_ship_in_every_desktop_package() -> None:
    config = json.loads((REPO_ROOT / "desktop" / "src-tauri" / "tauri.conf.json").read_text())

    assert config["bundle"]["resources"]["resources/notices/"] == "notices/"
    assert tpn.DEFAULT_OUT.parent == REPO_ROOT / "desktop" / "src-tauri" / "resources" / "notices"
