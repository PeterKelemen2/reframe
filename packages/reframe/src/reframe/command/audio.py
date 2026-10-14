"""Audio output tracks (05 §C-7 "Audio", 03 §Audio → Output tracks, decision 0013).

**Passthru** copies the source track (``-c:a:N copy``, plus the container's ``copy_args``:
``-strict -2`` for TrueHD in MP4). Nothing is snapped. When the container cannot hold the
codec, the track is encoded with the track's encoder (HandBrake's auto passthru; ``None`` =
AAC), like any encoded track.

**Encode**: ``-c:a:N <encoder>``, the bitrate (``-b:a:N``) or the VBR quality (``-q:a:N``),
the sample rate (``-ar:a:N``, always when a rate is known: FFmpeg silently picks a rate when
none is given, and ``loudnorm`` outputs 192 kHz), and one filter chain (``-filter:a:N``) in
this order:

1. the layout: ``aresample=[matrix_encoding=dplii:]out_chlayout=<layout>``
   (:attr:`PlannedAudio.layout`): the layout of the mixdown definition. When the source
   layout stays, libopus gets a layout it accepts (:data:`ENCODER_LAYOUTS`: side → back, else
   a downmix), and any other encoder the source layout, relabelled only where that is
   lossless (``5.1(side)`` → ``5.1``); see :func:`_kept_layout`;
2. the gain: ``volume=<gain>dB``;
3. loudness normalisation: two-pass ``loudnorm`` with the values measured by the track's
   ``analyse`` step (:class:`~reframe.models.ArgTemplate`), ``linear=true``.

The mixdown is in the chain, not ``-ac``, so that ``loudnorm`` measures and corrects the
audio that is encoded. **DRC** (HandBrake's dynamic range compression, 0 = off) is the AC-3
and E-AC-3 decoder option ``-drc_scale`` (an input option for the source stream; FFmpeg's
default is 1, HandBrake's 0).

**Snapping** (decision 0024 item 4, 0013 "Follow-up (M2 wave 2b)"): a mixdown, bitrate or
sample rate that the encoder cannot do is replaced by one it can do, with C-6's helpers, so
that the builder (C-7), validation (C-8) and the codec rules (C-12) give the same answer
(:func:`planned_audio`):

- mixdown: :meth:`~reframe.definitions.AudioEncoderDef.snap_mixdown`. Never an upmix
  (decision 0019 item 3: a 5.1 mixdown on a stereo source keeps the stereo; Dolby Pro Logic
  II on two channels or fewer keeps the source layout); a layout the encoder cannot make
  becomes its largest layout below (AC-3 and E-AC-3 make 5.1 of 7.1, MP3 stereo of 5.1);
- bitrate: :meth:`~reframe.definitions.AudioBitrateDef.snap` (down, as HandBrake does)
  in the table of the effective mixdown: the snapped mixdown, or
  :func:`~reframe.definitions.channels_mixdown` of the source when its layout stays. With
  no bitrate and no VBR quality, the table's default;
- sample rate: :meth:`~reframe.definitions.AudioEncoderDef.snap_samplerate` of the track's
  rate, or of the source's (a tie goes to the higher rate).
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

#: The channels of FFmpeg's named layouts up to eight channels (``ffmpeg -layouts``,
#: n9.0.2; the most any encoder of the definitions takes). A layout without a name reads
#: ``N channels (A+B+…)``: :func:`layout_channels`.
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

#: Encoders that refuse every layout but these, largest last. FFmpeg lists no layouts for
#: them (``ffmpeg -h encoder=libopus``), so it does not convert a layout for them by itself:
#: libopus takes only the Vorbis channel orders of mapping family -1 and fails on any other
#: ("Invalid channel layout 5.0(side) for specified mapping family -1", exit 234). The other
#: encoders take every layout (aac, flac), or FFmpeg converts it to one they list (ac3,
#: eac3, libmp3lame). Checked with both n9.0.2 builds (testdata/README.md).
ENCODER_LAYOUTS: dict[str, tuple[str, ...]] = {
    "libopus": ("mono", "stereo", "3.0", "quad", "5.0", "5.1", "6.1", "7.1"),
}

_SIDE_TO_BACK = {"SL": "BL", "SR": "BR"}
_UNNAMED_LAYOUT = re.compile(r"\d+ channels \(([A-Za-z0-9]+(?:\+[A-Za-z0-9]+)*)\)")


def layout_channels(layout: str | None) -> tuple[str, ...] | None:
    """The channels of an ffprobe ``channel_layout`` (``5.1(side)``, ``3 channels
    (FL+FR+LFE)``); ``None`` when not known."""
    if layout is None:
        return None
    named = LAYOUT_CHANNELS.get(layout)
    if named is not None:
        return named
    unnamed = _UNNAMED_LAYOUT.fullmatch(layout)
    return tuple(unnamed.group(1).split("+")) if unnamed is not None else None


def _side_to_back(channels: tuple[str, ...]) -> frozenset[str] | None:
    """The channels with the side pair renamed to the back pair (``5.1(side)`` → ``5.1``),
    when the layout has a side pair and no back pair; else ``None``."""
    have = set(channels)
    if not {"SL", "SR"} <= have or have & {"BL", "BR"}:
        return None
    return frozenset(_SIDE_TO_BACK.get(c, c) for c in channels)


def _kept_layout(
    stream: AudioStream, encoder: AudioEncoderDef, table: Mixdown, defs: Definitions
) -> str | None:
    """The ``out_chlayout`` written when the source layout stays (no mixdown), or ``None``.

    - An encoder of :data:`ENCODER_LAYOUTS` gets a layout it accepts: the source's, else the
      side → back relabel of it (lossless: the same PCM), else the largest accepted layout
      made of the source's channels (a downmix: ``2.1`` → ``stereo``, ``6.0`` → ``5.0``).
    - Any other encoder gets the source layout. Only ``5.1(side)`` and the like are relabelled
      to the layout of the bitrate table (``5.1``), which is lossless; ``6.0`` or
      ``7.1(wide)`` are not remixed to ``5.1`` / ``7.1``.
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


# --------------------------------------------------------------------------- what is written


@dataclass(frozen=True, slots=True)
class PlannedAudio:
    """What the builder writes for one output audio track (:func:`planned_audio`).

    A copy has only ``copy = True``. An encoded track has its encoder and the snapped values
    (decision 0024 item 4) that go into its arguments: ``mixdown`` → the ``aresample`` layout
    of ``-filter:a:N``, ``bitrate`` → ``-b:a:N``, ``quality`` → the VBR option (``-q:a:N``),
    ``samplerate`` → ``-ar:a:N``.
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
    """The ``out_chlayout`` of the ``aresample`` in ``-filter:a:N`` (with
    ``matrix_encoding=dplii`` for Dolby Pro Logic II); ``None`` = the encoder gets the source
    layout. With a mixdown, its layout (unless the source has it already); without one, a
    lossless relabel (``5.1(side)`` → ``5.1``) or, for libopus, the layout it accepts
    (:data:`ENCODER_LAYOUTS`: ``2.1`` → ``stereo``)."""
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
    found = defs.containers.get(container)
    if found is None:
        raise PlanError(f"unknown container {container!r}")
    return found


def _bitrate(
    track: AudioOutputTrack, encoder: AudioEncoderDef, table: Mixdown
) -> tuple[int | None, float | None]:
    """``(bitrate, quality)`` of an encoded track (decision 0013 §4, snapped by 0024)."""
    rates = encoder.bitrate
    if rates is None:
        return None, None  # lossless (FLAC)
    if track.bitrate is not None:
        snapped = rates.snap(track.bitrate, table)
        # ``None``: the encoder has no table for this layout (no defined encoder; the
        # linter checks that every mixdown has one): FFmpeg gets the value as it is.
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


# --------------------------------------------------------------------------- arguments


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


def _layout_filter(planned: PlannedAudio, definitions: Definitions) -> str | None:
    """``aresample=[matrix_encoding=dplii:]out_chlayout=…`` for :attr:`PlannedAudio.layout`."""
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
        out = AudioOut(index=index, stream=stream, copy=True)
        out.args = [spec("-c:a", a), "copy"]
        out.global_args = list(container.audio.copy_args.get(stream.codec or "", []))
        return out
    out = AudioOut(
        index=index, stream=stream, copy=False, encoder=encoder, fallback=planned.fallback
    )
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
