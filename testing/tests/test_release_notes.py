"""The changelog: cliff.toml with the pinned git-cliff, CHANGELOG.md, scripts/release-notes.py."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

from reframe_testing.scripts import load_script

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "release-notes.py"
CLIFF_TOML = REPO_ROOT / "cliff.toml"
CHANGELOG = REPO_ROOT / "CHANGELOG.md"


rn = load_script("release-notes.py")

SAMPLE = """# Changelog

Intro.

## [Unreleased]

## [1.1.0rc1] - 2026-12-01

### Fixed

- F-17: the queue keeps its order

## [1.0.0] - 2026-11-20

### Added

- Q-5: one version source
- F-19: the Range selector

### Fixed

- S-3: the token check

## [0.9.0] - 2026-01-01

### Added

- the first release
"""


def _notes(tmp_path: Path, version: str, text: str = SAMPLE) -> tuple[int, str, str]:
    changelog = tmp_path / "CHANGELOG.md"
    changelog.write_text(text, encoding="utf-8")
    result = subprocess.run(
        [sys.executable, str(SCRIPT), version, "--changelog", str(changelog)],
        capture_output=True,
        text=True,
    )
    return result.returncode, result.stdout, result.stderr


def test_prints_the_versions_section_without_its_heading_up_to_the_next_one(
    tmp_path: Path,
) -> None:
    assert _notes(tmp_path, "1.0.0") == (
        0,
        "### Added\n\n- Q-5: one version source\n- F-19: the Range selector\n\n"
        "### Fixed\n\n- S-3: the token check\n",
        "",
    )


def test_the_tags_spelling_finds_the_section(tmp_path: Path) -> None:
    code, out, _ = _notes(tmp_path, "v1.1.0rc1")

    assert (code, out) == (0, "### Fixed\n\n- F-17: the queue keeps its order\n")


@pytest.mark.parametrize(
    ("version", "says"),
    [("1.0.1", "no section for 1.0.1"), ("1.0", "no section"), ("Unreleased", "an empty section")],
)
def test_a_missing_or_empty_section_exits_1(tmp_path: Path, version: str, says: str) -> None:
    code, out, err = _notes(tmp_path, version)

    assert (code, out) == (1, "")
    assert says in err


def test_the_committed_changelog_has_no_release_section_yet() -> None:
    # The frame's note on the first release's heading must not read as a section.
    headings = re.findall(r"(?m)^## .*", CHANGELOG.read_text(encoding="utf-8"))

    assert headings == ["## [Unreleased]"]
    assert rn.section(CHANGELOG.read_text(encoding="utf-8"), "VERSION") is None


def _header() -> str:
    header: str = tomllib.loads(CLIFF_TOML.read_text(encoding="utf-8"))["changelog"]["header"]
    return header


def test_the_changelog_starts_with_the_header_git_cliff_replaces_on_prepend() -> None:
    # Otherwise each prepend writes a second title and a second Unreleased heading.
    assert _header().endswith("## [Unreleased]\n\n")
    assert CHANGELOG.read_text(encoding="utf-8").startswith(_header())


def _git_cliff() -> list[str]:
    pin = re.search(r"uv tool run (git-cliff==\S+)", CLIFF_TOML.read_text(encoding="utf-8"))
    assert pin is not None, "cliff.toml names the pinned git-cliff"
    uv = shutil.which("uv")
    assert uv is not None
    return [uv, "tool", "run", pin.group(1)]


def _commit(repo: Path, message: str) -> None:
    with (repo / "file").open("a") as file:
        file.write(message)
    subprocess.run(["git", "add", "file"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", message], cwd=repo, check=True)


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    for name, value in {
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_AUTHOR_NAME": "T",
        "GIT_AUTHOR_EMAIL": "t@example.invalid",
        "GIT_COMMITTER_NAME": "T",
        "GIT_COMMITTER_EMAIL": "t@example.invalid",
        "NO_COLOR": "1",
    }.items():
        monkeypatch.setenv(name, value)
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)
    shutil.copyfile(CLIFF_TOML, repo / "cliff.toml")
    # The first release's section, written by hand in place of the frame's note.
    (repo / "CHANGELOG.md").write_text(
        _header() + "## [0.9.0] - 2026-01-01\n\n### Added\n\n- written by hand\n",
        encoding="utf-8",
        newline="\n",
    )
    subprocess.run(["git", "add", "cliff.toml", "CHANGELOG.md"], cwd=repo, check=True)
    _commit(repo, "F-1: a commit in the older style")
    subprocess.run(["git", "tag", "v0.9.0"], cwd=repo, check=True)
    for message in [
        "feat(Q-5): one version source",
        "fix(F-17): the queue keeps its order",
        "perf(C-6): a faster probe",
        "docs(status): Q-5 done",
        "test(Q-5): stamp tests",
        "ci(Q-5): check the versions",
        "chore: tidy",
        "build(Q-5): pin git-cliff",
        "refactor(C-1): split a module",
        'revert: "feat(Q-5): one version source"',
        "feat(S-2)!: the API drops /api/old",
        "fix(S-3): the token check\n\nBREAKING CHANGE: every route needs the token",
        "Q-5: not a conventional commit",
        "feat: a change without a scope",
    ]:
        _commit(repo, message)
        if message.startswith("docs(status)"):
            # A sources release's tag: not a version, so no section may end at it.
            subprocess.run(["git", "tag", "sources-0123456789ab"], cwd=repo, check=True)
    subprocess.run(["git", "checkout", "-q", "-b", "side"], cwd=repo, check=True)
    _commit(repo, "fix(F-2): made on a branch")
    subprocess.run(["git", "checkout", "-q", "main"], cwd=repo, check=True)
    subprocess.run(
        ["git", "merge", "-q", "--no-ff", "side", "-m", "Merge branch 'side'"], cwd=repo, check=True
    )
    return repo


RELEASE_1_0_0 = """\
### Breaking

- S-2: the API drops /api/old
- S-3: every route needs the token

### Added

- Q-5: one version source
- a change without a scope

### Fixed

- F-17: the queue keeps its order
- F-2: made on a branch

### Performance

- C-6: a faster probe
"""


@pytest.mark.skipif(shutil.which("git") is None or shutil.which("uv") is None, reason="no git/uv")
def test_git_cliff_groups_the_commits_since_the_last_tag_and_prepends_each_release(
    repo: Path,
) -> None:
    def prepend(tag: str) -> None:
        subprocess.run(
            [*_git_cliff(), "--unreleased", "--tag", tag, "--prepend", "CHANGELOG.md"],
            cwd=repo,
            check=True,
            capture_output=True,
            timeout=300,
        )

    prepend("v1.0.0")
    subprocess.run(["git", "commit", "-q", "-am", "docs(changelog): 1.0.0"], cwd=repo, check=True)
    subprocess.run(["git", "tag", "v1.0.0"], cwd=repo, check=True)
    _commit(repo, "fix(F-9): made after the tag")
    prepend("v1.0.1")

    text = (repo / "CHANGELOG.md").read_text(encoding="utf-8")
    assert text.startswith(_header())
    assert text.count("# Changelog") == 1
    headings = re.findall(r"(?m)^## .*", text)
    assert [re.sub(r"- \d{4}-\d{2}-\d{2}$", "- DATE", h) for h in headings] == [
        "## [Unreleased]",
        "## [1.0.1] - DATE",
        "## [1.0.0] - DATE",
        "## [0.9.0] - DATE",
    ]
    assert rn.section(text, "1.0.0") + "\n" == RELEASE_1_0_0
    assert rn.section(text, "1.0.1") == "### Fixed\n\n- F-9: made after the tag"
    assert rn.section(text, "0.9.0") == "### Added\n\n- written by hand"
