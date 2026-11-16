"""The hardware and filter test encodes: the command (pure) and one run of it.

The command lines and the FFmpeg output that the checks rely on are recorded in
``testdata/README.md`` (section "Encoder detection").
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from reframe.capabilities.reasons import Failure, TestContext, explain_failure, normalise_line
from reframe.definitions import DEFAULT_VAAPI_DEVICE, VideoEncoderDef
from reframe.definitions.models import BitDepth
from reframe.models.capabilities import EncoderState
from reframe.tools import CancelToken, run

__all__ = [
    "FILTER_TESTS",
    "TEST_FRAMES",
    "TEST_MAX_OUTPUT",
    "TEST_SOURCE",
    "TEST_TIMEOUT",
    "TestOutcome",
    "filter_test_argv",
    "hardware_test_argv",
    "run_filter_test",
    "run_hardware_test",
    "uses_vaapi_device",
]

TEST_SOURCE = "color=size=640x360"
TEST_FRAMES = 3
#: Seconds for one test encode.
TEST_TIMEOUT = 10.0
#: Bytes of output kept from a test encode.
TEST_MAX_OUTPUT = 2**20

_VAAPI_PLACEHOLDER = "{vaapi_device}"
#: FFmpeg replaced a ``-pix_fmt`` that the encoder does not take (and then exits 0).
_AUTO_SELECTED = re.compile(
    r"Incompatible pixel format '(?P<asked>[^']+)' for codec '[^']+', "
    r"auto-selecting format '(?P<picked>[^']+)'"
)

#: Filters that ``ffmpeg -filters`` lists but that need a run test: ``libplacebo`` needs a
#: working Vulkan device.
FILTER_TESTS = ("libplacebo",)


def uses_vaapi_device(encoder: VideoEncoderDef) -> bool:
    """The hardware setup names ``{vaapi_device}``: the encoder runs on a render node."""
    setup = encoder.hardware_setup
    if setup is None:
        return False
    return any(_VAAPI_PLACEHOLDER in arg for arg in (*setup.init_args, *setup.filter_tail))


def hardware_test_argv(
    ffmpeg: str | Path,
    encoder: VideoEncoderDef,
    bit_depth: BitDepth = "8",
    *,
    vaapi_device: str = DEFAULT_VAAPI_DEVICE,
) -> list[str]:
    """The test encode command for ``encoder`` at ``bit_depth``. Pure."""
    sw_pix_fmt = encoder.pix_fmts[bit_depth]
    values = {"vaapi_device": vaapi_device, "sw_pix_fmt": sw_pix_fmt}
    setup = encoder.hardware_setup
    init_args, tail = setup.resolve(values) if setup else ([], [])
    frames = ["-vf", ",".join(tail)] if tail else ["-pix_fmt", sw_pix_fmt]
    return [
        str(ffmpeg),
        "-hide_banner",
        "-nostdin",
        *init_args,
        "-f",
        "lavfi",
        "-i",
        TEST_SOURCE,
        "-frames:v",
        str(TEST_FRAMES),
        *frames,
        "-c:v",
        encoder.id,
        "-f",
        "null",
        "-",
    ]


@dataclass(frozen=True)
class TestOutcome:
    """The result of one test encode."""

    __test__ = False  # not a pytest test class

    ok: bool
    failure: Failure | None = None
    """Why it failed (``None`` when it worked, or when it was cancelled)."""
    cancelled: bool = False
    argv: tuple[str, ...] = ()


def filter_test_argv(ffmpeg: str | Path, name: str) -> list[str]:
    """The run test of the filter ``name`` (one of :data:`FILTER_TESTS`). Pure."""
    if name not in FILTER_TESTS:
        raise ValueError(f"no run test for the filter {name!r}")
    return [
        str(ffmpeg),
        "-hide_banner",
        "-nostdin",
        "-f",
        "lavfi",
        "-i",
        TEST_SOURCE,
        "-frames:v",
        "1",
        "-vf",
        name,
        "-f",
        "null",
        "-",
    ]


def _replaced_pix_fmt(stderr: str, encoder_id: str) -> Failure | None:
    """A failure when FFmpeg encoded with another pixel format than the ``-pix_fmt`` it was
    given (FFmpeg names the canonical format: ``p010`` is ``p010le`` here)."""
    for line in stderr.splitlines():
        match = _AUTO_SELECTED.search(line)
        if match is not None:
            reason = (
                f"{encoder_id} does not take {match['asked']} in this FFmpeg build "
                f"(it got {match['picked']})"
            )
            return Failure(EncoderState.UNAVAILABLE, reason, detail=normalise_line(line))
    return None


async def _run_test(
    argv: list[str],
    ctx: TestContext,
    *,
    what: str,
    timeout: float,  # noqa: ASYNC109 - passed to run()
    cancel: CancelToken | None,
    extra_env: Mapping[str, str] | None,
    exact_pix_fmt: bool = False,
) -> TestOutcome:
    """Run one test. ``exact_pix_fmt``: the test also fails when FFmpeg replaced the pixel
    format it was given."""
    result = await run(
        argv, timeout=timeout, cancel=cancel, max_output=TEST_MAX_OUTPUT, extra_env=extra_env
    )

    def outcome(failure: Failure | None = None, *, cancelled: bool = False) -> TestOutcome:
        ok = failure is None and not cancelled
        return TestOutcome(ok, failure, cancelled, tuple(argv))

    if result.cancelled:
        return outcome(cancelled=True)
    if result.error is not None:
        return outcome(Failure(EncoderState.ERROR, f"FFmpeg could not be started: {result.error}"))
    if result.timed_out:
        reason = f"{what} did not finish within {timeout:g} s"
        return outcome(Failure(EncoderState.ERROR, reason))
    if result.returncode == 0:
        if not exact_pix_fmt:
            return outcome()
        return outcome(_replaced_pix_fmt(result.stderr_text, ctx.encoder))
    return outcome(explain_failure(result.stderr_text, ctx, returncode=result.returncode))


async def run_hardware_test(
    ffmpeg: str | Path,
    encoder: VideoEncoderDef,
    bit_depth: BitDepth = "8",
    *,
    vaapi_device: str = DEFAULT_VAAPI_DEVICE,
    timeout: float = TEST_TIMEOUT,  # noqa: ASYNC109 - passed to run()
    cancel: CancelToken | None = None,
    extra_env: Mapping[str, str] | None = None,
) -> TestOutcome:
    """Run one test encode and explain a failure. Never raises for FFmpeg problems. The
    10-bit test also fails when FFmpeg replaced the 10-bit pixel format (exit code 0)."""
    argv = hardware_test_argv(ffmpeg, encoder, bit_depth, vaapi_device=vaapi_device)
    ctx = TestContext(
        encoder=encoder.id,
        family=encoder.family,
        codec_label=encoder.codec_label,
        device=vaapi_device if uses_vaapi_device(encoder) else None,
    )
    return await _run_test(
        argv,
        ctx,
        what="The test encode",
        timeout=timeout,
        cancel=cancel,
        extra_env=extra_env,
        exact_pix_fmt=bit_depth == "10",
    )


async def run_filter_test(
    ffmpeg: str | Path,
    name: str,
    *,
    timeout: float = TEST_TIMEOUT,  # noqa: ASYNC109 - passed to run()
    cancel: CancelToken | None = None,
    extra_env: Mapping[str, str] | None = None,
) -> TestOutcome:
    """Run one frame through the filter ``name`` and explain a failure. Never raises for
    FFmpeg problems."""
    ctx = TestContext(encoder=name, family="filter")
    return await _run_test(
        filter_test_argv(ffmpeg, name),
        ctx,
        what=f"The {name} test",
        timeout=timeout,
        cancel=cancel,
        extra_env=extra_env,
    )
