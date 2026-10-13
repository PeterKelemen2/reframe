"""The hardware test encode (05 §C-4): its command (pure) and one run.

The command, as checked on real hardware (``testdata/README.md`` §Hardware setup of the
encoder definitions and §Encoder detection)::

    ffmpeg -hide_banner -nostdin [init_args] -f lavfi -i color=size=640x360 -frames:v 3
           (-vf <filter_tail> | -pix_fmt <sw_pix_fmt>) -c:v <encoder> -f null -

- ``init_args`` and ``filter_tail`` come from the encoder's ``hardware_setup``
  (``-init_hw_device vaapi=va:{vaapi_device} -filter_hw_device va`` and
  ``format={sw_pix_fmt},hwupload`` for VAAPI). Placeholders: ``{vaapi_device}`` (default
  ``/dev/dri/renderD128``) and ``{sw_pix_fmt}`` (the encoder's ``pix_fmts`` for the bit depth).
- Without a filter tail (NVENC, AMF: software frames), ``-pix_fmt <sw_pix_fmt>``.
- The 10-bit test is the same command with ``pix_fmts["10"]``.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from reframe.capabilities.reasons import Failure, TestContext, explain_failure
from reframe.definitions import VideoEncoderDef
from reframe.models.capabilities import EncoderState
from reframe.tools import CancelToken, run

__all__ = [
    "DEFAULT_VAAPI_DEVICE",
    "TEST_FRAMES",
    "TEST_MAX_OUTPUT",
    "TEST_SOURCE",
    "TEST_TIMEOUT",
    "BitDepth",
    "DefinitionError",
    "TestOutcome",
    "hardware_test_argv",
    "resolve_placeholders",
    "run_hardware_test",
]

DEFAULT_VAAPI_DEVICE = "/dev/dri/renderD128"
TEST_SOURCE = "color=size=640x360"
TEST_FRAMES = 3
#: Seconds for one test encode (02 §Cross-cutting rules: "short timeout (10 s default)").
TEST_TIMEOUT = 10.0
#: Bytes of output kept from a test encode (a few kB in practice).
TEST_MAX_OUTPUT = 2**20

BitDepth = Literal["8", "10"]
_PLACEHOLDER = re.compile(r"\{(\w+)\}")


class DefinitionError(ValueError):
    """The encoder definition cannot make a test command (unknown placeholder, no pixel
    format for the bit depth). The C-6 definitions linter should catch it first."""


def resolve_placeholders(arg: str, values: Mapping[str, str]) -> str:
    """Replace ``{name}`` in ``arg``; an unknown name raises :class:`DefinitionError`."""

    def replace(match: re.Match[str]) -> str:
        name = match[1]
        if name not in values:
            raise DefinitionError(f"unknown placeholder {{{name}}} in {arg!r}")
        return values[name]

    return _PLACEHOLDER.sub(replace, arg)


def hardware_test_argv(
    ffmpeg: str | Path,
    encoder: VideoEncoderDef,
    bit_depth: BitDepth = "8",
    *,
    vaapi_device: str = DEFAULT_VAAPI_DEVICE,
) -> list[str]:
    """The test encode command for ``encoder`` at ``bit_depth``. Pure."""
    sw_pix_fmt = encoder.pix_fmts.get(bit_depth)
    if sw_pix_fmt is None:
        raise DefinitionError(f"{encoder.id} has no pixel format for {bit_depth}-bit")
    values = {"vaapi_device": vaapi_device, "sw_pix_fmt": sw_pix_fmt}
    setup = encoder.hardware_setup
    init_args = [resolve_placeholders(a, values) for a in setup.init_args] if setup else []
    tail = [resolve_placeholders(f, values) for f in setup.filter_tail] if setup else []
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
    duration: float = 0.0
    argv: tuple[str, ...] = ()


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
    """Run one test encode and explain a failure. Never raises for FFmpeg problems."""
    try:
        argv = hardware_test_argv(ffmpeg, encoder, bit_depth, vaapi_device=vaapi_device)
    except DefinitionError as exc:
        reason = f"The encoder definition is broken: {exc}"
        return TestOutcome(ok=False, failure=Failure(EncoderState.ERROR, reason))
    result = await run(
        argv, timeout=timeout, cancel=cancel, max_output=TEST_MAX_OUTPUT, extra_env=extra_env
    )

    def outcome(failure: Failure | None = None, *, cancelled: bool = False) -> TestOutcome:
        ok = failure is None and not cancelled
        return TestOutcome(ok, failure, cancelled, result.duration, tuple(argv))

    if result.cancelled:
        return outcome(cancelled=True)
    if result.error is not None:
        return outcome(Failure(EncoderState.ERROR, f"FFmpeg could not be started: {result.error}"))
    if result.timed_out:
        reason = f"The test encode did not finish within {timeout:g} s"
        return outcome(Failure(EncoderState.ERROR, reason))
    if result.returncode == 0:
        return outcome()
    device = vaapi_device if encoder.family == "vaapi" else None
    ctx = TestContext(
        encoder=encoder.id, family=encoder.family, codec_label=encoder.codec_label, device=device
    )
    return outcome(explain_failure(result.stderr_text, ctx, returncode=result.returncode))
