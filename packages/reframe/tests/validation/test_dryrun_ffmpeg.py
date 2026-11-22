"""The dry run: refused custom parameters never start FFmpeg, FFmpeg runs in a temporary folder,
and libvpx codec-control refusals and encoder warnings name the parameter they are about."""

from __future__ import annotations

import asyncio
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from reframe.jsonpatch import apply_patch
from reframe.models import (
    ConstantQuality,
    JobSettings,
    Severity,
    SourceRef,
    VideoSettings,
)
from reframe.probe import ProbeError
from reframe.service import Reframe
from reframe.tools import RunResult
from reframe.validation import dryrun
from reframe.validation.dryrun import dry_run, parse_dry_run

from . import scenario as sc

pytestmark = pytest.mark.anyio

FixtureMedia = Callable[[str], Path]
PRECIOUS = "precious user data\n"


def _job(**video: object) -> JobSettings:
    return JobSettings(
        source=SourceRef(path=Path("/media/in.mkv")),
        video=VideoSettings.model_validate({"encoder": "libx265", **video}),
    )


def _vp9(**video: object) -> JobSettings:
    return _job(
        encoder="libvpx-vp9",
        rate_control=ConstantQuality(value=30),
        preset=None,
        tune=None,
        profile=None,
        level=None,
        **video,
    )


FILE, UNKNOWN = "encoder.custom_param_file", "encoder.custom_param_unknown"


@pytest.mark.parametrize(
    ("job", "code", "rest"),
    [
        pytest.param(
            _job(custom_params="aq-mode=3:analysis-save=/home/u/victim.txt"),
            FILE,
            "aq-mode=3",
            id="analysis-save",
        ),
        pytest.param(_job(custom_params="csv=/home/u/log.csv"), FILE, "", id="csv"),
        pytest.param(
            _job(encoder="libx264", custom_params="dump-yuv=/home/u/frames.yuv"),
            FILE,
            "",
            id="dump-yuv",
        ),
        pytest.param(_vp9(custom_params="vstats_file=/home/u/v.log"), FILE, "", id="vstats_file"),
        pytest.param(_vp9(custom_params="bogus=1"), UNKNOWN, "", id="not-an-option"),
        pytest.param(
            _job(encoder="libx264", custom_params="cqm=/home/u/secret.cfg"), FILE, "", id="cqm"
        ),
        pytest.param(
            _job(encoder="libx264", custom_params="nr=100:cqm=/home/u/matrix.cfg"),
            FILE,
            "nr=100",
            id="cqm-after-nr",
        ),
        # x264 matches the names case-sensitively: a file named FLAT
        pytest.param(_job(encoder="libx264", custom_params="cqm=FLAT"), FILE, "", id="cqm-FLAT"),
        # x264 gets cqm=true: a file named true
        pytest.param(_job(encoder="libx264", custom_params="nocqm=flat"), FILE, "", id="cqm-nocqm"),
        pytest.param(
            _job(encoder="libx264", custom_params="cqm=default"), FILE, "", id="cqm-default"
        ),
    ],
)
async def test_a_refused_parameter_never_starts_ffmpeg(
    job: JobSettings, code: str, rest: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def no_run(*args: Any, **kwargs: Any) -> RunResult:
        raise AssertionError("FFmpeg must not start")

    monkeypatch.setattr(dryrun, "run", no_run)
    issues = await dry_run(job, sc.make_source(), sc.make_caps(), sc.make_tools())
    assert [(i.code, i.severity, i.path) for i in issues] == [
        (code, Severity.ERROR, "video.custom_params")
    ]
    (fix,) = issues[0].fixes
    fixed = JobSettings.model_validate(apply_patch(job.model_dump(mode="json"), fix.patch))
    assert fixed.video.custom_params == rest


async def test_ffmpeg_runs_in_a_temporary_folder_that_is_removed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """x264 / x265 ``pass=1`` write ``x26?_2pass.log`` into the working folder: the dry run
    gives FFmpeg a new folder of its own and removes it, with what FFmpeg wrote."""
    seen: list[Path | None] = []

    async def fake_run(argv: list[str], **kwargs: Any) -> RunResult:
        cwd = kwargs.get("cwd")
        seen.append(cwd)
        assert cwd is not None
        await asyncio.to_thread((cwd / "x265_2pass.log").write_text, "written by the encoder")
        return RunResult(returncode=0, stdout=b"", stderr=b"frame=1\n", duration=0.1)

    monkeypatch.setattr(dryrun, "run", fake_run)
    monkeypatch.chdir(tmp_path)
    work = tmp_path / "work"
    work.mkdir()
    issues = await dry_run(
        _job(custom_params="aq-mode=3"),
        sc.make_source(),
        sc.make_caps(),
        sc.make_tools(),
        work_dir=work,
    )
    assert issues == []
    (cwd,) = seen
    assert cwd is not None
    assert cwd.parent == work
    assert not await asyncio.to_thread(cwd.exists)
    assert await asyncio.to_thread(lambda: list(work.iterdir())) == []
    assert await asyncio.to_thread(lambda: [p.name for p in tmp_path.iterdir()]) == ["work"]


async def test_a_relative_source_is_given_to_ffmpeg_as_an_absolute_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    argvs: list[list[str]] = []

    async def fake_run(argv: list[str], **kwargs: Any) -> RunResult:
        argvs.append(argv)
        return RunResult(returncode=0, stdout=b"", stderr=b"", duration=0.1)

    monkeypatch.setattr(dryrun, "run", fake_run)
    monkeypatch.chdir(tmp_path)
    job = _job()
    job.source = SourceRef(path=Path("in.mkv"))
    await dry_run(job, sc.make_source(), sc.make_caps(), sc.make_tools(), work_dir=tmp_path)
    (argv,) = argvs
    assert argv[argv.index("-i") + 1] == str(tmp_path / "in.mkv")


@pytest.fixture
async def app(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Reframe:
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))  # the dry run's working folder
    return await Reframe.create(
        tmp_path / "config", tmp_path / "data", cache_dir=tmp_path / "cache"
    )


async def _draft(app: Reframe, path: Path, tmp_path: Path) -> JobSettings:
    draft = await app.jobs.draft(path, output=tmp_path / "out.mkv")
    assert not isinstance(draft, ProbeError)
    return draft.job


@pytest.mark.needs_ffmpeg
@pytest.mark.parametrize(
    ("encoder", "custom"),
    [
        ("libx265", "analysis-save={victim}"),
        ("libx265", "csv={victim}"),
        ("libx264", "dump-yuv={victim}"),
        ("libvpx-vp9", "vstats_file={victim}"),
    ],
)
async def test_planning_with_a_shared_preset_leaves_the_users_file_alone(
    app: Reframe,
    fixture_media: FixtureMedia,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    encoder: str,
    custom: str,
) -> None:
    victim = tmp_path / "victim.txt"
    victim.write_text(PRECIOUS)
    monkeypatch.chdir(tmp_path)
    try:
        job = await _draft(app, fixture_media("multitrack"), tmp_path)
        job.video.encoder = encoder
        job.video.preset = None
        job.video.tune = None
        job.video.profile = None
        job.video.level = None
        if encoder == "libvpx-vp9":
            job.video.rate_control = ConstantQuality(value=30)
        job.video.custom_params = custom.format(victim=victim)

        planned = await app.jobs.plan(job, dry_run=True)
        assert isinstance(planned, list)
        assert ("encoder.custom_param_file", "video.custom_params") in {
            (i.code, i.path) for i in planned
        }
        issues = await app.jobs.dry_run(job)
        assert [(i.code, i.path) for i in issues] == [
            ("encoder.custom_param_file", "video.custom_params")
        ]
        fixed = JobSettings.model_validate(
            apply_patch(job.model_dump(mode="json"), issues[0].fixes[0].patch)
        )
        assert fixed.video.custom_params == ""
    finally:
        await app.close()
    assert await asyncio.to_thread(victim.read_text) == PRECIOUS
    # Nothing else was written (no x265_2pass.log, no dry-run folder left).
    names = await asyncio.to_thread(lambda: {p.name for p in tmp_path.iterdir()})
    assert names <= {"cache", "config", "data", "victim.txt"}


ARNR_STDERR = (
    "[libvpx-vp9 @ 0x5616] v1.17.0\n"
    "[libvpx-vp9 @ 0x5616] Failed to set VP8E_SET_ARNR_MAXFRAMES codec control: Invalid "
    "parameter\n"
    "[libvpx-vp9 @ 0x5616]   Additional information: arnr_max_frames out of range [0..15]\n"
    "frame=    1 fps=0.0 q=0.0 Lsize=N/A time=00:00:00.04 bitrate=N/A speed=0.5x\n"
)


def test_a_value_libvpx_refuses_through_a_codec_control_is_an_error() -> None:
    job = _vp9(custom_params="lag-in-frames=16:arnr-maxframes=16")
    issues = parse_dry_run(job, ARNR_STDERR, 0)
    assert [(i.severity, i.code, i.path) for i in issues] == [
        (Severity.ERROR, "encoder.custom_param_rejected", "video.custom_params")
    ]
    assert "arnr_max_frames out of range [0..15]" in issues[0].message
    (fix,) = issues[0].fixes
    fixed = JobSettings.model_validate(apply_patch(job.model_dump(mode="json"), fix.patch))
    assert fixed.video.custom_params == "lag-in-frames=16"


def test_a_control_that_names_no_parameter() -> None:
    stderr = "[libvpx-vp9 @ 0x1] Failed to set VP9E_SET_COLOR_SPACE codec control: Invalid\n"
    issues = parse_dry_run(_vp9(custom_params="lag-in-frames=16"), stderr, 0)
    assert [(i.code, i.path) for i in issues] == [("encoder.dry_run_failed", "video.custom_params")]
    assert dryrun.control_names("VP8E_SET_CPUUSED") == ["cpu-used", "cpuused"]
    assert dryrun.control_names("VP9E_SET_MIN_GF_INTERVAL") == ["min-gf-interval"]


@pytest.mark.needs_ffmpeg
@pytest.mark.parametrize(
    ("custom", "info"),
    [
        ("arnr-maxframes=16", "arnr_max_frames out of range [0..15]"),
        ("arnr-strength=7", "arnr_strength out of range"),
        ("min-gf-interval=40", "min_gf_interval out of range"),
    ],
)
async def test_the_real_libvpx_codec_control_refusals(
    app: Reframe, fixture_media: FixtureMedia, tmp_path: Path, custom: str, info: str
) -> None:
    try:
        job = await _draft(app, fixture_media("multitrack"), tmp_path)
        vp9 = _vp9(custom_params=custom)
        job.video = vp9.video
        issues = await app.jobs.dry_run(job)
    finally:
        await app.close()
    assert [(i.code, i.path) for i in issues] == [
        ("encoder.custom_param_rejected", "video.custom_params")
    ]
    assert info in issues[0].message


@pytest.mark.needs_ffmpeg
async def test_the_real_libvpx_failure_says_what_libvpx_refused(
    app: Reframe, fixture_media: FixtureMedia, tmp_path: Path
) -> None:
    try:
        job = await _draft(app, fixture_media("multitrack"), tmp_path)
        job.video = _vp9(custom_params="maxrate=100k").video
        issues = await app.jobs.dry_run(job)
    finally:
        await app.close()
    assert [(i.code, i.path) for i in issues] == [("encoder.dry_run_failed", "video.custom_params")]
    assert issues[0].message.endswith("Rate control parameters set without a bitrate")


VBV_MAXRATE = "video.advanced.vbv-maxrate"


@pytest.mark.needs_ffmpeg
@pytest.mark.parametrize(
    ("encoder", "custom", "advanced", "validation_says", "dry_run_says"),
    [
        (
            "libx264",
            "vbv-maxrate=1000",
            {},
            [("encoder.custom_param_overrides", VBV_MAXRATE)],
            [("encoder.dry_run_warning", "video.custom_params")],
        ),
        ("libx264", "", {"vbv-maxrate": 1000}, [("encoder.option_inactive", VBV_MAXRATE)], []),
        ("libx265", "", {"vbv-maxrate": 1000}, [("encoder.option_inactive", VBV_MAXRATE)], []),
        (
            "libx265",
            "",
            {"limit-refs": "2", "pmode": True},
            [("encoder.option_ignored", "video.advanced.limit-refs")],
            [],
        ),
    ],
    ids=["x264-custom", "x264-advanced", "x265-advanced", "x265-limit-refs-pmode"],
)
async def test_each_real_encoder_warning_is_one_issue(
    app: Reframe,
    fixture_media: FixtureMedia,
    tmp_path: Path,
    encoder: str,
    custom: str,
    advanced: dict[str, Any],
    validation_says: list[tuple[str, str]],
    dry_run_says: list[tuple[str, str]],
) -> None:
    try:
        job = await _draft(app, fixture_media("multitrack"), tmp_path)
        job.video.encoder = encoder
        job.video.preset = None
        job.video.tune = None
        job.video.profile = None
        job.video.level = None
        job.video.custom_params = custom
        job.video.advanced = advanced
        validated = await app.jobs.validate(job)
        issues = await app.jobs.dry_run(job)
    finally:
        await app.close()
    assert [(i.code, i.path) for i in validated if i.code.startswith("encoder.")] == (
        validation_says
    )
    assert [(i.code, i.path) for i in issues] == dry_run_says


RD_REFINE = (
    "x265 [warning]: --rd-refine disabled, requires RD level > 4 and adaptive quant\n"
    "x265 [warning]: Source height < 720p; disabling lookahead-slices\n"
)


def test_a_warning_goes_to_the_key_it_names_not_to_a_short_key_in_its_text() -> None:
    """The warning is about ``rd-refine``, not ``rd``: the text also contains "RD level"."""
    job = _job(custom_params="rd=3:rd-refine=1")
    (issue,) = parse_dry_run(job, RD_REFINE, 0)
    assert (issue.severity, issue.code) == (Severity.WARNING, "encoder.dry_run_warning")
    assert [f.label for f in issue.fixes] == ["Remove rd-refine=1 from the custom parameters"]

    job = _job(advanced={"rd": 3, "rd-refine": True})
    (issue,) = parse_dry_run(job, RD_REFINE, 0)
    assert issue.path == "video.advanced.rd-refine"
    # The looser form still names a key the text spells differently.
    job = _job(custom_params="rd=3")
    (issue,) = parse_dry_run(job, RD_REFINE, 0)
    assert [f.label for f in issue.fixes] == ["Remove rd=3 from the custom parameters"]


@pytest.mark.needs_ffmpeg
async def test_the_real_rd_refine_warning(
    app: Reframe, fixture_media: FixtureMedia, tmp_path: Path
) -> None:
    try:
        job = await _draft(app, fixture_media("multitrack"), tmp_path)
        job.video.encoder = "libx265"
        job.video.custom_params = "rd=3:rd-refine=1"
        issues = await app.jobs.dry_run(job)
    finally:
        await app.close()
    assert [(i.code, [f.label for f in i.fixes]) for i in issues] == [
        ("encoder.dry_run_warning", ["Remove rd-refine=1 from the custom parameters"])
    ]
