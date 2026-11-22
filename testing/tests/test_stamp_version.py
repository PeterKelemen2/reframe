"""scripts/stamp-version.py: one version source, stamped into every package's version field."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path
from typing import Any

import pytest

from reframe_testing.scripts import load_script

REPO_ROOT = Path(__file__).resolve().parents[2]
TAURI = REPO_ROOT / "desktop" / "node_modules" / ".bin" / "tauri"
NODE_SEMVER = REPO_ROOT / "frontend" / "node_modules" / "semver"


sv = load_script("stamp-version.py")

FILES = sorted({sv.CORE_INIT, *(field.path for field in sv.FIELDS)})


@pytest.fixture
def tree(tmp_path: Path) -> Path:
    """A copy of the files that hold a version."""
    for path in FILES:
        (tmp_path / path).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(REPO_ROOT / path, tmp_path / path)
    return tmp_path


def _run(root: Path, *args: str) -> int:
    code: int = sv.main([*args, "--root", str(root)])
    return code


def _changed_lines(before: bytes, after: bytes) -> list[tuple[str, str]]:
    old, new = before.decode().splitlines(), after.decode().splitlines()
    assert len(old) == len(new)
    return [(a, b) for a, b in zip(old, new, strict=True) if a != b]


def test_the_committed_version_fields_agree(capsys: pytest.CaptureFixture[str]) -> None:
    assert sv.main(["--check"]) == 0
    assert capsys.readouterr().out.strip() == sv.read_core_version(REPO_ROOT)


def test_the_server_takes_its_version_from_the_cores_file() -> None:
    server = REPO_ROOT / "packages" / "reframe-server"
    hatch = tomllib.loads((server / "pyproject.toml").read_text())["tool"]["hatch"]["version"]

    assert (server / hatch["path"]).resolve() == (REPO_ROOT / sv.CORE_INIT).resolve()
    assert "__version__ =" not in (server / "src" / "reframe_server" / "__init__.py").read_text()


def test_set_writes_the_version_and_its_semver_spelling_into_every_field(
    tree: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    before = {path: (tree / path).read_bytes() for path in FILES}

    assert _run(tree, "--set", "1.2.0rc3") == 0

    assert capsys.readouterr().out.strip() == "1.2.0rc3"
    assert sv.read_core_version(tree) == "1.2.0rc3"
    assert {field.label: sv.read_field(tree, field) for field in sv.FIELDS} == {
        field.label: "1.2.0-rc.3" for field in sv.FIELDS
    }
    # Each file differs only in its version lines, so a stamp commit is easy to review.
    for path in FILES:
        changed = _changed_lines(before[path], (tree / path).read_bytes())
        fields = sum(field.path == path for field in sv.FIELDS) or 1
        assert len(changed) == fields, path
        assert all(
            re.sub(r"[\d.a-z-]+", "V", a) == re.sub(r"[\d.a-z-]+", "V", b) for a, b in changed
        )
    assert _run(tree, "--check") == 0


def test_check_names_each_field_that_differs_and_changes_nothing(
    tree: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _run(tree, "--set", "2.0.0")
    conf = tree / "desktop/src-tauri/tauri.conf.json"
    conf.write_text(conf.read_text().replace('"version": "2.0.0"', '"version": "1.9.0"'))
    lock = tree / "desktop/src-tauri/Cargo.lock"
    lock.write_text(
        lock.read_text().replace(
            'name = "reframe-desktop"\nversion = "2.0.0"',
            'name = "reframe-desktop"\nversion = "2.0.1"',
        )
    )
    capsys.readouterr()
    before = {path: (tree / path).read_bytes() for path in FILES}

    assert _run(tree, "--check") == 1

    err = capsys.readouterr().err
    assert "desktop/src-tauri/tauri.conf.json: version is '1.9.0', expected '2.0.0'" in err
    assert "desktop/src-tauri/Cargo.lock: package \"reframe-desktop\" version is '2.0.1'" in err
    assert len([line for line in err.splitlines() if line.startswith("  ")]) == 2
    assert {path: (tree / path).read_bytes() for path in FILES} == before


def test_only_the_apps_entry_in_cargo_lock_changes(tree: Path) -> None:
    lock = tree / "desktop/src-tauri/Cargo.lock"
    current = sv.read_field(tree, next(f for f in sv.FIELDS if f.path.name == "Cargo.lock"))
    # A registry crate with the app's version, before the app's entry.
    lock.write_text(
        lock.read_text().replace(
            '[[package]]\nname = "reframe-desktop"',
            f'[[package]]\nname = "aaa-same-version"\nversion = "{current}"\n'
            'source = "registry+https://github.com/rust-lang/crates.io-index"\n\n'
            '[[package]]\nname = "reframe-desktop"',
        )
    )

    _run(tree, "--set", "3.1.4")

    packages = {p["name"]: p["version"] for p in tomllib.loads(lock.read_text())["package"]}
    assert (packages["aaa-same-version"], packages["reframe-desktop"]) == (current, "3.1.4")


def test_a_crlf_checkout_keeps_its_line_ends(tree: Path) -> None:
    for path in FILES:
        file = tree / path
        file.write_bytes(file.read_bytes().replace(b"\n", b"\r\n"))

    _run(tree, "--set", "1.0.0")

    for path in FILES:
        data = (tree / path).read_bytes()
        assert data.count(b"\n") == data.count(b"\r\n"), path
    assert _run(tree, "--check") == 0


@pytest.mark.parametrize(
    ("version", "semver"),
    [
        ("1.0.0", "1.0.0"),
        ("1.1.0a2", "1.1.0-alpha.2"),
        ("1.1.0b1", "1.1.0-beta.1"),
        ("1.1.0rc1", "1.1.0-rc.1"),
        ("0.1.0.dev0", "0.1.0-dev.0"),
        ("10.20.30rc40", "10.20.30-rc.40"),
    ],
)
def test_the_semver_spelling(version: str, semver: str) -> None:
    assert sv.to_semver(version) == semver


@pytest.mark.parametrize(
    "version",
    [
        "1.1",
        "1.1.0.post1",
        "1.1.0-rc1",
        "1.1.0rc1.dev2",
        "01.1.0",
        "1.1.0rc01",
        "1.1.0+local",
        "v1.1.0",
        "",
        "1.1.0\n",
        "\u0661.1.0",
        "1.1.0rc\u0663",
    ],
)
def test_set_refuses_a_version_it_cannot_spell_in_order_and_writes_nothing(
    tree: Path, version: str, capsys: pytest.CaptureFixture[str]
) -> None:
    before = {path: (tree / path).read_bytes() for path in FILES}

    assert _run(tree, "--set", version) == 2

    assert "stamp-version:" in capsys.readouterr().err
    assert {path: (tree / path).read_bytes() for path in FILES} == before


def test_print_semver_prints_the_spelling_and_writes_nothing(
    tree: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    sv.write_core_version(tree, "4.0.0b2")
    before = {path: (tree / path).read_bytes() for path in FILES}

    assert _run(tree, "--print-semver") == 0

    assert capsys.readouterr().out.strip() == "4.0.0-beta.2"
    assert {path: (tree / path).read_bytes() for path in FILES} == before


@pytest.mark.skipif(not NODE_SEMVER.is_dir(), reason="no frontend/node_modules: run npm ci")
def test_npm_semver_orders_the_spellings_as_pep_440_does() -> None:
    # The updater and npm compare SemVer: an rc must sort before its release, rc2 before rc10.
    ordered = ["1.0.0a1", "1.0.0a2", "1.0.0b1", "1.0.0rc2", "1.0.0rc10", "1.0.0", "1.0.1", "1.10.0"]
    spellings = [sv.to_semver(v) for v in reversed(ordered)]
    script = (
        "const s = require(process.argv[1]);"
        "const v = JSON.parse(process.argv[2]);"
        "console.log(JSON.stringify(v.map(x => s.valid(x)).every(Boolean) ? s.sort(v) : null))"
    )
    result = subprocess.run(
        ["node", "-e", script, str(NODE_SEMVER), json.dumps(spellings)],
        capture_output=True,
        text=True,
        check=True,
    )

    assert json.loads(result.stdout) == [sv.to_semver(v) for v in ordered]


def _semver_tree(tmp_path: Path, version: str) -> Path:
    for name in ("tauri.conf.json", "Cargo.toml"):
        shutil.copyfile(REPO_ROOT / "desktop/src-tauri" / name, tmp_path / name)
    (tmp_path / "src").mkdir(exist_ok=True)
    (tmp_path / "src/main.rs").write_text("fn main() {}\n")
    conf = tmp_path / "tauri.conf.json"
    data: dict[str, Any] = json.loads(conf.read_text())
    data["version"] = version
    conf.write_text(json.dumps(data))
    cargo = tmp_path / "Cargo.toml"
    cargo.write_text(
        re.sub(r'(?m)^version = ".*"$', f'version = "{version}"', cargo.read_text(), count=1)
    )
    return tmp_path


@pytest.mark.skipif(shutil.which("cargo") is None, reason="no cargo")
@pytest.mark.parametrize("version", ["1.1.0rc1", "1.1.0", "0.1.0.dev0"])
def test_cargo_takes_the_semver_spelling_and_refuses_the_pep_440_one(
    tmp_path: Path, version: str
) -> None:
    def metadata(spelling: str) -> subprocess.CompletedProcess[str]:
        _semver_tree(tmp_path, spelling)
        return subprocess.run(
            ["cargo", "metadata", "--no-deps", "--offline", "--format-version", "1"],
            cwd=tmp_path,
            capture_output=True,
            text=True,
        )

    taken = metadata(sv.to_semver(version))
    assert taken.returncode == 0, taken.stderr
    assert json.loads(taken.stdout)["packages"][0]["version"] == sv.to_semver(version)
    if sv.to_semver(version) != version:
        assert metadata(version).returncode != 0


@pytest.mark.skipif(
    sys.platform == "win32" or not TAURI.is_file(),
    reason="no desktop/node_modules (npm ci in desktop/); the .bin entry is a shell script",
)
def test_the_tauri_cli_takes_the_semver_spelling_and_refuses_the_pep_440_one(
    tmp_path: Path,
) -> None:
    def inspect(spelling: str) -> subprocess.CompletedProcess[str]:
        project = tmp_path / spelling
        (project / "src-tauri").mkdir(parents=True)
        _semver_tree(project / "src-tauri", spelling)
        return subprocess.run(
            [str(TAURI), "inspect", "wix-upgrade-code"],
            cwd=project,
            capture_output=True,
            text=True,
            env={**os.environ, "NO_COLOR": "1"},
            timeout=120,
        )

    assert inspect(sv.to_semver("1.1.0rc1")).returncode == 0
    refused = inspect("1.1.0rc1")
    assert refused.returncode != 0
    assert "must be a semver string" in refused.stdout + refused.stderr
