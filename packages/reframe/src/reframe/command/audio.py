"""Audio output tracks: a copy, or an encoder with its bitrate, sample rate and one filter chain.

The chain is the layout, the gain, then ``loudnorm``. The mixdown is in the chain, not ``-ac``,
so that ``loudnorm`` measures the audio that is encoded. :func:`planned_audio` holds the snapped
values, so the builder and validation agree.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from reframe.command.errors import PlanError
from reframe.command.video import format_number, spec
from reframe.definitions import (
    AudioEncoderDef,
    ContainerDef,
    Definitions,
    channels_mixdown,
    load_definitions,
)
from reframe.models import (
    ArgTemplate,
    AudioOutputTrack,
    AudioStream,
    Container,
    LoudnessTarget,
    Mixdown,
    PlanArg,
    ValueRef,
)

__all__ = [
    "DRC_CODECS",
    "ENCODER_LAYOUTS",
    "FALLBACK_ENCODER",
    "LAYOUT_CHANNELS",
    "LOUDNESS",
    "AudioOut",
    "LoudnessSpec",
    "PlannedAudio",
    "audio_output",
    "layout_channels",
    "loudnorm_analyse_filter",
    "planned_audio",
]

#: The encoder of a passthru track that the container cannot hold, when the track names none
#: (HandBrake's default fallback).
FALLBACK_ENCODER = "aac"
#: Source codecs whose decoder applies dynamic range compression (``-drc_scale``).
DRC_CODECS = frozenset({"ac3", "eac3"})


@dataclass(frozen=True, slots=True)
class LoudnessSpec:
    """``loudnorm`` targets: integrated loudness (LUFS), true peak (dBTP), loudness range (LU)."""

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

#: The second pass's ``loudnorm`` options, as (option, key in the first pass's JSON block).
_MEASURED = (
    ("measured_I", "input_i"),
    ("measured_TP", "input_tp"),
    ("measured_LRA", "input_lra"),
    ("measured_thresh", "input_thresh"),
    ("offset", "target_offset"),
)

#: The channels of FFmpeg's named layouts (``ffmpeg -layouts``). A layout without a name is read
#: by :func:`layout_channels`.
LAYOUT_CHANNELS: dict[str, tuple[str, ...]] = {
    "mono": ("FC",),
    "stereo": ("FL", "FR"),
    "2.1": ("FL", "FR", "LFE"),
    "3.0": ("FL", "FR", "FC"),
    "3.0(back)": ("FL", "FR", "BC"),
    "4.0": ("FL", "FR", "FC", "BC"),
    "quad": ("FL", "FR", "BL", "BR"),
    "quad(side)": ("FL", "FR", "SL", "SR"),
    "3.1": ("FL", "FR", "FC", "LFE"),
    "5.0": ("FL", "FR", "FC", "BL", "BR"),
    "5.0(side)": ("FL", "FR", "FC", "SL", "SR"),
    "4.1": ("FL", "FR", "FC", "LFE", "BC"),
    "5.1": ("FL", "FR", "FC", "LFE", "BL", "BR"),
    "5.1(side)": ("FL", "FR", "FC", "LFE", "SL", "SR"),
    "6.0": ("FL", "FR", "FC", "BC", "SL", "SR"),
    "6.0(front)": ("FL", "FR", "FLC", "FRC", "SL", "SR"),
    "3.1.2": ("FL", "FR", "FC", "LFE", "TFL", "TFR"),
    "hexagonal": ("FL", "FR", "FC", "BL", "BR", "BC"),
    "6.1": ("FL", "FR", "FC", "LFE", "BC", "SL", "SR"),
    "6.1(back)": ("FL", "FR", "FC", "LFE", "BL", "BR", "BC"),
    "6.1(front)": ("FL", "FR", "LFE", "FLC", "FRC", "SL", "SR"),
    "7.0": ("FL", "FR", "FC", "BL", "BR", "SL", "SR"),
    "7.0(front)": ("FL", "FR", "FC", "FLC", "FRC", "SL", "SR"),
    "7.1": ("FL", "FR", "FC", "LFE", "BL", "BR", "SL", "SR"),
    "7.1(wide)": ("FL", "FR", "FC", "LFE", "BL", "BR", "FLC", "FRC"),
    "7.1(wide-side)": ("FL", "FR", "FC", "LFE", "FLC", "FRC", "SL", "SR"),
    "5.1.2": ("FL", "FR", "FC", "LFE", "SL", "SR", "TFL", "TFR"),
    "5.1.2(back)": ("FL", "FR", "FC", "LFE", "BL", "BR", "TFL", "TFR"),
    "octagonal": ("FL", "FR", "FC", "BL", "BR", "BC", "SL", "SR"),
    "cube": ("FL", "FR", "BL", "BR", "TFL", "TFR", "TBL", "TBR"),
    "binaural": ("BIL", "BIR"),
    "downmix": ("DL", "DR"),
}

#: Encoders that refuse every layout but these, largest last. FFmpeg lists no layouts for them,
#: so it does not convert one for them: libopus fails on any other (mapping family -1).
ENCODER_LAYOUTS: dict[str, tuple[str, ...]] = {
    "libopus": ("mono", "stereo", "3.0", "quad", "5.0", "5.1", "6.1", "7.1"),
}

_SIDE_TO_BACK = {"SL": "BL", "SR": "BR"}
_UNNAMED_LAYOUT = re.compile(r"\d+ channels \(([A-Za-z0-9]+(?:\+[A-Za-z0-9]+)*)\)")


def layout_channels(layout: str | None) -> tuple[str, ...] | None:
    """The channels of an ffprobe ``channel_layout``: named, or ``N channels (A+B+…)``; ``None``
    when not known."""
    if layout is None:
        return None
    named = LAYOUT_CHANNELS.get(layout)
    if named is not None:
        return named
    unnamed = _UNNAMED_LAYOUT.fullmatch(layout)
    return tuple(unnamed.group(1).split("+")) if unnamed is not None else None


def _side_to_back(channels: tuple[str, ...]) -> frozenset[str] | None:
    """The channels with the side pair renamed to the back pair, or ``None`` unless the layout
    has a side pair and no back pair."""
    have = set(channels)
    if not {"SL", "SR"} <= have or have & {"BL", "BR"}:
        return None
    return frozenset(_SIDE_TO_BACK.get(c, c) for c in channels)


def _kept_layout(
    stream: AudioStream, encoder: AudioEncoderDef, table: Mixdown, defs: Definitions
) -> str | None:
    """The ``out_chlayout`` for a source layout that stays (no mixdown), or ``None`` to leave
    it to FFmpeg.

    An encoder in :data:`ENCODER_LAYOUTS` keeps the source layout when it accepts it. Else it
    gets the side → back relabel when that is accepted, or else the largest accepted layout of
    the source's channels (a downmix). Any other encoder gets the source's layout, relabelled
    to the bitrate table's layout only when that is lossless: a 6.0 or 7.1(wide) source is not
    remixed to 5.1 or 7.1.
    """
    channels = layout_channels(stream.channel_layout)
    if channels is None:
        return None  # not known: left to FFmpeg
    renamed = _side_to_back(channels)
    accepted = ENCODER_LAYOUTS.get(encoder.id)
    if accepted is None:
        target = defs.mixdowns[table].layout
        relabel = renamed is not None and renamed == frozenset(LAYOUT_CHANNELS[target])
        return target if relabel else None
    if stream.channel_layout in accepted:
        return None
    if renamed is not None:
        for name in accepted:
            if frozenset(LAYOUT_CHANNELS[name]) == renamed:
                return name
    have = renamed if renamed is not None else frozenset(channels)
    fits = [name for name in accepted if frozenset(LAYOUT_CHANNELS[name]) <= have]
    return fits[-1] if fits else None


@dataclass(frozen=True, slots=True)
class PlannedAudio:
    """What the builder writes for one output audio track (:func:`planned_audio`).

    A copy has only ``copy = True``. An encoded track has its encoder and the snapped values
    that go into its arguments.
    """

    copy: bool
    """A passthru track that the container can hold: ``-c:a:N copy``."""
    encoder: str | None = None
    """The audio encoder id (``None`` for a copy)."""
    fallback: bool = False
    """A passthru track that is encoded because the container cannot hold its codec."""
    mixdown: Mixdown | None = None
    """The snapped mixdown (:meth:`~reframe.definitions.AudioEncoderDef.snap_mixdown`);
    ``None`` = the source layout stays (see :attr:`layout`)."""
    layout: str | None = None
    """The ``out_chlayout`` of the ``aresample`` in ``-filter:a:N``; ``None`` = the encoder gets
    the source layout. With a mixdown, that is its layout unless the source has it already.
    Without one, a lossless relabel or, for an encoder of :data:`ENCODER_LAYOUTS`, a layout
    it accepts."""
    bitrate_mixdown: Mixdown | None = None
    """The bitrate table the track uses: ``mixdown``, else
    :func:`~reframe.definitions.channels_mixdown` of the output channels (the source's, or
    those of :attr:`layout`)."""
    bitrate: int | None = None
    """kb/s: the track's bitrate snapped, else (no VBR quality) the table's default.
    ``None`` for a copy, a lossless encoder and a VBR quality."""
    quality: float | None = None
    """The track's VBR quality, when the encoder has one and no bitrate is set."""
    samplerate: int | None = None
    """Hz; ``None`` only when neither the track nor the source says a rate."""


def _container(container: ContainerDef | Container, defs: Definitions) -> ContainerDef:
    if isinstance(container, ContainerDef):
        return container
    return defs.containers[container]


def _bitrate(
    track: AudioOutputTrack, encoder: AudioEncoderDef, table: Mixdown
) -> tuple[int | None, float | None]:
    """``(bitrate, quality)`` of an encoded track: a set bitrate, else a VBR quality, else the
    table's default."""
    rates = encoder.bitrate
    if rates is None:
        return None, None  # lossless (FLAC)
    if track.bitrate is not None:
        snapped = rates.snap(track.bitrate, table)
        # ``None``: the encoder has no table for this layout. The linter checks that every
        # mixdown has one; FFmpeg gets the value as it is.
        return (snapped if snapped is not None else track.bitrate), None
    if track.quality is not None and encoder.quality is not None:
        return None, track.quality
    limits = rates.by_mixdown.get(table)
    return (limits.default if limits is not None else None), None


def _plan(
    track: AudioOutputTrack, stream: AudioStream, container: ContainerDef, defs: Definitions
) -> tuple[PlannedAudio, AudioEncoderDef | None]:
    if track.action == "passthru" and container.audio.can_copy(stream.codec or ""):
        return PlannedAudio(copy=True), None
    encoder_id = track.encoder or FALLBACK_ENCODER
    encoder = defs.audio_encoders.get(encoder_id)
    if encoder is None:
        raise PlanError(f"unknown audio encoder {encoder_id!r} (validation reports it)")
    if encoder.codec not in container.audio.encode:
        raise PlanError(
            f"{encoder.label} cannot be written into {container.label} (validation reports it)"
        )
    mixdown = encoder.snap_mixdown(track.mixdown, stream.channels, defs.mixdowns)
    layout: str | None
    if mixdown is not None:
        target = defs.mixdowns[mixdown]
        same = target.matrix_encoding is None and stream.channel_layout == target.layout
        layout = None if same else target.layout
        table = mixdown
    else:
        layout = _kept_layout(stream, encoder, channels_mixdown(stream.channels), defs)
        written = layout_channels(layout)
        table = channels_mixdown(len(written) if written is not None else stream.channels)
    bitrate, quality = _bitrate(track, encoder, table)
    planned = PlannedAudio(
        copy=False,
        encoder=encoder.id,
        fallback=track.action == "passthru",
        mixdown=mixdown,
        layout=layout,
        bitrate_mixdown=table,
        bitrate=bitrate,
        quality=quality,
        samplerate=encoder.snap_samplerate(track.samplerate, stream.sample_rate),
    )
    return planned, encoder


def planned_audio(
    track: AudioOutputTrack,
    stream: AudioStream,
    container: ContainerDef | Container,
    *,
    definitions: Definitions | None = None,
) -> PlannedAudio:
    """What :func:`~reframe.command.build_plan` writes for ``track`` (read from ``stream``)
    in ``container``: copy or encode, and the snapped mixdown, bitrate or quality, and sample
    rate. Pure. Raises :class:`PlanError` for an unknown encoder or container, or an encoder
    the container cannot hold (validation reports them)."""
    defs = definitions if definitions is not None else load_definitions()
    return _plan(track, stream, _container(container, defs), defs)[0]


@dataclass(slots=True)
class AudioOut:
    """One output audio track: its output arguments, input options and analyse filter."""

    index: int
    """Output audio index (``a:N``)."""
    stream: AudioStream
    args: list[PlanArg] = field(default_factory=list)
    """Per-stream codec arguments (``-c:a:N`` …); the filter is in :attr:`filter`."""
    filter: PlanArg | None = None
    """``-filter:a:N``; a template when it holds measured ``loudnorm`` values."""
    drc: float | None = None
    """``-drc_scale`` for the source stream (AC-3 / E-AC-3 that are decoded)."""
    global_args: list[str] = field(default_factory=list)
    """Output options without a stream specifier (``-strict -2``)."""
    analyse_filter: str | None = None
    """The filter of the ``analyse`` step (the chain up to ``loudnorm``, which prints JSON)."""
    measurement_id: str | None = None


def loudnorm_analyse_filter(pre: list[str], loudness: LoudnessSpec) -> str:
    return ",".join([*pre, f"loudnorm={loudness.targets()}:print_format=json"])


def _loudnorm_template(measurement: str, loudness: LoudnessSpec) -> list[str | ValueRef]:
    parts: list[str | ValueRef] = [f"loudnorm={loudness.targets()}"]
    for option, key in _MEASURED:
        parts += [f":{option}=", ValueRef(ref=f"{measurement}.{key}")]
    parts.append(":linear=true:print_format=summary")
    return parts


def _layout_filter(planned: PlannedAudio, definitions: Definitions) -> str | None:
    if planned.layout is None:
        return None
    mixdown = definitions.mixdowns[planned.mixdown] if planned.mixdown is not None else None
    matrix = mixdown.matrix_encoding if mixdown is not None else None
    prefix = f"matrix_encoding={matrix}:" if matrix else ""
    return f"aresample={prefix}out_chlayout={planned.layout}"


def audio_output(
    index: int,
    track: AudioOutputTrack,
    stream: AudioStream,
    container: ContainerDef,
    definitions: Definitions,
) -> AudioOut:
    """The arguments of output audio track ``index`` (``a:index``)."""
    a = f"a:{index}"
    planned, encoder = _plan(track, stream, container, definitions)
    if encoder is None:
        out = AudioOut(index=index, stream=stream)
        out.args = [spec("-c:a", a), "copy"]
        out.global_args = list(container.audio.copy_args.get(stream.codec or "", []))
        return out
    out = AudioOut(index=index, stream=stream)
    out.args = [spec("-c:a", a), encoder.id]
    if planned.bitrate is not None:
        out.args += [spec("-b:a", a), f"{planned.bitrate}k"]
    elif planned.quality is not None and encoder.quality is not None:
        out.args += [spec(encoder.quality.arg, a), format_number(planned.quality)]
    if planned.samplerate is not None:
        out.args += [spec("-ar", a), str(planned.samplerate)]
    if (stream.codec or "") in DRC_CODECS:
        out.drc = track.drc
    pre: list[str] = []
    layout_filter = _layout_filter(planned, definitions)
    if layout_filter is not None:
        pre.append(layout_filter)
    if track.gain:
        pre.append(f"volume={format_number(track.gain)}dB")
    if track.loudness != "off":
        loudness = LOUDNESS[track.loudness]
        measurement = f"a{index}"
        out.measurement_id = measurement
        out.analyse_filter = loudnorm_analyse_filter(pre, loudness)
        parts = _loudnorm_template(measurement, loudness)
        if pre:
            parts[0] = ",".join(pre) + "," + str(parts[0])
        out.filter = ArgTemplate(parts=parts)
    elif pre:
        out.filter = ",".join(pre)
    return out
