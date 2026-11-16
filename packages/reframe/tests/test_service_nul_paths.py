"""A path with a NUL character at the facade's entry points is an expected error, never an
exception. Only the API can send one: argv cannot hold a NUL, and JSON can (``\\u0000``).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from reframe.models import (
    JobSettings,
    MediaSource,
    Severity,
    SourceRef,
    ValidationIssue,
)
from reframe.service import ProbeError, ProbeErrorKind, Reframe
from reframe.tools import ENV_VARS
from reframe_testing import fake_tools as ft

pytestmark = pytest.mark.anyio

PROBES = Path(__file__).resolve().parents[3] / "testdata" / "probes"
MULTITRACK = PROBES / "fixtures" / "multitrack.mkv.json"
NUL_MESSAGE = (
    "The path has a NUL character, which no file system allows: no file can have this name."
)


@pytest.fixture
def env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """No tool overrides, user folders in ``tmp_path``."""
    for var in ENV_VARS.values():
        monkeypatch.delenv(var, raising=False)
    for name in ("config", "data", "cache"):
        monkeypatch.setenv(f"REFRAME_{name.upper()}_DIR", str(tmp_path / name))
    return tmp_path


@pytest.fixture
def fake(env: Path, fake_tools: ft.FakeTools, monkeypatch: pytest.MonkeyPatch) -> ft.FakeTools:
    """``REFRAME_FFMPEG`` / ``REFRAME_FFPROBE`` point at the fake tools (multitrack probe)."""
    monkeypatch.setenv("REFRAME_FFMPEG", str(fake_tools.ffmpeg))
    monkeypatch.setenv("REFRAME_FFPROBE", str(fake_tools.ffprobe))
    rule = ft.Rule(
        tool="ffprobe", argv_has=["-show_streams"], actions=[{"stdout_file": str(MULTITRACK)}]
    )
    fake_tools.set_scenario(ft.Scenario([rule]))
    return fake_tools


@pytest.fixture
def media(tmp_path: Path) -> Path:
    path = tmp_path / "Movie.mkv"
    path.write_bytes(b"\x1a\x45\xdf\xa3 not really matroska")
    return path


def _nul_error(outcome: object, path: Path) -> None:
    assert isinstance(outcome, ProbeError)
    assert outcome.kind is ProbeErrorKind.NOT_FOUND
    assert outcome.path == path
    assert outcome.message == NUL_MESSAGE
    assert outcome.detail is None


async def test_probe_of_a_nul_path_is_a_probe_error(fake: ft.FakeTools, env: Path) -> None:
    nul = env / "Mo\0vie.mkv"
    async with await Reframe.create() as app:
        _nul_error(await app.sources.probe(nul), nul)
        _nul_error(await app.sources.probe(str(nul), use_cache=False), nul)
        in_folder = env / "fol\0der" / "Movie.mkv"
        _nul_error(await app.sources.probe(in_folder), in_folder)
        # ffprobe was not asked (its -version is tool discovery's).
        assert [argv for argv in fake.calls("ffprobe") if "-show_streams" in argv] == []


async def test_probe_of_a_nul_path_without_ffprobe(
    env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A file problem comes before the tool's: the same error when ffprobe is missing."""
    monkeypatch.setenv("REFRAME_FFPROBE", str(env / "nowhere" / "ffprobe"))
    nul = env / "Mo\0vie.mkv"
    async with await Reframe.create() as app:
        _nul_error(await app.sources.probe(nul), nul)


async def test_get_store_and_update_of_a_nul_path(
    fake: ft.FakeTools, env: Path, media: Path
) -> None:
    nul = env / "Mo\0vie.mkv"
    async with await Reframe.create() as app:
        probed = await app.sources.probe(media)
        assert isinstance(probed, MediaSource)
        assert await app.sources.get(nul) is None
        bad = probed.model_copy(update={"ref": probed.ref.model_copy(update={"path": nul})})
        await app.sources.store(bad)
        await app.sources.update(bad, lambda latest: latest)
        assert await app.sources.get(nul) is None
        assert await app.sources.get(media) == probed


def _errors(issues: object) -> list[ValidationIssue]:
    assert isinstance(issues, list)
    return [i for i in issues if isinstance(i, ValidationIssue) and i.severity is Severity.ERROR]


async def _job(app: Reframe, media: Path) -> JobSettings:
    draft = await app.jobs.draft(media)
    assert not isinstance(draft, ProbeError)
    return draft.job


async def test_validate_a_job_with_a_nul_in_its_output_path(
    fake: ft.FakeTools, env: Path, media: Path
) -> None:
    async with await Reframe.create() as app:
        job = await _job(app, media)
        (env / "out").mkdir()
        for output in (env / "out" / "Mo\0vie.mkv", env / "fol\0der" / "Movie.mkv"):
            job.output.path = output
            for issues in (await app.jobs.validate(job), await app.jobs.plan(job)):
                [issue] = _errors(issues)
                assert (issue.code, issue.path) == ("output.not_writable", "output.path")
                shown = str(output).replace("\0", "\\0")
                assert issue.message.startswith(f"The output path {shown} has a NUL character")
            # ``draft(source, output=…)`` (a manual output name) validates the same way.
            draft = await app.jobs.draft(media, output=output)
            assert not isinstance(draft, ProbeError)
            assert [(i.code, i.path) for i in _errors(draft.issues)] == [
                ("output.not_writable", "output.path")
            ]


async def test_validate_a_job_with_a_nul_in_its_source_path(
    fake: ft.FakeTools, env: Path, media: Path
) -> None:
    nul = env / "Mo\0vie.mkv"
    async with await Reframe.create() as app:
        job = await _job(app, media)
        job.source = SourceRef(path=nul)
        for issues in (
            await app.jobs.validate(job),
            await app.jobs.plan(job, dry_run=True),
            await app.jobs.dry_run(job),
        ):
            [issue] = _errors(issues)
            assert (issue.code, issue.path) == ("source.probe_failed", "source")
            assert issue.message == f"{nul.name} cannot be read: {NUL_MESSAGE}"
        _nul_error(await app.jobs.draft(nul), nul)


async def test_validate_and_plan_with_a_given_source_with_a_nul(
    fake: ft.FakeTools, env: Path, media: Path
) -> None:
    nul = env / "Mo\0vie.mkv"
    async with await Reframe.create() as app:
        probed = await app.sources.probe(media)
        assert isinstance(probed, MediaSource)
        bad = probed.model_copy(update={"ref": probed.ref.model_copy(update={"path": nul})})
        job = (await _job(app, media)).model_copy(update={"source": bad.ref})
        for issues in (
            await app.jobs.validate(job, bad),
            await app.jobs.plan(job, bad),
            await app.jobs.plan(job, bad, dry_run=True),
        ):
            assert isinstance(issues, list)
            assert [(i.code, i.path) for i in _errors(issues)] == [
                ("source.path_unusable", "source")
            ]
        [skipped] = await app.jobs.dry_run(job, bad)
        assert (skipped.code, skipped.severity) == ("encoder.dry_run_skipped", Severity.WARNING)
