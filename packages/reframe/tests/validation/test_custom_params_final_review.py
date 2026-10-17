"""Custom parameters after the final review (decision 0035 "Follow-up (final review,
2026-10-17)"), RC-1: x264 reads every ``cqm`` value as a file name unless it contains ``flat``
or ``jvt`` (checked with x264 core 165), as it reads ``cqmfile``. ``cqm=FILE`` passed validation,
so ``reframe plan`` dry-ran a shared preset with it and ``reframe encode`` read and applied FILE.
Now validation refuses it (``encoder.custom_param_file``), the dry run never starts FFmpeg with
it, and planning returns the error; ``cqm=flat`` / ``cqm=jvt`` still dry-run.

Each test failed on 5dbf152. The real runs use the fixtures and FFmpeg on ``PATH``; the
encoders' behaviour is in ``test_custom_params_ffmpeg.py``."""

from __future__ import annotations

import asyncio
import importlib.util
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from reframe.jsonpatch import apply_patch
from reframe.models import (
    JobSettings,
    MediaSource,
    Severity,
    SourceRef,
    ToolInfo,
    ToolSet,
    ToolStatus,
    VideoSettings,
)
from reframe.probe import ProbeError
from reframe.service import Reframe
from reframe.tools import RunResult
from reframe.validation import dryrun
from reframe.validation.dryrun import dry_run

pytestmark = pytest.mark.anyio

FixtureMedia = Callable[[str], Path]

#: x264's own CQM file format: every matrix flat 16 (as the reviewer's reproduction).
CQM_FILE = "".join(
    f"{name} =\n" + ",".join(["16"] * size) + "\n"
    for name, size in (
        ("INTRA4X4_LUMA", 16),
        ("INTRA4X4_CHROMA", 16),
        ("INTER4X4_LUMA", 16),
        ("INTER4X4_CHROMA", 16),
        ("INTRA8X8_LUMA", 64),
        ("INTER8X8_LUMA", 64),
    )
)


def _load(name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        f"_reframe_validation_{name}", Path(__file__).with_name(f"{name}.py")
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


sc = _load("scenario")


def _job(custom: str, encoder: str = "libx264") -> JobSettings:
    return JobSettings(
        source=SourceRef(path=Path("/media/in.mkv")),
        video=VideoSettings(encoder=encoder, custom_params=custom),
    )


def _found_tools() -> ToolSet:
    def info(name: str) -> ToolInfo:
        return ToolInfo(name=name, status=ToolStatus.FOUND, path=Path(f"/usr/bin/{name}"))  # type: ignore[arg-type]

    return ToolSet(
        ffmpeg=info("ffmpeg"),
        ffprobe=info("ffprobe"),
        mkvpropedit=info("mkvpropedit"),
        mediainfo=info("mediainfo"),
    )


def _source() -> MediaSource:
    source: MediaSource = sc.make_source()
    return source


# --------------------------------------------------------------------------- no FFmpeg


@pytest.mark.parametrize(
    ("custom", "rest"),
    [
        ("cqm=/home/u/secret.cfg", ""),
        ("nr=100:cqm=/home/u/matrix.cfg", "nr=100"),
        ("cqm=FLAT", ""),  # x264 matches the names case-sensitively: a file named FLAT
        ("nocqm=flat", ""),  # x264 gets cqm=true: a file named true
        ("cqm=default", ""),
    ],
)
async def test_rc_1_the_dry_run_never_starts_ffmpeg_with_a_cqm_file(
    custom: str, rest: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def no_run(*args: Any, **kwargs: Any) -> RunResult:
        raise AssertionError("FFmpeg must not start")

    monkeypatch.setattr(dryrun, "run", no_run)
    job = _job(custom)
    issues = await dry_run(job, _source(), sc.make_caps(), _found_tools())
    assert [(i.code, i.severity, i.path) for i in issues] == [
        ("encoder.custom_param_file", Severity.ERROR, "video.custom_params")
    ]
    (fix,) = issues[0].fixes
    fixed = JobSettings.model_validate(apply_patch(job.model_dump(mode="json"), fix.patch))
    assert fixed.video.custom_params == rest


@pytest.mark.parametrize("custom", ["cqm=flat", "cqm=jvt", "nr=100:cqm=jvt"])
async def test_rc_1_the_matrix_presets_are_still_dry_run(
    custom: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    argvs: list[list[str]] = []

    async def fake_run(argv: list[str], **kwargs: Any) -> RunResult:
        argvs.append(argv)
        return RunResult(returncode=0, stdout=b"", stderr=b"frame=1\n", duration=0.1)

    monkeypatch.setattr(dryrun, "run", fake_run)
    assert await dry_run(_job(custom), _source(), sc.make_caps(), _found_tools()) == []
    (argv,) = argvs
    assert argv[argv.index("-x264-params:v:0") + 1].endswith(custom)


# --------------------------------------------------------------------------- real FFmpeg


@pytest.fixture
async def app(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Reframe:
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))  # the dry run's working folder
    return await Reframe.create(
        tmp_path / "config", tmp_path / "data", cache_dir=tmp_path / "cache"
    )


@pytest.mark.needs_ffmpeg
async def test_rc_1_planning_with_a_shared_preset_refuses_its_cqm_file(
    app: Reframe, fixture_media: FixtureMedia, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The reviewer's reproduction (``rc1_cqm_plan.py``): a user preset with
    ``cqm=<matrix file>``. Before the fix, ``plan(…, dry_run=True)`` returned a plan (the dry
    run's x264 read the file) and the encode applied it (``cqm=2`` in the output's SEI)."""
    if "flat" in str(tmp_path) or "jvt" in str(tmp_path):
        pytest.skip("x264 would take the temporary path for a matrix name")
    matrix = tmp_path / "matrix.cfg"
    await asyncio.to_thread(matrix.write_text, CQM_FILE)
    monkeypatch.chdir(tmp_path)
    try:
        draft = await app.jobs.draft(fixture_media("multitrack"), output=tmp_path / "out.mkv")
        assert not isinstance(draft, ProbeError)
        job = draft.job
        job.video.encoder = "libx264"
        job.video.preset = None
        job.video.tune = None
        job.video.profile = None
        job.video.level = None
        job.video.custom_params = f"cqm={matrix}"

        planned = await app.jobs.plan(job, dry_run=True)
        assert isinstance(planned, list)
        assert ("encoder.custom_param_file", "video.custom_params") in {
            (i.code, i.path) for i in planned
        }
        issues = await app.jobs.dry_run(job)
        assert [(i.code, i.path) for i in issues] == [
            ("encoder.custom_param_file", "video.custom_params")
        ]
        # What `reframe encode` checks before it queues the job.
        refused = await app.jobs.validate(job)
        assert ("encoder.custom_param_file", Severity.ERROR) in {
            (i.code, i.severity) for i in refused
        }

        # The presets still run: the one-frame encode passes.
        job.video.custom_params = "cqm=jvt"
        assert [i for i in await app.jobs.dry_run(job) if i.severity is Severity.ERROR] == []
    finally:
        await app.close()
