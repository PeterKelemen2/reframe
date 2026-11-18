"""scripts/release-workflow.py: what the release workflow decides, against a fake GitHub that
keeps releases, drafts, assets and tags as the API reports them."""

from __future__ import annotations

import hashlib
import importlib.util
import itertools
import json
import os
import re
import shutil
import subprocess
import sys
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "release-workflow.py"
REPO = "owner/reframe"
TEXTS = "licence-texts.json"
TAG = "sources-0123456789ab"
ARCHIVES = ("ffmpeg.tar.xz", "gtk_3.0.tar", "lame.tar.xz")
REQUIRED = {"TAURI_SIGNING_PRIVATE_KEY", "RELEASE_GPG_PRIVATE_KEY"}


def _load_script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("release_workflow", SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # dataclasses look the module up by name
    spec.loader.exec_module(module)
    return module


rw = _load_script()


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class FakeGitHub:
    """One repository's releases, assets and tags, answering the gh commands the script runs."""

    def __init__(self) -> None:
        self.private = False
        self.tags: list[str] = []
        self.releases: list[dict[str, Any]] = []
        self.content: dict[int, bytes] = {}
        self.calls: list[tuple[str, ...]] = []
        self.error: str | None = None
        self.upload_stops_after: int | None = None
        self.after_upload: Callable[[dict[str, Any]], None] | None = None
        self._ids = itertools.count(1)

    def add_release(
        self, tag: str, files: Mapping[str, bytes], *, draft: bool = False
    ) -> dict[str, Any]:
        release: dict[str, Any] = {
            "id": next(self._ids),
            "tag_name": tag,
            "draft": draft,
            "assets": [],
            "html_url": f"https://github.com/{REPO}/releases/tag/{tag}",
        }
        for name, data in files.items():
            self._upload(release, name, data)
        self.releases.append(release)
        return release

    def asset(self, tag: str, name: str) -> dict[str, Any]:
        release = next(r for r in self.releases if r["tag_name"] == tag)
        found: dict[str, Any] = next(a for a in release["assets"] if a["name"] == name)
        return found

    def _upload(self, release: dict[str, Any], name: str, data: bytes) -> None:
        asset_id = next(self._ids)
        self.content[asset_id] = data
        release["assets"].append(
            {
                "id": asset_id,
                "name": name,
                "size": len(data),
                "state": "uploaded",
                "digest": f"sha256:{_sha256(data)}",
            }
        )

    def _release(self, path: str) -> dict[str, Any]:
        release_id = int(path.rsplit("/", 1)[1])
        found: dict[str, Any] = next(r for r in self.releases if r["id"] == release_id)
        return found

    def __call__(self, *args: str) -> bytes:
        self.calls.append(args)
        if self.error is not None:
            raise rw.ReleaseError(f"gh {' '.join(args)} failed: {self.error}")
        match args:
            case ("api", "--paginate", "--slurp", path) if path == (
                f"repos/{REPO}/releases?per_page=100"
            ):
                # Two per page, so that a release on a later page is found too.
                pages = [self.releases[i : i + 2] for i in range(0, len(self.releases), 2)]
                return json.dumps(pages or [[]]).encode()
            case ("api", "--paginate", "--slurp", path) if path == (
                f"repos/{REPO}/git/matching-refs/tags/v"
            ):
                refs = [{"ref": f"refs/tags/{tag}"} for tag in self.tags if tag.startswith("v")]
                return json.dumps([refs]).encode()
            case ("api", path) if path == f"repos/{REPO}":
                return json.dumps({"private": self.private}).encode()
            case ("api", "-X", "DELETE", path):
                self.releases.remove(self._release(path))
                return b""
            case ("api", "-X", "PATCH", path, "-F", "draft=false", "-f", latest):
                release = self._release(path)
                release["draft"] = False
                release["make_latest"] = latest.removeprefix("make_latest=")
                return json.dumps(release).encode()
            case ("api", "-H", "Accept: application/octet-stream", path):
                return self.content[int(path.rsplit("/", 1)[1])]
            case ("release", "create", tag, "--repo", repo, "--draft", "--title", title, *rest):
                assert repo == REPO
                return self._create(tag, title, list(rest))
        raise AssertionError(f"unexpected gh call: {args}")

    def _create(self, tag: str, title: str, rest: list[str]) -> bytes:
        assert rest[0] == "--notes-file"
        notes = Path(rest[1]).read_text(encoding="utf-8")
        rest = rest[2:]
        target = None
        if rest[0] == "--target":
            target, rest = rest[1], rest[2:]
        if rest[0] == "--verify-tag":
            if tag not in self.tags:
                raise rw.ReleaseError(f"tag {tag} doesn't exist in the repo")
            rest = rest[1:]
        release = self.add_release(tag, {}, draft=True)
        release |= {"title": title, "notes": notes, "target": target}
        for number, file in enumerate(rest):
            if self.upload_stops_after is not None and number >= self.upload_stops_after:
                raise rw.ReleaseError("gh release create failed: the job was cancelled")
            self._upload(release, Path(file).name, Path(file).read_bytes())
        if self.after_upload is not None:
            self.after_upload(release)
        return f"{release['html_url']}\n".encode()

    def commands(self, *first: str) -> list[tuple[str, ...]]:
        return [call for call in self.calls if call[: len(first)] == first]


@pytest.fixture
def github(monkeypatch: pytest.MonkeyPatch) -> FakeGitHub:
    fake = FakeGitHub()
    monkeypatch.setattr(rw, "gh", fake)
    return fake


@pytest.fixture
def fetched(tmp_path: Path) -> tuple[Path, Path]:
    """A source manifest and the folder that sources-fetch.py made from it."""
    manifest = tmp_path / "sources" / "manifest.json"
    files = tmp_path / "sources" / "files"
    files.mkdir(parents=True)
    entries = [{"archive": name, "kind": "url"} for name in ARCHIVES]
    manifest.write_text(json.dumps({"entries": entries, "schema_version": 1}), encoding="utf-8")
    sums = ""
    for name in sorted([*ARCHIVES, TEXTS]):
        data = f"the source of {name}".encode()
        (files / name).write_bytes(data)
        sums += f"{_sha256(data)}  {name}\n"
    (files / "SHA256SUMS").write_text(sums, encoding="utf-8")
    return manifest, files


def _published_sources(github: FakeGitHub, manifest: Path, files: Path) -> dict[str, Any]:
    contents = {"manifest.json": manifest.read_bytes()}
    contents |= {name: (files / name).read_bytes() for name in ("SHA256SUMS", TEXTS, *ARCHIVES)}
    return github.add_release(TAG, contents)


def _names(release: Mapping[str, Any]) -> list[str]:
    return sorted(asset["name"] for asset in release["assets"])


def test_without_a_sources_release_the_job_fetches(
    github: FakeGitHub, fetched: tuple[Path, Path], tmp_path: Path
) -> None:
    github.add_release("v1.0.0", {"latest.json": b"{}"})

    assert rw.find_sources(REPO, TAG, fetched[0], tmp_path / "out" / "SHA256SUMS") is False

    assert not (tmp_path / "out").exists()
    assert github.commands("api", "-X") == []


def test_a_draft_left_by_an_interrupted_run_is_deleted_not_reused(
    github: FakeGitHub, fetched: tuple[Path, Path], tmp_path: Path
) -> None:
    # gh release create uploads to a draft and publishes it last: a cancelled job leaves it.
    manifest, files = fetched
    github.add_release(
        TAG,
        {"manifest.json": manifest.read_bytes(), "SHA256SUMS": (files / "SHA256SUMS").read_bytes()},
        draft=True,
    )

    assert rw.find_sources(REPO, TAG, manifest, tmp_path / "SHA256SUMS") is False

    assert github.releases == []
    assert not (tmp_path / "SHA256SUMS").exists()


def test_a_complete_sources_release_is_reused_with_its_sums(
    github: FakeGitHub, fetched: tuple[Path, Path], tmp_path: Path
) -> None:
    manifest, files = fetched
    github.add_release("v1.0.0", {"latest.json": b"{}"})
    github.add_release("v1.0.1", {"latest.json": b"{}"})
    _published_sources(github, manifest, files)
    sums_out = tmp_path / "sources" / "SHA256SUMS"

    assert rw.find_sources(REPO, TAG, manifest, sums_out) is True

    assert sums_out.read_bytes() == (files / "SHA256SUMS").read_bytes()
    # The packages' notices need the licence texts even when nothing is fetched.
    assert (tmp_path / "sources" / TEXTS).read_bytes() == (files / TEXTS).read_bytes()


def _drop(github: FakeGitHub, name: str) -> None:
    release = github.releases[0]
    release["assets"].remove(github.asset(TAG, name))


DAMAGE: dict[str, tuple[Callable[[FakeGitHub], None], str]] = {
    "an archive missing": (lambda gh: _drop(gh, "lame.tar.xz"), "lame.tar.xz: missing"),
    "an unfinished upload": (
        lambda gh: gh.asset(TAG, "gtk_3.0.tar").update(state="starter"),
        "gtk_3.0.tar: not completely uploaded",
    ),
    "other bytes": (
        lambda gh: gh.asset(TAG, "ffmpeg.tar.xz").update(digest=f"sha256:{'0' * 64}"),
        "ffmpeg.tar.xz: sha256:000",
    ),
    "another manifest": (
        lambda gh: gh.asset(TAG, "manifest.json").update(size=3, digest=f"sha256:{'1' * 64}"),
        "manifest.json: 3 bytes",
    ),
    "no SHA256SUMS": (lambda gh: _drop(gh, "SHA256SUMS"), "SHA256SUMS: missing"),
    "an extra file": (
        lambda gh: gh._upload(gh.releases[0], "stray.tar.xz", b"x"),
        "stray.tar.xz: not a file of this release",
    ),
}


@pytest.mark.parametrize("damage", DAMAGE)
def test_a_published_but_incomplete_sources_release_stops_the_run(
    github: FakeGitHub, fetched: tuple[Path, Path], tmp_path: Path, damage: str
) -> None:
    manifest, files = fetched
    _published_sources(github, manifest, files)
    change, says = DAMAGE[damage]
    change(github)

    with pytest.raises(rw.ReleaseError, match="published but does not hold") as raised:
        rw.find_sources(REPO, TAG, manifest, tmp_path / "SHA256SUMS")

    assert says in str(raised.value)
    assert not (tmp_path / "SHA256SUMS").exists()
    assert len(github.releases) == 1


@pytest.mark.parametrize(
    ("keep", "name"),
    [
        pytest.param(lambda lines: lines[:2], "lame.tar.xz", id="the first two lines"),
        pytest.param(
            lambda lines: [line for line in lines if TEXTS.encode() not in line],
            TEXTS,
            id="no licence texts",
        ),
    ],
)
def test_sums_that_leave_out_a_file_stop_the_run(
    github: FakeGitHub,
    fetched: tuple[Path, Path],
    tmp_path: Path,
    keep: Callable[[list[bytes]], list[bytes]],
    name: str,
) -> None:
    """A release whose sums skip the licence texts cannot give the notices theirs."""
    manifest, files = fetched
    _published_sources(github, manifest, files)
    sums = github.asset(TAG, "SHA256SUMS")
    shorter = b"".join(keep((files / "SHA256SUMS").read_bytes().splitlines(keepends=True)))
    github.content[sums["id"]] = shorter
    sums.update(size=len(shorter), digest=f"sha256:{_sha256(shorter)}")

    with pytest.raises(rw.ReleaseError, match=rf"{re.escape(name)}: not in its SHA256SUMS"):
        rw.find_sources(REPO, TAG, manifest, tmp_path / "SHA256SUMS")


def test_licence_texts_whose_bytes_are_not_the_sums_stop_the_run(
    github: FakeGitHub, fetched: tuple[Path, Path], tmp_path: Path
) -> None:
    # The API may give no digest; the downloaded bytes are checked against SHA256SUMS then.
    manifest, files = fetched
    _published_sources(github, manifest, files)
    texts = github.asset(TAG, TEXTS)
    github.content[texts["id"]] = b"other texts"
    texts.update(digest=None)

    with pytest.raises(rw.ReleaseError, match=rf"{TEXTS}: downloaded bytes"):
        rw.find_sources(REPO, TAG, manifest, tmp_path / "SHA256SUMS")
    assert not (tmp_path / TEXTS).exists()


def test_sources_find_writes_the_texts_where_it_is_told(
    github: FakeGitHub, fetched: tuple[Path, Path], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GITHUB_OUTPUT", str(tmp_path / "github-output"))
    _published_sources(github, *fetched)
    args = ["sources-find", "--repo", REPO, "--tag", TAG, "--manifest", str(fetched[0])]
    args += ["--sums-out", str(tmp_path / "SHA256SUMS")]

    assert rw.main([*args, "--texts-out", str(tmp_path / "texts" / "t.json")]) == 0

    assert (tmp_path / "texts" / "t.json").read_bytes() == (fetched[1] / TEXTS).read_bytes()


def test_a_github_error_is_not_read_as_no_sources_release(
    github: FakeGitHub,
    fetched: tuple[Path, Path],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    output = tmp_path / "github-output"
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))
    github.error = "HTTP 502: Bad Gateway"

    code = rw.main(
        [
            *("sources-find", "--repo", REPO, "--tag", TAG, "--manifest", str(fetched[0])),
            *("--sums-out", str(tmp_path / "SHA256SUMS")),
        ]
    )

    assert code == 1
    assert not output.exists()
    assert "::error::" in capsys.readouterr().out


def test_sources_find_writes_found_for_the_next_steps(
    github: FakeGitHub, fetched: tuple[Path, Path], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output = tmp_path / "github-output"
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))
    args = ["sources-find", "--repo", REPO, "--tag", TAG, "--manifest", str(fetched[0])]
    args += ["--sums-out", str(tmp_path / "SHA256SUMS")]

    assert rw.main(args) == 0
    _published_sources(github, *fetched)
    assert rw.main(args) == 0

    assert output.read_text(encoding="utf-8") == "found=false\nfound=true\n"


@pytest.mark.skipif(sys.platform == "win32", reason="a shell script stands in for gh")
def test_gh_raises_on_any_failure_with_its_message(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = tmp_path / "gh"
    fake.write_text(
        '#!/bin/sh\nif [ "$1" = ok ]; then echo \'{"a": 1}\'; exit 0; fi\n'
        'echo "gh: Not Found (HTTP 404)" >&2\nexit 1\n',
        encoding="utf-8",
    )
    fake.chmod(0o755)
    monkeypatch.setenv("PATH", f"{tmp_path}{os.pathsep}{os.environ['PATH']}")

    assert rw.gh_json("ok") == {"a": 1}
    with pytest.raises(rw.ReleaseError, match=r"HTTP 404"):
        rw.gh("release", "view", TAG)


def test_the_sources_release_is_published_complete_and_never_latest(
    github: FakeGitHub, fetched: tuple[Path, Path], tmp_path: Path
) -> None:
    manifest, files = fetched

    url = rw.publish_sources(REPO, TAG, manifest, files, "0f1e2d3c")

    [release] = github.releases
    assert release["draft"] is False
    assert (release["make_latest"], release["target"]) == ("false", "0f1e2d3c")
    assert _names(release) == sorted(["manifest.json", "SHA256SUMS", TEXTS, *ARCHIVES])
    assert url == release["html_url"]
    assert rw.find_sources(REPO, TAG, manifest, tmp_path / "SHA256SUMS") is True


def test_an_interrupted_upload_is_not_published_and_the_next_run_starts_over(
    github: FakeGitHub, fetched: tuple[Path, Path], tmp_path: Path
) -> None:
    manifest, files = fetched
    github.upload_stops_after = 2

    with pytest.raises(rw.ReleaseError, match="cancelled"):
        rw.publish_sources(REPO, TAG, manifest, files, "0f1e2d3c")

    [draft] = github.releases
    assert draft["draft"] is True
    assert len(draft["assets"]) == 2
    github.upload_stops_after = None
    assert rw.find_sources(REPO, TAG, manifest, tmp_path / "SHA256SUMS") is False
    rw.publish_sources(REPO, TAG, manifest, files, "0f1e2d3c")
    [release] = github.releases
    assert release["draft"] is False
    assert _names(release) == sorted(["manifest.json", "SHA256SUMS", TEXTS, *ARCHIVES])


@pytest.mark.parametrize(
    ("change", "says"),
    [
        (lambda release: release["assets"][3].update(state="starter"), "not completely uploaded"),
        (lambda release: release["assets"].pop(), "missing"),
        (lambda release: release["assets"][0].update(size=1), "1 bytes"),
    ],
)
def test_a_draft_is_published_only_when_github_has_every_file(
    github: FakeGitHub,
    fetched: tuple[Path, Path],
    change: Callable[[dict[str, Any]], None],
    says: str,
) -> None:
    github.after_upload = change

    with pytest.raises(rw.ReleaseError, match="not complete") as raised:
        rw.publish_sources(REPO, TAG, *fetched, "0f1e2d3c")

    assert says in str(raised.value)
    assert github.releases[0]["draft"] is True
    assert github.commands("api", "-X", "PATCH") == []


@pytest.mark.parametrize("name", ["lame.tar.xz", TEXTS])
def test_sources_whose_sums_do_not_match_a_file_are_not_uploaded(
    github: FakeGitHub, fetched: tuple[Path, Path], name: str
) -> None:
    manifest, files = fetched
    (files / name).write_bytes(b"changed after the sums were written")

    with pytest.raises(rw.ReleaseError, match=re.escape(name)):
        rw.publish_sources(REPO, TAG, manifest, files, "0f1e2d3c")

    assert github.commands("release") == []


def _artefacts(folder: Path) -> list[Path]:
    paths = []
    for name in ("Reframe_1.1.0_amd64.AppImage", "Reframe_1.1.0_x64-setup.exe", "SHA256SUMS"):
        path = folder / name
        path.write_bytes(name.encode())
        paths.append(path)
    return paths


@pytest.mark.parametrize("latest", [True, False])
def test_the_version_is_published_with_every_file_and_latest_as_asked(
    github: FakeGitHub, tmp_path: Path, latest: bool
) -> None:
    github.tags = ["v1.1.0"]
    notes = tmp_path / "notes.md"
    notes.write_text("### Fixed\n", encoding="utf-8")
    paths = _artefacts(tmp_path)

    rw.publish(
        REPO,
        "v1.1.0",
        paths,
        title="Reframe 1.1.0",
        notes_file=notes,
        latest=latest,
        verify_tag=True,
    )

    [release] = github.releases
    assert release["draft"] is False
    assert release["make_latest"] == str(latest).lower()
    assert (release["title"], release["notes"], release["target"]) == (
        "Reframe 1.1.0",
        "### Fixed\n",
        None,
    )
    assert _names(release) == sorted(path.name for path in paths)
    assert "--verify-tag" in github.commands("release", "create")[0]


def test_a_leftover_draft_of_the_version_is_replaced(github: FakeGitHub, tmp_path: Path) -> None:
    github.tags = ["v1.1.0"]
    github.add_release("v1.1.0", {"Reframe_1.1.0_amd64.AppImage": b"part"}, draft=True)
    notes = tmp_path / "notes.md"
    notes.write_text("notes", encoding="utf-8")

    rw.publish(REPO, "v1.1.0", _artefacts(tmp_path), title="T", notes_file=notes, latest=True)

    [release] = github.releases
    assert release["draft"] is False
    assert github.asset("v1.1.0", "Reframe_1.1.0_amd64.AppImage")["size"] == len(
        b"Reframe_1.1.0_amd64.AppImage"
    )


def test_a_published_version_is_never_replaced(github: FakeGitHub, tmp_path: Path) -> None:
    github.add_release("v1.1.0", {"latest.json": b"{}"})
    notes = tmp_path / "notes.md"
    notes.write_text("notes", encoding="utf-8")

    with pytest.raises(rw.ReleaseError, match="published already"):
        rw.publish(REPO, "v1.1.0", _artefacts(tmp_path), title="T", notes_file=notes, latest=True)

    assert github.commands("release") == []
    assert _names(github.releases[0]) == ["latest.json"]


@pytest.mark.parametrize(
    "text", [f"{'a' * 64}  x.tar\n{'b' * 64}  x.tar\n", f"{'a' * 63}  x.tar\n", "x.tar\n"]
)
def test_sums_with_a_bad_line_or_a_name_twice_are_refused(text: str) -> None:
    with pytest.raises(rw.ReleaseError, match="not a SHA-256 line of a new file"):
        rw.parse_sums(text, "SHA256SUMS")


def test_a_second_draft_of_the_tag_during_the_upload_is_not_published(
    github: FakeGitHub, fetched: tuple[Path, Path]
) -> None:
    # Another run uploading at the same time; the workflow's concurrency group prevents it.
    def another_run(release: dict[str, Any]) -> None:
        github.add_release(TAG, {}, draft=True)

    github.after_upload = another_run

    with pytest.raises(rw.ReleaseError, match="2 draft releases"):
        rw.publish_sources(REPO, TAG, *fetched, "0f1e2d3c")

    assert github.commands("api", "-X", "PATCH") == []


def test_two_files_with_one_name_are_refused(tmp_path: Path) -> None:
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    for folder in ("a", "b"):
        (tmp_path / folder / "SHA256SUMS").write_text(folder, encoding="utf-8")

    with pytest.raises(rw.ReleaseError, match="two files are named SHA256SUMS"):
        rw.local_files([tmp_path / "a" / "SHA256SUMS", tmp_path / "b" / "SHA256SUMS"])


@pytest.mark.parametrize("version", ["1.1.0", "0.1.0", "255.255.65535"])
def test_a_tag_of_the_stamped_final_version_passes(github: FakeGitHub, version: str) -> None:
    assert rw.preflight(f"v{version}", version, REPO, REQUIRED, "") == ([], True)


@pytest.mark.parametrize(
    ("tag", "version", "says"),
    [
        ("v1.2.1", "1.2.0", "The tag v1.2.1 is not v1.2.0"),
        ("v1.2.0rc1", "1.2.0rc1", "pre-releases are not released"),
        ("v0.1.0.dev0", "0.1.0.dev0", "pre-releases are not released"),
        ("v1\u0661.2.0", "1\u0661.2.0", "pre-releases are not released"),
        ("v256.0.0", "256.0.0", "at most 255.255.65535"),
        ("v1.256.0", "1.256.0", "at most 255.255.65535"),
        ("v1.0.65536", "1.0.65536", "at most 255.255.65535"),
    ],
)
def test_a_tag_that_is_not_a_final_version_the_msi_can_take_is_refused(
    github: FakeGitHub, tag: str, version: str, says: str
) -> None:
    problems, _ = rw.preflight(tag, version, REPO, REQUIRED, "")

    assert len(problems) == 1
    assert says in problems[0]


@pytest.mark.parametrize(
    ("secrets", "timestamp_url", "missing"),
    [
        (set(), "", ["TAURI_SIGNING_PRIVATE_KEY", "RELEASE_GPG_PRIVATE_KEY"]),
        (REQUIRED - {"RELEASE_GPG_PRIVATE_KEY"}, "", ["RELEASE_GPG_PRIVATE_KEY"]),
        (
            REQUIRED | {"WINDOWS_CERTIFICATE"},
            "",
            ["WINDOWS_CERTIFICATE_PASSWORD", "WINDOWS_TIMESTAMP_URL"],
        ),
        (REQUIRED | {"WINDOWS_CERTIFICATE"}, "http://ts.example", ["WINDOWS_CERTIFICATE_PASSWORD"]),
        (REQUIRED | {"WINDOWS_CERTIFICATE", "WINDOWS_CERTIFICATE_PASSWORD"}, "", ["TIMESTAMP"]),
        (REQUIRED | {"WINDOWS_CERTIFICATE", "WINDOWS_CERTIFICATE_PASSWORD"}, "http://ts", []),
        (REQUIRED | {"WINDOWS_CERTIFICATE_PASSWORD"}, "", []),
    ],
)
def test_each_secret_a_release_needs_is_named_before_anything_is_built(
    github: FakeGitHub, secrets: set[str], timestamp_url: str, missing: list[str]
) -> None:
    problems, _ = rw.preflight("v1.1.0", "1.1.0", REPO, secrets, timestamp_url)

    assert len(problems) == len(missing)
    for name, problem in zip(missing, problems, strict=True):
        assert name in problem


def test_a_private_repository_is_refused(github: FakeGitHub) -> None:
    github.private = True

    problems, _ = rw.preflight("v1.1.0", "1.1.0", REPO, REQUIRED, "")

    assert len(problems) == 1
    assert f"{REPO} is private" in problems[0]


@pytest.mark.parametrize(
    ("version", "tags", "latest"),
    [
        ("1.1.0", ["v1.0.0", "v1.1.0"], True),
        ("1.0.5", ["v1.0.4", "v1.0.5", "v1.1.0"], False),
        ("1.1.0", ["v1.1.0", "v1.1.1rc1", "v1.2.0.dev0", "sources-abc"], True),
        ("1.10.0", ["v1.9.0", "v1.10.0"], True),
        ("1.9.1", ["v1.9.1", "v1.10.0"], False),
        ("2.0.0", ["v2.0.0", "v10.0.0"], False),
    ],
)
def test_only_the_highest_version_is_the_latest(
    github: FakeGitHub, version: str, tags: list[str], latest: bool
) -> None:
    github.tags = tags

    assert rw.preflight(f"v{version}", version, REPO, REQUIRED, "") == ([], latest)


def test_preflight_writes_its_outputs_or_names_every_problem(
    github: FakeGitHub,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    output = tmp_path / "github-output"
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))
    for name in REQUIRED:
        monkeypatch.setenv(f"{name}_SET", "true")
    github.tags = ["v1.0.0", "v1.1.0"]
    args = ["preflight", "--tag", "v1.0.1", "--version", "1.0.1", "--repo", REPO]

    assert rw.main(args) == 0
    assert output.read_text(encoding="utf-8") == "version=1.0.1\nlatest=false\n"

    monkeypatch.setenv("RELEASE_GPG_PRIVATE_KEY_SET", "false")
    github.private = True
    capsys.readouterr()
    assert rw.main(args) == 1
    errors = [line for line in capsys.readouterr().out.splitlines() if line.startswith("::error::")]
    assert len(errors) == 2
    assert output.read_text(encoding="utf-8") == "version=1.0.1\nlatest=false\n"


SUMS_TEXT = f"{'a' * 64}  ffmpeg.tar.xz\n{'b' * 64}  lame.tar.xz\n"


@pytest.mark.parametrize("signed", ["true", "false", ""])
def test_the_notes_carry_the_changes_checks_sources_and_the_unsigned_warning(
    tmp_path: Path, signed: str
) -> None:
    changes = tmp_path / "changes.md"
    changes.write_text("### Fixed\n\n- F-17: the queue keeps its order\n", encoding="utf-8")
    sums = tmp_path / "SHA256SUMS"
    sums.write_text(SUMS_TEXT, encoding="utf-8")
    out = tmp_path / "notes.md"
    check_url = "https://github.com/owner/reframe/blob/v1.1.0/docs/release.md#check-a-download"

    code = rw.main(
        [
            *("notes", "--changes", str(changes), "--signed", signed, "--check-url", check_url),
            *("--sources-url", f"https://github.com/{REPO}/releases/tag/{TAG}"),
            *("--sources-sums", str(sums), "--out", str(out)),
        ]
    )

    assert code == 0
    text = out.read_text(encoding="utf-8")
    assert text.startswith("### Fixed\n\n- F-17: the queue keeps its order\n\n")
    assert ("not code-signed" in text) is (signed != "true")
    assert f"`SHA256SUMS.asc` its GPG signature. How to check a download: {check_url}" in text
    assert f"https://github.com/{REPO}/releases/tag/{TAG}" in text
    assert f"```\n{SUMS_TEXT}```\n" in text


needs_gpg = pytest.mark.skipif(
    sys.platform == "win32" or not shutil.which("gpg") or not shutil.which("gpgconf"),
    reason="the release job signs on Linux with GnuPG",
)


@dataclass(frozen=True)
class Keys:
    secret: str
    public: str
    other_public: str


def _gpg(home: Path, *args: str, stdin: str = "") -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["gpg", "--homedir", str(home), "--batch", "--no-tty", *args],
        input=stdin,
        capture_output=True,
        text=True,
        check=False,
    )


def _kill_agent(home: Path) -> None:
    subprocess.run(["gpgconf", "--homedir", str(home), "--kill", "all"], check=False)


def _new_key(home: Path, uid: str) -> tuple[str, str]:
    home.mkdir(mode=0o700)
    try:
        secret = ("--pinentry-mode", "loopback", "--passphrase", "pw")
        _gpg(home, *secret, "--quick-gen-key", uid, "ed25519", "sign", "never")
        exported = _gpg(home, *secret, "--armor", "--export-secret-keys").stdout
        return exported, _gpg(home, "--armor", "--export").stdout
    finally:
        _kill_agent(home)


@pytest.fixture(scope="module")
def keys(tmp_path_factory: pytest.TempPathFactory) -> Keys:
    """A throwaway release key with the passphrase ``pw``, and another key's public half."""
    folder = tmp_path_factory.mktemp("gpg")
    secret, public = _new_key(folder / "release", "Release <release@example.invalid>")
    _, other = _new_key(folder / "other", "Other <other@example.invalid>")
    assert "PRIVATE KEY BLOCK" in secret
    return Keys(secret, public, other)


def _doc(folder: Path, public_key: str) -> Path:
    doc = folder / "release.md"
    doc.write_text(f"# Releasing\n\n```text\n{public_key}```\n\nMore text.\n", encoding="utf-8")
    return doc


@pytest.fixture
def user_home(tmp_path: Path) -> Iterator[Path]:
    """A user's GnuPG home with nothing in it."""
    home = tmp_path / "user"
    home.mkdir(mode=0o700)
    yield home
    _kill_agent(home)


def _user_verifies(home: Path, public_key: str, folder: Path) -> bool:
    """docs/release.md's check: import the key, verify the signature, then each file's sum."""
    _gpg(home, "--import", stdin=public_key)
    verified = _gpg(home, "--verify", str(folder / "SHA256SUMS.asc"), str(folder / "SHA256SUMS"))
    if verified.returncode != 0:
        return False
    for line in (folder / "SHA256SUMS").read_text(encoding="utf-8").splitlines():
        sha256, name = line.split("  ")
        if _sha256((folder / name).read_bytes()) != sha256:
            return False
    return True


@needs_gpg
def test_sha256sums_of_every_file_is_signed_so_that_users_can_check_a_download(
    keys: Keys, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, user_home: Path
) -> None:
    out = tmp_path / "dist"
    out.mkdir()
    names = ["Reframe_1.1.0_amd64.AppImage", "Reframe-1.1.0-1.x86_64.rpm", "latest.json"]
    for name in names:
        (out / name).write_bytes(name.encode() * 1000)
    monkeypatch.setenv("RELEASE_GPG_PRIVATE_KEY", keys.secret)
    monkeypatch.setenv("RELEASE_GPG_PASSPHRASE", "pw")

    code = rw.main(
        ["sums", "--out-dir", str(out), "--public-key-doc", str(_doc(tmp_path, keys.public))]
        + [str(out / name) for name in names]
    )

    assert code == 0
    lines = (out / "SHA256SUMS").read_text(encoding="utf-8").splitlines()
    assert [line.split("  ")[1] for line in lines] == sorted(names)
    assert _user_verifies(user_home, keys.public, out)
    (out / "SHA256SUMS").write_text("\n".join(lines[1:]) + "\n", encoding="utf-8")
    assert not _user_verifies(user_home, keys.public, out)


@needs_gpg
@pytest.mark.parametrize(
    ("case", "says"),
    [
        ("a wrong passphrase", "Bad passphrase"),
        ("another key in the docs", "holds another key"),
        ("no key in the docs", "has no PGP public key block"),
        ("no secret", "RELEASE_GPG_PRIVATE_KEY is not set"),
    ],
)
def test_no_signature_that_users_could_not_check_is_made(
    keys: Keys,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    case: str,
    says: str,
) -> None:
    file = tmp_path / "Reframe_1.1.0_amd64.deb"
    file.write_bytes(b"deb")
    public = {"another key in the docs": keys.other_public, "no key in the docs": "(not yet)\n"}
    doc = _doc(tmp_path, public.get(case, keys.public))
    monkeypatch.setenv("RELEASE_GPG_PRIVATE_KEY", "" if case == "no secret" else keys.secret)
    monkeypatch.setenv("RELEASE_GPG_PASSPHRASE", "wrong" if case == "a wrong passphrase" else "pw")

    code = rw.main(
        ["sums", "--out-dir", str(tmp_path / "out"), "--public-key-doc", str(doc), str(file)]
    )

    assert code == 1
    out = capsys.readouterr().out
    assert out.startswith("::error::")
    assert says in out
    if case != "another key in the docs":
        assert not (tmp_path / "out" / "SHA256SUMS.asc").exists()


def test_every_package_job_hands_the_licence_texts_to_its_notices() -> None:
    """Without them a package's notices would lack the texts; only a real run would show it."""
    workflow = (REPO_ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
    texts = '"$RUNNER_TEMP/sources/licence-texts.json"'

    calls = re.findall(r"third-party-notices\.py(.*?)(?:\n\n|\n      - )", workflow, re.DOTALL)
    assert len(calls) == 2  # the Windows job and the Docker job
    for call in calls:
        assert f"--sources-texts {texts}" in call
    assert "REFRAME_SOURCES_TEXTS: ${{ runner.temp }}/sources/licence-texts.json" in workflow
    assert f"--texts-out {texts}" in workflow
    assert "${{ runner.temp }}/sources/licence-texts.json\n" in workflow
    assert '"$RUNNER_TEMP/sources/files/licence-texts.json"' in workflow
