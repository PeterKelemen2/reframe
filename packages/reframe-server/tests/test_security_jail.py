"""The path jail: every path from a client must stay inside the media roots (read) or the
output roots (write) after links and ``..`` are resolved; desktop mode allows every path."""

from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from pydantic import Field

from reframe.models import ExternalSubtitle, JobSettings, SourceRef, SubtitleOutputTrack
from reframe_server import security
from reframe_server.config import ServerConfig, ServerMode
from reframe_server.errors import ProblemError


@dataclass
class Roots:
    media: Path
    output: Path
    outside: Path

    def config(self, mode: ServerMode = "web", **overrides: Any) -> ServerConfig:
        settings: dict[str, Any] = {
            "mode": mode,
            "auth": "token",
            "media_roots": [self.media],
            "output_roots": [self.output],
        }
        return ServerConfig(**(settings | overrides))


@pytest.fixture
def roots(tmp_path: Path) -> Roots:
    folders = Roots(tmp_path / "media", tmp_path / "output", tmp_path / "outside")
    for folder in (folders.media, folders.output, folders.outside):
        folder.mkdir()
    (folders.outside / "secret.mkv").write_bytes(b"x")
    return folders


def _link(link: Path, target: Path) -> None:
    try:
        link.symlink_to(target, target_is_directory=True)
    except OSError as exc:  # Windows without the symlink privilege
        pytest.skip(f"cannot make a symbolic link: {exc}")


def _refused(call: Callable[..., object], *args: object) -> ProblemError:
    with pytest.raises(ProblemError) as caught:
        call(*args)
    return caught.value


def test_a_path_inside_a_root_comes_back_resolved(roots: Roots) -> None:
    config = roots.config()
    (roots.media / "Show").mkdir()
    assert (
        security.jail_read(config, roots.media / "Show" / ".." / "a.mkv")
        == (roots.media / "a.mkv").resolve()
    )
    new_folder = roots.output / "not" / "made" / "yet.mkv"
    assert security.jail_write(config, str(new_folder)) == new_folder.resolve()


@pytest.mark.parametrize("attack", ["traversal", "symlink", "absolute"])
def test_a_path_that_leaves_the_roots_is_refused(roots: Roots, attack: str) -> None:
    if attack == "traversal":
        path = roots.media / ".." / "outside" / "secret.mkv"
    elif attack == "symlink":
        _link(roots.media / "link", roots.outside)
        path = roots.media / "link" / "secret.mkv"
    else:
        path = roots.outside / "secret.mkv"
    problem = _refused(security.jail_read, roots.config(), path).problem
    assert (problem.status, problem.code) == (403, "path.outside_roots")
    if attack == "symlink":
        assert str(roots.outside) not in (problem.detail or ""), "where the link points"


def test_a_root_reached_through_a_link_still_works(roots: Roots, tmp_path: Path) -> None:
    linked = tmp_path / "media-link"
    _link(linked, roots.media)
    config = roots.config(media_roots=[linked])
    assert security.jail_read(config, roots.media / "a.mkv") == (roots.media / "a.mkv").resolve()


def test_reading_and_writing_have_their_own_roots(roots: Roots) -> None:
    config = roots.config()
    assert _refused(security.jail_write, config, roots.media / "a.mkv").problem.status == 403
    assert _refused(security.jail_read, config, roots.output / "a.mkv").problem.status == 403


@pytest.mark.parametrize(("mode", "case"), [("web", "relative"), ("desktop", "NUL")])
def test_a_path_that_is_not_absolute_or_holds_a_nul_is_a_bad_request(
    roots: Roots, mode: ServerMode, case: str
) -> None:
    path = "relative/a.mkv" if case == "relative" else f"{roots.media}{os.sep}a\0.mkv"
    problem = _refused(security.jail_read, roots.config(mode), path).problem
    assert (problem.status, problem.code) == (400, "path.invalid")
    assert ("not absolute" in (problem.detail or "")) is (case == "relative")


def test_desktop_mode_allows_the_whole_file_system(roots: Roots) -> None:
    secret = roots.outside / "secret.mkv"
    config = roots.config("desktop")
    assert security.jail_read(config, secret) == secret.resolve()
    assert security.jail_write(config, secret) == secret.resolve()


def _job(roots: Roots, case: str = "inside") -> JobSettings:
    job = JobSettings(source=SourceRef(path=roots.media / "a.mkv"))
    job.output.path = roots.output / "a.mkv"
    if case == "source outside":
        job.source.path = roots.outside / "secret.mkv"
    elif case == "subtitle outside":
        external = ExternalSubtitle(path=roots.outside / "a.srt")
        job.subtitles = [SubtitleOutputTrack(source=0), SubtitleOutputTrack(source=external)]
    elif case == "output in the media root":
        job.output.path = roots.media / "b.mkv"
    elif case == "in-place edit of a read-only source":
        job.output.edit_in_place = True
    return job


@pytest.mark.parametrize(
    "case",
    [
        "source outside",
        "subtitle outside",
        "output in the media root",
        "in-place edit of a read-only source",
    ],
)
def test_jail_job_refuses_a_path_the_job_may_not_use(roots: Roots, case: str) -> None:
    problem = _refused(security.jail_job, roots.config(), _job(roots, case)).problem
    assert (problem.status, problem.code) == (403, "path.outside_roots")


def test_jail_job_allows_a_job_inside_its_roots(roots: Roots) -> None:
    job = _job(roots)
    job.subtitles = [SubtitleOutputTrack(source=ExternalSubtitle(path=roots.media / "a.srt"))]
    security.jail_job(roots.config(), job)
    job.output.edit_in_place = True
    security.jail_job(roots.config(output_roots=[roots.output, roots.media]), job)


class _LaterJob(JobSettings):
    attachments: dict[str, list[Path]] = Field(default_factory=dict)
    chapter_file: Path | None = None


@pytest.mark.parametrize("field", ["attachments", "chapter_file"])
def test_a_path_field_added_to_the_job_later_is_checked_too(roots: Roots, field: str) -> None:
    job = _LaterJob(source=SourceRef(path=roots.media / "a.mkv"))
    outside = roots.outside / "secret.mkv"
    if field == "attachments":
        job.attachments = {"cover": [outside]}
    else:
        job.chapter_file = outside
    assert _refused(security.jail_job, roots.config(), job).problem.status == 403
