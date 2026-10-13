"""Range rules (05 §C-8 "Range is outside the duration").

- A range that starts at or after the end of the source, or that is empty (end ≤ start), or a
  chapter range on a source without chapters: ``range.outside`` (error). The fix encodes the
  whole source.
- A range that ends after the source ends: ``range.end_beyond`` (warning). The encode stops at
  the end of the source anyway; the fix sets the end to "the end".

Nothing is checked when the duration (or, for frames, the frame count) is not known.
"""

from __future__ import annotations

from collections.abc import Iterator

from reframe.models.issues import Fix, ValidationIssue
from reframe.models.job import ChapterRange, FullRange, TimeRange
from reframe.validation.common import error, fix, replace, warning
from reframe.validation.context import JobContext
from reframe.validation.registry import job_rule

__all__ = ["frame_count", "range_duration", "source_range"]


def frame_count(ctx: JobContext) -> int | None:
    """Frames of the main video stream: the stream's count, else duration x frame rate."""
    stream = ctx.video_stream
    if stream is None:
        return None
    if stream.frame_count is not None:
        return stream.frame_count
    rate = stream.avg_frame_rate or stream.frame_rate
    if ctx.duration is None or rate is None or rate.num <= 0:
        return None
    return round(ctx.duration * rate.num / rate.den)


def range_duration(ctx: JobContext) -> float | None:
    """Seconds of the source the job encodes (``None`` when not known)."""
    duration = ctx.duration
    selected = ctx.job.range
    if isinstance(selected, FullRange):
        return duration
    if isinstance(selected, TimeRange):
        if duration is None:
            return None if selected.end is None else max(0.0, selected.end - selected.start)
        end = min(selected.end, duration) if selected.end is not None else duration
        return max(0.0, end - selected.start)
    if isinstance(selected, ChapterRange):
        chapters = ctx.source.chapters
        if not chapters or selected.start > len(chapters):
            return None
        final = chapters[min(selected.end, len(chapters)) - 1]
        return max(0.0, final.end - chapters[selected.start - 1].start)
    stream = ctx.video_stream
    rate = (stream.avg_frame_rate or stream.frame_rate) if stream is not None else None
    if rate is None or rate.num <= 0:
        return None
    total = frame_count(ctx)
    last = selected.end if selected.end is not None else total
    if last is None:
        return None
    if total is not None:
        last = min(last, total)
    return max(0, last - selected.start) * rate.den / rate.num


def _full(ctx: JobContext) -> Fix:
    return fix("Encode the whole source", replace("range", {"kind": "full"}), target=ctx.target)


def _seconds(value: float) -> str:
    return f"{value:g} s"


@job_rule("range", "range.outside", "range.end_beyond")
def source_range(ctx: JobContext) -> Iterator[ValidationIssue]:
    selected = ctx.job.range
    if isinstance(selected, FullRange):
        return
    if isinstance(selected, ChapterRange):
        yield from _chapters(ctx, selected)
        return
    total: float | None
    if isinstance(selected, TimeRange):
        total = ctx.duration
        start, end = float(selected.start), selected.end
        text = _seconds
    else:
        frames = frame_count(ctx)
        total = float(frames) if frames is not None else None
        start = float(selected.start)
        end = float(selected.end) if selected.end is not None else None

        def text(value: float) -> str:
            return f"frame {value:g}"

    if end is not None and end <= start:
        yield error(
            "range.outside",
            "range",
            f"The range is empty: it ends ({text(end)}) before it starts ({text(start)}).",
            _full(ctx),
        )
        return
    if total is None:
        return
    if start >= total:
        yield error(
            "range.outside",
            "range.start",
            f"The range starts at {text(start)}, after the end of the source ({text(total)}).",
            _full(ctx),
        )
    elif end is not None and end > total:
        yield warning(
            "range.end_beyond",
            "range.end",
            f"The range ends at {text(end)}, after the end of the source ({text(total)}): the "
            "encode stops at the end of the source.",
            fix("End at the end of the source", replace("range.end", None), target=ctx.target),
        )


def _chapters(ctx: JobContext, selected: ChapterRange) -> Iterator[ValidationIssue]:
    count = len(ctx.source.chapters)
    if count == 0:
        yield error("range.outside", "range", "The source has no chapters to select.", _full(ctx))
    elif selected.end < selected.start:
        yield error(
            "range.outside",
            "range",
            f"The chapter range is empty: it ends (chapter {selected.end}) before it starts "
            f"(chapter {selected.start}).",
            _full(ctx),
        )
    elif selected.start > count:
        yield error(
            "range.outside",
            "range.start",
            f"The range starts at chapter {selected.start}; the source has {count} chapters.",
            _full(ctx),
        )
    elif selected.end > count:
        yield warning(
            "range.end_beyond",
            "range.end",
            f"The range ends at chapter {selected.end}; the source has {count} chapters: the "
            "encode stops at the last chapter.",
            fix(f"End at chapter {count}", replace("range.end", count), target=ctx.target),
        )
