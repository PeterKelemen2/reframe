"""Audio output tracks (05 §C-7 "Audio", 03 §Audio → Output tracks, decision 0013).

**Passthru** copies the source track (``-c:a:N copy``, plus the container's ``copy_args``:
``-strict -2`` for TrueHD in MP4). When the container cannot hold the codec, the track is
encoded with the track's encoder (HandBrake's auto passthru; ``None`` = AAC).

**Encode**: ``-c:a:N <encoder>``, the bitrate (``-b:a:N``; ``None`` = the definition's
default for the mixdown) or the VBR quality (``-q:a:N``), the sample rate (``-ar:a:N``,
always: FFmpeg silently picks a rate when none is given, and ``loudnorm`` outputs 192 kHz),
and one filter chain (``-filter:a:N``) in this order:

1. the layout: ``aresample=[matrix_encoding=dplii:]out_chlayout=<layout>`` (the layout of
   the mixdown definition). Without a mixdown the source layout stays, unless it has more
   channels than the encoder takes or the same channels with other labels (``5.1(side)`` →
   ``5.1``: libopus refuses ``5.1(side)``); see :func:`_layout_filter`;
2. the gain: ``volume=<gain>dB``;
3. loudness normalisation: two-pass ``loudnorm`` with the values measured by the track's
   ``analyse`` step (:class:`~reframe.models.ArgTemplate`), ``linear=true``.

The mixdown is in the chain, not ``-ac``, so that ``loudnorm`` measures and corrects the
audio that is encoded. **DRC** (HandBrake's dynamic range compression, 0 = off) is the AC-3
and E-AC-3 decoder option ``-drc_scale`` (an input option for the source stream; FFmpeg's
default is 1, HandBrake's 0).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

from reframe.command.errors import PlanError
from reframe.command.video import format_number, spec
from reframe.definitions import AudioEncoderDef, ContainerDef, Definitions
from reframe.models import (
    ArgTemplate,
    AudioOutputTrack,
    AudioStream,
    LoudnessTarget,
    Mixdown,
    PlanArg,
    ValueRef,
)

__all__ = [
    "DRC_CODECS",
    "FALLBACK_ENCODER",
    "LOUDNESS",
    "AudioOut",
    "LoudnessSpec",
    "audio_output",
    "closest_samplerate",
    "effective_mixdown",
    "loudnorm_analyse_filter",
]

#: The encoder of a passthru track that the container cannot hold when the track names none
#: (HandBrake's default fallback, ``AudioEncoderFallback: aac``).
FALLBACK_ENCODER = "aac"
#: Source codecs whose decoder applies dynamic range compression (``-drc_scale``).
DRC_CODECS = frozenset({"ac3", "eac3"})


@dataclass(frozen=True, slots=True)
class LoudnessSpec:
    """``loudnorm`` targets: integrated loudness (LUFS), true peak (dBTP), loudness range
    (LU). The plan sets only the loudness (03 §Audio); TP and LRA are decision 0013."""

    integrated: float
    true_peak: float
    lra: float

    def targets(self) -> str:
        return (
            f"I={format_number(self.integrated)}:TP={format_number(self.true_peak)}"
            f":LRA={format_number(self.lra)}"
        )


LOUDNESS: dict[LoudnessTarget, LoudnessSpec] = {
    "ebu_r128": LoudnessSpec(integrated=-23, true_peak=-1, lra=20),
    "streaming": LoudnessSpec(integrated=-16, true_peak=-1, lra=20),
}

#: The keys of ``loudnorm``'s JSON block that the second pass needs (option ← key).
_MEASURED = (
    ("measured_I", "input_i"),
    ("measured_TP", "input_tp"),
    ("measured_LRA", "input_lra"),
    ("measured_thresh", "input_thresh"),
    ("offset", "target_offset"),
)

_CHANNELS_TO_MIXDOWN: tuple[tuple[int, Mixdown], ...] = (
    (1, "mono"),
    (2, "stereo"),
    (6, "5.1"),
    (8, "7.1"),
)


def effective_mixdown(
    track: AudioOutputTrack, stream: AudioStream, encoder: AudioEncoderDef
) -> Mixdown:
    """The layout the encoder gets: the track's mixdown, else the source's channel count
    (1 mono, 2 stereo, 3 to 6 5.1, 7 to 8 7.1), limited to what the encoder can make."""
    if track.mixdown is not None:
        return track.mixdown
    channels = stream.channels or 2
    wanted: Mixdown = next((m for n, m in _CHANNELS_TO_MIXDOWN if channels <= n), "7.1")
    order: list[Mixdown] = ["7.1", "5.1", "stereo", "mono"]
    for mixdown in order[order.index(wanted) :]:
        if not encoder.mixdowns or mixdown in encoder.mixdowns:
            return mixdown
    return "stereo"


def closest_samplerate(rate: int, allowed: Sequence[int]) -> int:
    """``rate`` if allowed, else the closest allowed rate (the higher one on a tie)."""
    if not allowed or rate in allowed:
        return rate
    return min(allowed, key=lambda r: (abs(r - rate), -r))


@dataclass(slots=True)
class AudioOut:
    """One output audio track: its output arguments, input options and analyse filter."""

    index: int
    """Output audio index (``a:N``)."""
    stream: AudioStream
    copy: bool
    encoder: AudioEncoderDef | None = None
    args: list[PlanArg] = field(default_factory=list)
    """Per-stream codec arguments (``-c:a:N`` …); the filter is in :attr:`filter`."""
    filter: PlanArg | None = None
    """``-filter:a:N``; a template when it holds measured ``loudnorm`` values."""
    drc: float | None = None
    """``-drc_scale`` for the source stream (AC-3 / E-AC-3 that are decoded)."""
    global_args: list[str] = field(default_factory=list)
    """Output options without a stream specifier (``-strict -2``)."""
    loudness: LoudnessSpec | None = None
    analyse_filter: str | None = None
    """The filter of the ``analyse`` step (the chain up to ``loudnorm``, which prints JSON)."""
    measurement_id: str | None = None
    fallback: bool = False
    """A passthru track that is encoded because the container cannot hold its codec."""


def loudnorm_analyse_filter(pre: list[str], loudness: LoudnessSpec) -> str:
    return ",".join([*pre, f"loudnorm={loudness.targets()}:print_format=json"])


def _loudnorm_template(measurement: str, loudness: LoudnessSpec) -> list[str | ValueRef]:
    parts: list[str | ValueRef] = [f"loudnorm={loudness.targets()}"]
    for option, key in _MEASURED:
        parts += [f":{option}=", ValueRef(ref=f"{measurement}.{key}")]
    parts.append(":linear=true:print_format=summary")
    return parts


def _layout_filter(
    track: AudioOutputTrack, stream: AudioStream, mixdown: Mixdown, definitions: Definitions
) -> str | None:
    """The ``aresample`` that sets the output layout, or ``None`` when the source layout stays.

    A chosen mixdown is always written (Dolby Pro Logic II with its matrix encoding). Without
    one (keep the source layout) the layout of :func:`effective_mixdown` is written when the
    source has more channels than it, or the same number with other labels: libopus refuses
    ``5.1(side)``, the layout of FFmpeg's AC-3, DTS and TrueHD decoders ("Invalid channel
    layout 5.1(side) for specified mapping family -1"), and side → back is a lossless
    relabel (the same PCM). A source with fewer channels is not upmixed (5.0 stays 5.0).
    """
    target = definitions.mixdowns[mixdown]
    matrix = f"matrix_encoding={target.matrix_encoding}:" if target.matrix_encoding else ""
    convert = f"aresample={matrix}out_chlayout={target.layout}"
    if track.mixdown is not None:
        same = target.matrix_encoding is None and stream.channel_layout == target.layout
        return None if same else convert
    if stream.channel_layout is None or stream.channel_layout == target.layout:
        return None
    return convert if stream.channels >= target.channels else None


def audio_output(
    index: int,
    track: AudioOutputTrack,
    stream: AudioStream,
    container: ContainerDef,
    definitions: Definitions,
) -> AudioOut:
    """The arguments of output audio track ``index`` (``a:index``)."""
    a = f"a:{index}"
    codec = stream.codec or ""
    if track.action == "passthru" and container.audio.can_copy(codec):
        out = AudioOut(index=index, stream=stream, copy=True)
        out.args = [spec("-c:a", a), "copy"]
        out.global_args = list(container.audio.copy_args.get(codec, []))
        return out
    encoder_id = track.encoder or FALLBACK_ENCODER
    encoder = definitions.audio_encoders.get(encoder_id)
    if encoder is None:
        raise PlanError(f"unknown audio encoder {encoder_id!r} (validation reports it)")
    if encoder.codec not in container.audio.encode:
        raise PlanError(
            f"{encoder.label} cannot be written into {container.label} (validation reports it)"
        )
    out = AudioOut(
        index=index,
        stream=stream,
        copy=False,
        encoder=encoder,
        fallback=track.action == "passthru",
    )
    out.args = [spec("-c:a", a), encoder.id]
    mixdown = effective_mixdown(track, stream, encoder)
    if encoder.bitrate is not None:
        if track.bitrate is not None:
            out.args += [spec("-b:a", a), f"{track.bitrate}k"]
        elif track.quality is not None and encoder.quality is not None:
            out.args += [spec(encoder.quality.arg, a), format_number(track.quality)]
        else:
            limits = encoder.bitrate.by_mixdown.get(mixdown)
            if limits is not None:
                out.args += [spec("-b:a", a), f"{limits.default}k"]
    rate = track.samplerate or stream.sample_rate
    if rate is not None:
        out.args += [spec("-ar", a), str(closest_samplerate(rate, encoder.samplerates))]
    if codec in DRC_CODECS:
        out.drc = track.drc
    pre: list[str] = []
    layout_filter = _layout_filter(track, stream, mixdown, definitions)
    if layout_filter is not None:
        pre.append(layout_filter)
    if track.gain:
        pre.append(f"volume={format_number(track.gain)}dB")
    if track.loudness != "off":
        loudness = LOUDNESS[track.loudness]
        measurement = f"a{index}"
        out.loudness = loudness
        out.measurement_id = measurement
        out.analyse_filter = loudnorm_analyse_filter(pre, loudness)
        parts = _loudnorm_template(measurement, loudness)
        if pre:
            parts[0] = ",".join(pre) + "," + str(parts[0])
        out.filter = ArgTemplate(parts=parts)
    elif pre:
        out.filter = ",".join(pre)
    return out
