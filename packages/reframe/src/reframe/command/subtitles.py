"""Subtitle output tracks (05 §C-7 "Subtitles", 03 §Subtitles → Output tracks).

- **Copy**: ``-c:s:N copy`` when the container holds the codec; a text track it does not hold
  is converted to the container's text format (MP4 ``mov_text``, WebM ``webvtt``, MKV
  ``srt`` for ``mov_text``). An external text file with a character encoding is decoded and
  written again (``-sub_charenc`` works only when FFmpeg decodes the file).
- **Convert**: text to SRT, ASS, WebVTT or mov_text.
- **Burn in** (one track): text with the ``subtitles`` filter, bitmap with ``overlay``
  (:mod:`reframe.command.filtergraph`); **forced only** is the bitmap decoder option
  ``forced_subs_only`` (PGS and VobSub).
- **External files** are inputs after the source: ``-itsoffset`` (the track's offset),
  ``-ss`` (the range start: the source's seek does not move other inputs, checked with FFmpeg
  n9.0.2) and ``-sub_charenc``, then ``-i``. An event on screen at the range start, or moved
  before 0 by a negative offset, gets a negative time: the builder's output ``-ss 0`` drops
  it (the video is encoded), or ``-copypriorss:s:N 0`` (the video is copied and the track
  too, no range). A copied video with a range keeps them: the muxer moves every stream by
  the same amount, as it does for the video's own packets before the range start
  (decision 0013, "Follow-up (M2 review)").
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from reframe.command.errors import PlanError
from reframe.command.filtergraph import BitmapBurn, TextBurn
from reframe.command.video import format_number, spec
from reframe.definitions import ContainerDef
from reframe.models import (
    ExternalSubtitle,
    MediaSource,
    SubtitleFormat,
    SubtitleOutputTrack,
    SubtitleStream,
)

__all__ = [
    "EXTERNAL_CODECS",
    "FORMAT_ENCODERS",
    "ExternalInput",
    "SubtitleOut",
    "SubtitlePlan",
    "plan_subtitles",
]

#: ffprobe codec name of an external subtitle file, by extension.
EXTERNAL_CODECS = {
    ".srt": "subrip",
    ".ass": "ass",
    ".ssa": "ass",
    ".vtt": "webvtt",
    ".sup": "hdmv_pgs_subtitle",
}
_BITMAP_CODECS = frozenset({"hdmv_pgs_subtitle", "dvd_subtitle", "dvb_subtitle", "xsub"})
#: FFmpeg encoder of each subtitle format.
FORMAT_ENCODERS: dict[SubtitleFormat, str] = {
    "srt": "srt",
    "ass": "ass",
    "webvtt": "webvtt",
    "mov_text": "mov_text",
}
#: The encoder that writes a text codec again (to apply ``-sub_charenc``).
_SAME_FORMAT = {"subrip": "srt", "ass": "ass", "webvtt": "webvtt", "mov_text": "mov_text"}


@dataclass(slots=True)
class ExternalInput:
    """An external subtitle file as an input (``-i``)."""

    path: Path
    input_index: int
    args: list[str] = field(default_factory=list)
    """Input options and ``-i path``."""


@dataclass(slots=True)
class SubtitleOut:
    """One output subtitle track (``s:N``)."""

    index: int
    map: str
    """``0:4`` or ``1:0``."""
    codec: str
    """``copy`` or the encoder."""
    track: SubtitleOutputTrack
    source_language: str | None
    source_title: str | None
    ass: bool
    """The output is ASS (fonts are attachments of the source)."""
    drop_before_start: bool = False
    """``-copypriorss:s:N 0``: a copied external track drops its events before time 0 (a
    negative offset) when the output cannot have ``-ss 0`` (a copied video)."""

    def args(self) -> list[str]:
        out = [spec("-c:s", f"s:{self.index}"), self.codec]
        if self.drop_before_start:
            out += [spec("-copypriorss", f"s:{self.index}"), "0"]
        return out


@dataclass(slots=True)
class SubtitlePlan:
    outputs: list[SubtitleOut] = field(default_factory=list)
    inputs: list[ExternalInput] = field(default_factory=list)
    text_burn: TextBurn | None = None
    bitmap_burn: BitmapBurn | None = None
    decoder_args: list[str] = field(default_factory=list)
    """Input options of the source (``-forced_subs_only:5 1``)."""

    @property
    def copies_ass(self) -> bool:
        """An ASS track of the source is in the output: its fonts (the source's attachments)
        must go with it (05 §C-7)."""
        return any(o.ass and o.map.startswith("0:") for o in self.outputs)


def _is_bitmap(codec: str) -> bool:
    return codec in _BITMAP_CODECS


def _external_codec(ext: ExternalSubtitle) -> str:
    codec = EXTERNAL_CODECS.get(ext.path.suffix.lower())
    if codec is None:
        raise PlanError(f"unknown subtitle file type {ext.path.suffix!r} (validation reports it)")
    return codec


def _external_args(ext: ExternalSubtitle, start: float, bitmap: bool) -> list[str]:
    args: list[str] = []
    if ext.offset_ms:
        args += ["-itsoffset", format_number(ext.offset_ms / 1000)]
    if start:
        args += ["-ss", format_number(start)]
    if ext.charset and not bitmap:
        args += ["-sub_charenc", ext.charset]
    return args


def _output_codec(
    track: SubtitleOutputTrack, codec: str, container: ContainerDef, *, recode: bool
) -> str:
    bitmap = _is_bitmap(codec)
    if track.action == "convert":
        if track.convert_to is None:
            raise PlanError("a subtitle conversion needs a target format")
        if bitmap:
            raise PlanError("FFmpeg cannot convert bitmap subtitles to text (validation)")
        if track.convert_to not in container.subtitles.encode:
            raise PlanError(f"{track.convert_to} cannot be written into {container.label}")
        return FORMAT_ENCODERS[track.convert_to]
    if container.subtitles.can_copy(codec):
        return _SAME_FORMAT[codec] if recode and codec in _SAME_FORMAT else "copy"
    if not bitmap and container.text_subtitle_target is not None:
        return FORMAT_ENCODERS[container.text_subtitle_target]
    raise PlanError(f"{codec} subtitles cannot go into {container.label} (validation reports it)")


def _source_stream(source: MediaSource, index: int) -> SubtitleStream:
    stream = next((s for s in source.subtitles if s.index == index), None)
    if stream is None:
        raise PlanError(f"the source has no subtitle stream {index}")
    return stream


def plan_subtitles(
    tracks: list[SubtitleOutputTrack],
    source: MediaSource,
    container: ContainerDef,
    *,
    start: float,
    first_input: int,
    passthrough: bool,
) -> SubtitlePlan:
    """The subtitle part of a plan. ``first_input`` is the input index of the first external
    file (1: after the source)."""
    plan = SubtitlePlan()
    burns = [t for t in tracks if t.action == "burn"]
    if len(burns) > 1:
        raise PlanError("only one subtitle track can be burned in (validation reports it)")
    if burns and passthrough:
        raise PlanError("subtitles cannot be burned into a video that is passed through")
    next_input = first_input
    for track in tracks:
        if isinstance(track.source, ExternalSubtitle):
            ext = track.source
            codec = _external_codec(ext)
            bitmap = _is_bitmap(codec)
            if track.action == "burn" and not bitmap:
                plan.text_burn = TextBurn(
                    path=ext.path, stream=None, charenc=ext.charset,
                    shift=start - ext.offset_ms / 1000,
                )  # fmt: skip
                continue
            args = _external_args(ext, start, bitmap)
            if track.action == "burn" and track.forced_only:
                args += ["-forced_subs_only:0", "1"]
            entry = ExternalInput(ext.path, next_input, [*args, "-i", str(ext.path)])
            plan.inputs.append(entry)
            next_input += 1
            label = f"{entry.input_index}:0"
            if track.action == "burn":
                plan.bitmap_burn = BitmapBurn(input_label=label)
                continue
            recode = bool(ext.charset) and not bitmap
            out_codec = _output_codec(track, codec, container, recode=recode)
            plan.outputs.append(
                SubtitleOut(
                    index=len(plan.outputs), map=label, codec=out_codec, track=track,
                    source_language=ext.language, source_title=ext.name,
                    ass=_is_ass(codec, out_codec),
                    drop_before_start=(passthrough and not start and ext.offset_ms < 0
                                       and out_codec == "copy"),
                )
            )  # fmt: skip
            continue
        stream = _source_stream(source, track.source)
        codec = stream.codec or ""
        bitmap = stream.subtitle_kind == "bitmap" or _is_bitmap(codec)
        if track.action == "burn":
            if bitmap:
                canvas = (
                    (stream.width, stream.height)
                    if stream.width is not None and stream.height is not None
                    else None
                )
                plan.bitmap_burn = BitmapBurn(input_label=f"0:{stream.index}", canvas=canvas)
                if track.forced_only:
                    plan.decoder_args += [f"-forced_subs_only:{stream.index}", "1"]
            else:
                plan.text_burn = TextBurn(
                    path=source.ref.path, stream=stream.type_index, shift=start
                )
            continue
        out_codec = _output_codec(track, codec, container, recode=False)
        plan.outputs.append(
            SubtitleOut(
                index=len(plan.outputs), map=f"0:{stream.index}", codec=out_codec, track=track,
                source_language=stream.language_ietf or stream.language,
                source_title=stream.title, ass=_is_ass(codec, out_codec),
            )
        )  # fmt: skip
    return plan


def _is_ass(codec: str, out_codec: str) -> bool:
    return out_codec == "ass" or (out_codec == "copy" and codec == "ass")
