"""The advanced options through the facade: the option search, Copy HDR metadata on the HDR10
fixture, and the dry run of custom parameters through ``Reframe.jobs``."""

from __future__ import annotations

import re
import subprocess
from collections.abc import Callable
from pathlib import Path

import pytest

from reframe.definitions import load_definitions
from reframe.jsonpatch import apply_patch
from reframe.models import EncodePlan, JobSettings, MediaSource, Severity
from reframe.probe import ProbeError
from reframe.service import Reframe

pytestmark = pytest.mark.anyio

FixtureMedia = Callable[[str], Path]


@pytest.fixture
async def app(tmp_path: Path) -> Reframe:
    return await Reframe.create(
        tmp_path / "config", tmp_path / "data", cache_dir=tmp_path / "cache"
    )


async def test_search_psy_finds_psy_rd_and_psy_rdoq(app: Reframe) -> None:
    try:
        found = [o.key for o in app.jobs.search_options("libx265", "psy")]
        assert found[:2] == ["psy-rd", "psy-rdoq"]
        assert next(o.key for o in app.jobs.search_options("libx265", "PSY-RDOQ")) == "psy-rdoq"
        assert [o.key for o in app.jobs.search_options("hevc_nvenc", "-bf")] == ["bf"]
        assert app.jobs.search_options("no-such-encoder", "psy") == []
        everything = app.jobs.search_options("libx264", "  ")
        assert everything == app.jobs.definitions.video_encoders["libx264"].options
    finally:
        await app.close()


def _fixture_hdr10() -> tuple[str, str]:
    """master-display and max-cll as ``testing/reframe_testing/media.py`` made the fixture."""
    from reframe_testing import media

    params = dict(item.split("=", 1) for item in media._X265_HDR10.split(":"))
    return params["master-display"], params["max-cll"]


async def _probe(app: Reframe, path: Path) -> MediaSource:
    media = await app.sources.probe(path)
    assert not isinstance(media, ProbeError), media
    return media


async def _draft(app: Reframe, path: Path, tmp_path: Path) -> JobSettings:
    draft = await app.jobs.draft(path, output=tmp_path / "out.mkv")
    assert not isinstance(draft, ProbeError)
    return draft.job


def _encode(ffmpeg: str, source: Path, out: Path, encoder: str, params: str) -> None:
    params_arg = load_definitions().video_encoders[encoder].params_arg
    assert params_arg is not None
    argv = [ffmpeg, "-hide_banner", "-nostdin", "-y", "-i", str(source), "-frames:v", "3",
            "-map", "0:v:0", "-pix_fmt", "yuv420p10le", "-c:v", encoder]  # fmt: skip
    argv += ["-preset", "10"] if encoder == "libsvtav1" else ["-preset", "ultrafast"]
    argv += [params_arg, params, str(out)]
    result = subprocess.run(argv, capture_output=True, text=True, timeout=120, check=False)
    assert result.returncode == 0, result.stderr[-1500:]
    assert not re.search(r"Error parsing option|Unknown option|Invalid value", result.stderr)


@pytest.mark.needs_ffmpeg
async def test_copy_hdr_metadata_fills_master_display_and_max_cll(
    app: Reframe, fixture_media: FixtureMedia, tmp_path: Path
) -> None:
    from reframe_testing import media

    path = fixture_media("hdr10")
    try:
        source = await _probe(app, path)
        job = await _draft(app, path, tmp_path)
        job.video.encoder = "libx265"
        patch = app.jobs.hdr_metadata(job, source)
        assert [(op.op, op.path) for op in patch] == [
            ("add", "/video/advanced/master-display"),
            ("add", "/video/advanced/max-cll"),
        ]
        patched = JobSettings.model_validate(apply_patch(job.model_dump(mode="json"), patch))
        master, cll = _fixture_hdr10()
        assert patched.video.advanced == {
            **job.video.advanced,
            "master-display": master,
            "max-cll": cll,
        }

        ffmpeg = media.find_ffmpeg()
        assert ffmpeg is not None
        x265_out = tmp_path / "x265.mkv"
        values = patched.video.advanced
        x265_params = f"master-display={values['master-display']}:max-cll={values['max-cll']}"
        _encode(ffmpeg, path, x265_out, "libx265", x265_params)
        encoded = await _probe(app, x265_out)
        assert source.video[0].hdr is not None
        assert encoded.video[0].hdr is not None
        assert encoded.video[0].hdr.mastering_display == source.video[0].hdr.mastering_display
        assert encoded.video[0].hdr.content_light == source.video[0].hdr.content_light

        job.video.encoder = "libsvtav1"
        svt = {
            op.path.rsplit("/", 1)[1]: op.value  # type: ignore[union-attr]
            for op in app.jobs.hdr_metadata(job, source)
        }
        assert svt == {
            "mastering-display": "G(0.265,0.69)B(0.15,0.06)R(0.68,0.32)WP(0.3127,0.329)"
            "L(1000,0.0001)",
            "content-light": "1000,400",
        }
        svt_out = tmp_path / "svt.mkv"
        svt_params = (
            f"mastering-display={svt['mastering-display']}:content-light={svt['content-light']}"
        )
        _encode(ffmpeg, path, svt_out, "libsvtav1", svt_params)
        av1 = (await _probe(app, svt_out)).video[0].hdr
        assert av1 is not None
        assert av1.content_light == source.video[0].hdr.content_light
        md = av1.mastering_display
        assert md is not None
        # AV1 stores chromaticities in 1/65536 and luminance in 1/256 (max) and 1/16384 (min).
        expected = source.video[0].hdr.mastering_display
        assert expected is not None
        assert md.red_x == pytest.approx(expected.red_x, abs=1 / 65536)
        assert md.white_y == pytest.approx(expected.white_y, abs=1 / 65536)
        assert md.max_luminance == pytest.approx(expected.max_luminance, abs=1 / 256)
        assert md.min_luminance == pytest.approx(expected.min_luminance, abs=1 / 16384)

        job.video.encoder = "libx264"
        assert app.jobs.hdr_metadata(job, source) == []
    finally:
        await app.close()


@pytest.mark.needs_ffmpeg
async def test_no_hdr_metadata_on_an_sdr_source(
    app: Reframe, fixture_media: FixtureMedia, tmp_path: Path
) -> None:
    path = fixture_media("multitrack")
    try:
        source = await _probe(app, path)
        job = await _draft(app, path, tmp_path)
        job.video.encoder = "libx265"
        assert app.jobs.hdr_metadata(job, source) == []
    finally:
        await app.close()


@pytest.mark.needs_ffmpeg
async def test_an_unsupported_custom_parameter_fails_the_dry_run(
    app: Reframe, fixture_media: FixtureMedia, tmp_path: Path
) -> None:
    """x265 only logs it and exits with 0; the dry run reads the log."""
    path = fixture_media("multitrack")
    try:
        job = await _draft(app, path, tmp_path)
        job.video.encoder = "libx265"
        job.video.custom_params = "ref=3:no-such-param=1"
        issues = await app.jobs.dry_run(job)
        assert [(i.severity, i.code, i.path) for i in issues] == [
            (Severity.ERROR, "encoder.custom_param_rejected", "video.custom_params")
        ]
        assert "Unknown option: no-such-param" in issues[0].message
        fixed = JobSettings.model_validate(
            apply_patch(job.model_dump(mode="json"), issues[0].fixes[0].patch)
        )
        assert fixed.video.custom_params == "ref=3"
        assert await app.jobs.dry_run(fixed) == []

        planned = await app.jobs.plan(job, dry_run=True)
        assert isinstance(planned, list)
        assert ("encoder.custom_param_rejected", "video.custom_params") in {
            (i.code, i.path) for i in planned
        }
        assert isinstance(await app.jobs.plan(job), EncodePlan)
        assert isinstance(await app.jobs.plan(fixed, dry_run=True), EncodePlan)
    finally:
        await app.close()


@pytest.mark.needs_ffmpeg
@pytest.mark.parametrize(
    ("encoder", "custom", "code"),
    [
        ("libx264", "bogus=1", "encoder.custom_param_rejected"),
        ("libsvtav1", "bogus=1", "encoder.custom_param_rejected"),
        # Not an option of libvpx-vp9: refused before FFmpeg starts.
        ("libvpx-vp9", "bogus=1", "encoder.custom_param_unknown"),
        # libvpx refuses the value through a codec control and goes on (exit code 0).
        ("libvpx-vp9", "arnr-maxframes=16", "encoder.custom_param_rejected"),
        # libvpx names its own field ("g_lag_in_frames out of range"): not attributed.
        ("libvpx-vp9", "lag-in-frames=26", "encoder.dry_run_failed"),
        ("libsvtav1", "film-grain=99", "encoder.custom_param_rejected"),
    ],
)
async def test_the_dry_run_of_each_software_encoder(
    app: Reframe, fixture_media: FixtureMedia, tmp_path: Path, encoder: str, custom: str, code: str
) -> None:
    path = fixture_media("multitrack")
    try:
        job = await _draft(app, path, tmp_path)
        job.video.encoder = encoder
        job.video.preset = None
        job.video.tune = None
        job.video.profile = None
        job.video.level = None
        job.video.custom_params = custom
        issues = await app.jobs.dry_run(job)
        assert [(i.code, i.path) for i in issues] == [(code, "video.custom_params")], issues
        job.video.custom_params = ""
        assert await app.jobs.dry_run(job) == []
    finally:
        await app.close()
