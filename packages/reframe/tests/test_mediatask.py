"""The core-complete contract (docs/core-breakdown.md): the C-10 task context and its helpers,
measured values kept by ``Reframe.sources.store``, ``Reframe.jobs.explain`` and the facade
wiring of the new services."""

from __future__ import annotations

import itertools
import os
import shutil
from pathlib import Path

import pytest

from reframe.definitions import load_definitions
from reframe.events import EventBus
from reframe.mediatask import (
    MediaTaskContext,
    TaskFailed,
    require_source,
    require_tool,
    sample_timestamps,
)
from reframe.models import (
    AppSettings,
    BitrateInfo,
    BitrateSource,
    CapabilitySnapshot,
    MediaSource,
    ToolInfo,
    ToolSet,
    ToolStatus,
)
from reframe.probe import ProbeError, ProbeErrorKind
from reframe.service import Reframe
from reframe.tasks import DEFAULT_LIMITS, TaskManager
from reframe.tools import CancelToken

pytestmark = pytest.mark.anyio

# --------------------------------------------------------------------------- sample_timestamps


@pytest.mark.parametrize(("duration", "count"), [(None, 10), (0.0, 10), (-1.0, 3), (100.0, 0)])
def test_no_timestamps(duration: float | None, count: int) -> None:
    assert sample_timestamps(duration, count) == []


def test_one_timestamp_is_the_middle() -> None:
    assert sample_timestamps(7.0, 1) == [3.5]


def test_timestamps_skip_the_first_and_last_five_percent() -> None:
    stamps = sample_timestamps(200.0, 10)
    assert stamps[0] == 10.0
    assert stamps[-1] == 190.0
    steps = {round(b - a, 3) for a, b in itertools.pairwise(stamps)}
    assert steps == {20.0}


def test_timestamps_are_rounded_to_milliseconds() -> None:
    stamps = sample_timestamps(1.0 / 3.0, 3)
    assert stamps == [round(s, 3) for s in stamps]
    assert all(0 < s < 1 / 3 for s in stamps)


# --------------------------------------------------------------------------- helpers


class _Tools:
    def __init__(self, tools: ToolSet) -> None:
        self.tools = tools

    async def status(self) -> ToolSet:
        return self.tools


class _Sources:
    def __init__(self, outcome: MediaSource | ProbeError) -> None:
        self.outcome = outcome
        self.stored: list[MediaSource] = []

    async def probe(
        self,
        path: str | os.PathLike[str],
        *,
        use_cache: bool = True,
        cancel: CancelToken | None = None,
    ) -> MediaSource | ProbeError:
        return self.outcome

    async def store(self, source: MediaSource) -> None:
        self.stored.append(source)


class _Caps:
    @property
    def snapshot(self) -> CapabilitySnapshot:
        return CapabilitySnapshot()

    async def wait(self) -> CapabilitySnapshot:
        return CapabilitySnapshot()


def _info(name: str, status: ToolStatus, reason: str | None = None) -> ToolInfo:
    path = Path(f"/opt/{name}") if status is ToolStatus.FOUND else None
    return ToolInfo(name=name, status=status, path=path, reason=reason)  # type: ignore[arg-type]


def _toolset(ffmpeg: ToolInfo) -> ToolSet:
    return ToolSet(
        ffmpeg=ffmpeg,
        ffprobe=_info("ffprobe", ToolStatus.FOUND),
        mkvpropedit=_info("mkvpropedit", ToolStatus.MISSING, "not found"),
        mediainfo=_info("mediainfo", ToolStatus.MISSING, "not found"),
    )


def _context(tmp_path: Path, tools: ToolSet, sources: _Sources) -> MediaTaskContext:
    events = EventBus()
    return MediaTaskContext(
        tasks=TaskManager(events),
        tools=_Tools(tools),
        sources=sources,
        capabilities=_Caps(),
        settings=AppSettings,
        events=events,
        cache_dir=tmp_path,
        definitions=load_definitions,
    )


async def test_require_tool(tmp_path: Path) -> None:
    sources = _Sources(ProbeError(tmp_path, ProbeErrorKind.NOT_FOUND, "x"))
    found = _info("ffmpeg", ToolStatus.FOUND)
    ctx = _context(tmp_path, _toolset(found), sources)
    assert await require_tool(ctx, "ffmpeg") == found
    assert (await require_tool(ctx, "ffprobe")).name == "ffprobe"
    with pytest.raises(TaskFailed, match="mkvpropedit cannot be used: not found"):
        await require_tool(ctx, "mkvpropedit")
    old = _info("ffmpeg", ToolStatus.TOO_OLD)
    ctx = _context(tmp_path, _toolset(old), sources)
    with pytest.raises(TaskFailed, match="ffmpeg cannot be used: too_old"):
        await require_tool(ctx, "ffmpeg")


async def test_require_source_gives_the_probe_error_as_the_message(tmp_path: Path) -> None:
    error = ProbeError(tmp_path / "a.mkv", ProbeErrorKind.FAILED, "a.mkv is not media.", "EBML")
    ctx = _context(tmp_path, _toolset(_info("ffmpeg", ToolStatus.FOUND)), _Sources(error))
    with pytest.raises(TaskFailed, match=r"^a\.mkv is not media\. \(EBML\)$"):
        await require_source(ctx, tmp_path / "a.mkv")


def test_every_c10_task_kind_has_a_limit() -> None:
    kinds = {"bitrate_scan", "subtitle_scan", "loudness", "frames", "cropdetect"}
    assert kinds | {"preview_clip", "tools_fetch"} <= set(DEFAULT_LIMITS)


# --------------------------------------------------------------------------- the facade


@pytest.fixture
async def app(tmp_path: Path) -> Reframe:
    return await Reframe.create(
        tmp_path / "config", tmp_path / "data", cache_dir=tmp_path / "cache"
    )


async def test_facade_wiring(app: Reframe, tmp_path: Path) -> None:
    try:
        assert app.sources.media is not None
        assert app.sources.media.cache_dir == tmp_path / "cache"
        assert app.sources.media.sources is app.sources
        assert app.power.pending is None
    finally:
        await app.close()
    await app.power.close()  # safe twice


@pytest.mark.needs_ffmpeg
async def test_preview_cache_size_and_clear(app: Reframe, fixture_media: object) -> None:
    try:
        assert await app.sources.preview_cache_size() == 0
        info = app.sources.frames(fixture_media("multitrack"), count=2)  # type: ignore[operator]
        done = await app.tasks.wait(info.id)
        assert done.state.value == "done", done.error
        size = await app.sources.preview_cache_size()
        assert size > 0
        assert await app.sources.clear_preview_cache() == size
        assert await app.sources.preview_cache_size() == 0
    finally:
        await app.close()


@pytest.mark.needs_ffmpeg
async def test_store_keeps_a_measured_bitrate(
    app: Reframe, tmp_path: Path, fixture_media: object
) -> None:
    source_file = tmp_path / "multitrack.mkv"
    shutil.copy(fixture_media("multitrack"), source_file)  # type: ignore[operator]
    try:
        probed = await app.sources.probe(source_file)
        assert isinstance(probed, MediaSource)
        measured = BitrateInfo(value=123_456, source=BitrateSource.MEASURED)
        probed.audio[1].bitrate = measured
        await app.sources.store(probed)
        known = await app.sources.get(source_file)
        assert known is not None
        assert known.audio[1].bitrate == measured
    finally:
        await app.close()
    # A new process reads it from the probe cache.
    again = await Reframe.create(
        tmp_path / "config", tmp_path / "data", cache_dir=tmp_path / "cache"
    )
    try:
        cached = await again.sources.probe(source_file)
        assert isinstance(cached, MediaSource)
        assert cached.audio[1].bitrate == measured
        # A changed file: the old measurement is not stored for it.
        stale = cached.model_copy(deep=True)
        os.utime(source_file, (1, 1))
        stale.audio[1].bitrate = BitrateInfo(value=1, source=BitrateSource.MEASURED)
        await again.sources.store(stale)
        fresh = await again.sources.probe(source_file)
        assert isinstance(fresh, MediaSource)
        assert fresh.audio[1].bitrate.value != 1
    finally:
        await again.close()


@pytest.mark.needs_ffmpeg
async def test_explain_drafts_the_tracks_of_a_preset(app: Reframe, fixture_media: object) -> None:
    path = fixture_media("multitrack")  # type: ignore[operator]
    try:
        draft = await app.jobs.explain(path)
        assert not isinstance(draft, ProbeError)
        assert [d.source_stream for d in draft.decisions] == [1, 2, 3]
        assert all(d.reason for d in draft.decisions)
        unknown = await app.jobs.explain(path, "No Such Preset")
        assert not isinstance(unknown, ProbeError)
        assert [i.code for i in unknown.issues][:1] == ["preset.not_found"]
        mp4 = await app.jobs.explain(path, container="mp4")
        assert not isinstance(mp4, ProbeError)
        assert len(mp4.decisions) == 3
    finally:
        await app.close()
