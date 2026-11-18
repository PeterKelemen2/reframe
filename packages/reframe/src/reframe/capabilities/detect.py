"""One encoder detection run: list, help and hardware tests. No cache, no service state.

``on_update`` gets the statuses that changed, as soon as they change. Nothing here raises for
an FFmpeg problem: a missing, old or broken FFmpeg gives ``unavailable`` statuses with the
tool's reason.
"""

from __future__ import annotations

import asyncio
import logging
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from reframe.capabilities.devices import render_nodes
from reframe.capabilities.hwtest import (
    FILTER_TESTS,
    TEST_TIMEOUT,
    TestOutcome,
    run_filter_test,
    run_hardware_test,
    uses_vaapi_device,
)
from reframe.capabilities.parse import (
    EncoderHelp,
    parse_encoder_help,
    parse_encoders,
    parse_filters,
)
from reframe.capabilities.reasons import normalise_line
from reframe.definitions import DEFAULT_VAAPI_DEVICE, Definitions, OperatingSystem, VideoEncoderDef
from reframe.definitions.models import BitDepth
from reframe.models.capabilities import CapabilitySnapshot, EncoderState, EncoderStatus
from reframe.models.tools import ToolInfo, ToolStatus
from reframe.tools import CancelToken, RunResult, run

__all__ = [
    "LIST_TIMEOUT",
    "MAX_PARALLEL_HELP",
    "MAX_PARALLEL_TESTS",
    "NOT_IN_BUILD",
    "DetectionOptions",
    "StatusCallback",
    "current_os",
    "detect_capabilities",
    "initial_statuses",
    "unusable_snapshot",
    "vaapi_nodes",
]

log = logging.getLogger(__name__)

#: Seconds for each FFmpeg list call. Generous for a first start from a slow disk; the calls
#: take about 10 ms otherwise.
LIST_TIMEOUT = 20.0
#: Hardware test encodes running at the same time.
MAX_PARALLEL_TESTS = 3
MAX_PARALLEL_HELP = 4
NOT_IN_BUILD = "Not in this FFmpeg build"
_OS_NAMES: dict[OperatingSystem, str] = {"linux": "Linux", "windows": "Windows", "macos": "macOS"}

#: Called with the statuses that changed (never empty).
StatusCallback = Callable[[list[EncoderStatus]], None]


def current_os(platform: str | None = None) -> OperatingSystem:
    """``linux`` / ``windows`` / ``macos`` for a ``sys.platform`` value (default: this one)."""
    platform = sys.platform if platform is None else platform
    if platform == "win32":
        return "windows"
    if platform == "darwin":
        return "macos"
    return "linux"


@dataclass(frozen=True)
class DetectionOptions:
    """How a detection runs."""

    hardware_tests: bool = True
    """Off: the hardware encoders stay ``unknown``."""
    os: OperatingSystem | None = None
    """The OS for the definitions' ``platforms`` (default: this one)."""
    vaapi_device: str | None = None
    """Test VAAPI only on this render node. ``None`` or empty: test every node (see
    :attr:`render_nodes`)."""
    render_nodes: tuple[str, ...] | None = None
    """The render nodes to try, in order; ``None``: list ``/dev/dri/renderD*`` when a VAAPI
    encoder is tested (:func:`reframe.capabilities.devices.render_nodes`)."""
    test_timeout: float = TEST_TIMEOUT
    list_timeout: float = LIST_TIMEOUT


def _now() -> datetime:
    return datetime.now(UTC)


def vaapi_nodes(options: DetectionOptions) -> list[str]:
    """The render nodes to test VAAPI encoders on: the forced one, else
    :attr:`DetectionOptions.render_nodes`, else ``/dev/dri/renderD*`` (blocking: lists a
    folder)."""
    forced = (options.vaapi_device or "").strip()
    if forced:
        return [forced]
    if options.render_nodes is not None:
        return list(options.render_nodes)
    return render_nodes()


def initial_statuses(
    definitions: Definitions, state: EncoderState = EncoderState.UNKNOWN
) -> dict[str, EncoderStatus]:
    """Every video and audio encoder of the definitions in ``state`` (no reason)."""
    statuses = {
        enc.id: EncoderStatus(id=enc.id, state=state, hardware=enc.hardware)
        for enc in definitions.video_encoders.values()
    }
    for audio in definitions.audio_encoders.values():
        statuses.setdefault(audio.id, EncoderStatus(id=audio.id, state=state))
    return statuses


def unusable_snapshot(
    ffmpeg: ToolInfo, definitions: Definitions, *, now: datetime | None = None
) -> CapabilitySnapshot:
    """Every encoder ``unavailable`` because ffmpeg is missing, too old or broken."""
    when = now or _now()
    reason = {
        ToolStatus.MISSING: "FFmpeg not found",
        ToolStatus.TOO_OLD: "FFmpeg is too old",
        ToolStatus.BROKEN: "FFmpeg does not work",
    }.get(ffmpeg.status, "FFmpeg cannot be used")
    statuses = {
        key: status.model_copy(
            update={
                "state": EncoderState.UNAVAILABLE,
                "reason": reason,
                "detail": ffmpeg.reason,
                "checked_at": when,
            }
        )
        for key, status in initial_statuses(definitions).items()
    }
    return CapabilitySnapshot(
        encoders=statuses,
        ffmpeg=ffmpeg.path,
        ffmpeg_version=ffmpeg.version,
        checked_at=when,
    )


def _last_line(text: str) -> str:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return normalise_line(lines[-1]) if lines else ""


def _list_problem(result: RunResult, what: str, timeout: float) -> str | None:
    """Why ``ffmpeg -<what>`` gave no usable output, or ``None``."""
    if result.error is not None:
        return f"FFmpeg could not be started: {result.error}"
    if result.timed_out:
        return f"FFmpeg did not list its {what} within {timeout:g} s"
    if result.returncode != 0:
        detail = _last_line(result.stderr_text) or _last_line(result.stdout_text)
        suffix = f": {detail}" if detail else ""
        return f"ffmpeg -{what} exited with code {result.returncode}{suffix}"
    return None


class _Detection:
    """The state of one run: the statuses by id, updated in place (one event loop)."""

    def __init__(
        self,
        ffmpeg: ToolInfo,
        definitions: Definitions,
        options: DetectionOptions,
        cancel: CancelToken | None,
        on_update: StatusCallback | None,
    ) -> None:
        assert ffmpeg.path is not None
        self.binary: Path = ffmpeg.path
        self.env = dict(ffmpeg.env)
        self.ffmpeg = ffmpeg
        self.definitions = definitions
        self.options = options
        self.os: OperatingSystem = options.os or current_os()
        self.cancel = cancel
        self.on_update = on_update
        self.statuses = initial_statuses(definitions, EncoderState.CHECKING)
        self.tests = asyncio.Semaphore(MAX_PARALLEL_TESTS)
        self.helps = asyncio.Semaphore(MAX_PARALLEL_HELP)
        self.filter_failures: dict[str, str] = {}
        self.untested_filters: list[str] = []
        self.nodes: list[str] = []

    def set(self, encoder_id: str, **changes: object) -> EncoderStatus:
        status = self.statuses[encoder_id].model_copy(update=changes)
        self.statuses[encoder_id] = status
        return status

    def publish(self, changed: list[EncoderStatus]) -> None:
        if changed and self.on_update is not None:
            self.on_update(changed)

    async def ffmpeg_run(self, *args: str, timeout: float) -> RunResult:  # noqa: ASYNC109
        return await run(
            [str(self.binary), "-hide_banner", *args],
            timeout=timeout,
            cancel=self.cancel,
            extra_env=self.env,
        )

    async def run(self) -> CapabilitySnapshot:
        timeout = self.options.list_timeout
        async with asyncio.TaskGroup() as group:
            encoders_task = group.create_task(self.ffmpeg_run("-encoders", timeout=timeout))
            filters_task = group.create_task(self.ffmpeg_run("-filters", timeout=timeout))
        encoders_result, filters_result = encoders_task.result(), filters_task.result()
        filters = self.filters(filters_result)
        self.untested_filters = [f for f in FILTER_TESTS if f in (filters or ())]

        problem = _list_problem(encoders_result, "encoders", timeout)
        listing = parse_encoders(encoders_result.stdout_text) if problem is None else frozenset()
        if problem is None and not listing:
            problem = "ffmpeg -encoders printed no encoder list"
        if problem is not None:
            log.warning("encoder detection: %s", problem)
            when = _now()
            changed = [
                self.set(key, state=EncoderState.ERROR, reason=problem, checked_at=when)
                for key in self.statuses
            ]
            self.publish(changed)
            return self.snapshot(filters)

        pending = self.classify(listing)
        await self.read_help(listing)
        # Publish the statuses that need no test now, with their help data, so no status
        # goes out without its options.
        self.publish([s for s in self.statuses.values() if s.state is not EncoderState.CHECKING])
        if any(uses_vaapi_device(encoder) for encoder in pending):
            self.nodes = await asyncio.to_thread(vaapi_nodes, self.options)
            log.info("encoder detection: VAAPI render nodes %s", self.nodes or "none")
        async with asyncio.TaskGroup() as group:
            for encoder in pending:
                group.create_task(self.test(encoder))
            if self.options.hardware_tests:
                for name in list(self.untested_filters):
                    group.create_task(self.test_filter(name))
        return self.snapshot(filters)

    def filters(self, result: RunResult) -> list[str] | None:
        problem = _list_problem(result, "filters", self.options.list_timeout)
        names = parse_filters(result.stdout_text) if problem is None else []
        if problem is not None or not names:
            log.warning("encoder detection: no filter list (%s)", problem or "empty output")
            return None
        return names

    def classify(self, listing: frozenset[str]) -> list[VideoEncoderDef]:
        """Set every status that needs no test; return the hardware encoders to test."""
        when = _now()
        pending: list[VideoEncoderDef] = []
        for encoder in self.definitions.video_encoders.values():
            in_build = encoder.id in listing
            update: dict[str, object] = {"in_build": in_build, "checked_at": when}
            if self.os not in encoder.platforms:
                update |= {
                    "state": EncoderState.UNAVAILABLE,
                    "reason": f"Not available on {_OS_NAMES[self.os]}",
                }
            elif not in_build:
                update |= {"state": EncoderState.UNAVAILABLE, "reason": NOT_IN_BUILD}
            elif not encoder.hardware:
                update |= {"state": EncoderState.AVAILABLE}
            elif not self.options.hardware_tests:
                update |= {
                    "state": EncoderState.UNKNOWN,
                    "reason": "Not tested: hardware test encodes are off (Settings → Encoders)",
                    "checked_at": None,
                }
                forced = (self.options.vaapi_device or "").strip()
                if forced and uses_vaapi_device(encoder):
                    update["device"] = forced  # the encode uses it, tested or not
            else:
                pending.append(encoder)
                self.set(encoder.id, in_build=True)
                continue
            if "10" not in encoder.pix_fmts:
                update["supports_10bit"] = False
            self.set(encoder.id, **update)
        for audio in self.definitions.audio_encoders.values():
            in_build = audio.id in listing
            state = EncoderState.AVAILABLE if in_build else EncoderState.UNAVAILABLE
            reason = None if in_build else NOT_IN_BUILD
            self.set(audio.id, in_build=in_build, state=state, reason=reason, checked_at=when)
        return pending

    async def read_help(self, listing: frozenset[str]) -> None:
        """``-h encoder=<id>`` for every known encoder in the build (statuses updated, not
        published)."""
        ids = [key for key in self.statuses if key in listing]
        helps: dict[str, EncoderHelp] = {}

        async def one(encoder_id: str) -> None:
            async with self.helps:
                result = await self.ffmpeg_run(
                    "-h", f"encoder={encoder_id}", timeout=self.options.list_timeout
                )
            problem = _list_problem(result, f"h encoder={encoder_id}", self.options.list_timeout)
            parsed = parse_encoder_help(result.stdout_text) if problem is None else None
            if parsed is None:
                log.warning("encoder detection: no help for %s (%s)", encoder_id, problem)
                return
            helps[encoder_id] = parsed

        async with asyncio.TaskGroup() as group:
            for encoder_id in ids:
                group.create_task(one(encoder_id))
        for encoder_id in ids:
            parsed = helps.get(encoder_id)
            if parsed is None:
                continue
            update: dict[str, object] = {
                "private_options": parsed.private_options,
                "presets": parsed.presets,
                "pix_fmts": parsed.pix_fmts,
            }
            encoder = self.definitions.video_encoders.get(encoder_id)
            status = self.statuses[encoder_id]
            if encoder is not None and not encoder.hardware and status.supports_10bit is None:
                ten = encoder.pix_fmts.get("10")
                if ten is not None and parsed.pix_fmts:
                    update["supports_10bit"] = ten in parsed.pix_fmts
            self.set(encoder_id, **update)

    async def run_test(
        self, encoder: VideoEncoderDef, bit_depth: BitDepth, device: str | None = None
    ) -> TestOutcome:
        async with self.tests:
            started = time.monotonic()
            outcome = await run_hardware_test(
                self.binary,
                encoder,
                bit_depth,
                vaapi_device=device or DEFAULT_VAAPI_DEVICE,
                timeout=self.options.test_timeout,
                cancel=self.cancel,
                extra_env=self.env,
            )
        _log_outcome(f"test encode {encoder.id} {bit_depth}-bit", outcome, started)
        return outcome

    async def test(self, encoder: VideoEncoderDef) -> None:
        """The 8-bit test (on each render node in turn for VAAPI), then the 10-bit test on the
        device that worked."""
        vaapi = uses_vaapi_device(encoder)
        devices: list[str | None] = list(self.nodes) if vaapi else [None]
        if not devices:
            reason = "No VAAPI device (no render node in /dev/dri)"
            status = self.set(
                encoder.id, state=EncoderState.UNAVAILABLE, reason=reason, checked_at=_now()
            )
            self.publish([status])
            return
        first_failure = None
        device: str | None = None
        for candidate in devices:
            outcome = await self.run_test(encoder, "8", candidate)
            if outcome.cancelled:
                return
            if outcome.ok:
                device = candidate
                break
            first_failure = first_failure or outcome.failure
            if vaapi:
                assert outcome.failure is not None
                log.info("%s on %s: %s", encoder.id, candidate, outcome.failure.reason)
        else:
            assert first_failure is not None
            status = self.set(
                encoder.id,
                state=first_failure.state,
                reason=first_failure.reason,
                detail=first_failure.detail,
                build_mismatch=first_failure.build_mismatch,
                device=None,
                checked_at=_now(),
            )
            self.publish([status])
            return
        update: dict[str, object] = {
            "state": EncoderState.AVAILABLE,
            "reason": None,
            "detail": None,
            "device": device,
        }
        if "10" not in encoder.pix_fmts:
            update["supports_10bit"] = False
        else:
            ten = await self.run_test(encoder, "10", device)
            if ten.cancelled:
                return
            update["supports_10bit"] = ten.ok
            if ten.failure is not None:
                update["reason_10bit"] = ten.failure.reason
                log.info(
                    "%s: 10-bit test failed: %s (%s)",
                    encoder.id,
                    ten.failure.reason,
                    ten.failure.detail,
                )
        self.publish([self.set(encoder.id, checked_at=_now(), **update)])

    async def test_filter(self, name: str) -> None:
        """The run test of a filter (``libplacebo``): one frame through it."""
        async with self.tests:
            started = time.monotonic()
            outcome = await run_filter_test(
                self.binary,
                name,
                timeout=self.options.test_timeout,
                cancel=self.cancel,
                extra_env=self.env,
            )
        _log_outcome(f"filter test {name}", outcome, started)
        if outcome.cancelled:
            return
        self.untested_filters = [f for f in self.untested_filters if f != name]
        if outcome.failure is not None:
            self.filter_failures[name] = outcome.failure.reason
            log.info(
                "filter %s cannot be used: %s (%s)",
                name,
                outcome.failure.reason,
                outcome.failure.detail,
            )

    def snapshot(self, filters: list[str] | None) -> CapabilitySnapshot:
        return CapabilitySnapshot(
            encoders=dict(self.statuses),
            filters=filters,
            filter_failures=dict(self.filter_failures),
            untested_filters=list(self.untested_filters),
            ffmpeg=self.binary,
            ffmpeg_version=self.ffmpeg.version,
            detecting=False,
            from_cache=False,
            checked_at=_now(),
        )


def _log_outcome(what: str, outcome: TestOutcome, started: float) -> None:
    result = "ok" if outcome.ok else (outcome.failure.reason if outcome.failure else "cancelled")
    took = time.monotonic() - started
    log.debug("%s: %s in %.2f s (%s)", what, result, took, " ".join(outcome.argv))


async def detect_capabilities(
    ffmpeg: ToolInfo,
    definitions: Definitions,
    options: DetectionOptions | None = None,
    *,
    cancel: CancelToken | None = None,
    on_update: StatusCallback | None = None,
) -> CapabilitySnapshot:
    """Detect every encoder of ``definitions`` with ``ffmpeg``.

    Returns the finished snapshot (``detecting=False``). A cancel (``cancel`` or the task)
    kills every running FFmpeg; the snapshot is then incomplete (statuses stay ``checking``).
    """
    options = options or DetectionOptions()
    if not ffmpeg.usable:
        snapshot = unusable_snapshot(ffmpeg, definitions)
        if on_update is not None:
            on_update(list(snapshot.encoders.values()))
        return snapshot
    started = time.monotonic()
    snapshot = await _Detection(ffmpeg, definitions, options, cancel, on_update).run()
    counts: dict[str, int] = {}
    for status in snapshot.encoders.values():
        counts[status.state.value] = counts.get(status.state.value, 0) + 1
    log.info(
        "encoder detection with %s took %.2f s: %s",
        ffmpeg.path,
        time.monotonic() - started,
        ", ".join(f"{count} {state}" for state, count in sorted(counts.items())),
    )
    return snapshot
