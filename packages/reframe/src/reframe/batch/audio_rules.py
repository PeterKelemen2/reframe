"""Codec rules of the audio defaults. The first matching rule wins. A source passes through
only when its codec is allowed, the container can hold it, its channels fit the rule's
mixdown, and the rule changes nothing that needs a decode. A lossy source that fits passes
through at any bit rate, since a re-encode only loses quality; a lossless one fits only at or
below the max. Reframe never makes a track bigger than its source. Bit rates, layouts and
sample rates snap with the encoder's helpers, so the command builder, validation and these
rules agree on the same track. Pure: no I/O.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Literal

from reframe import languages
from reframe.batch.metadata import effective_language, render_track_name, track_metadata
from reframe.command import PlanError, planned_audio
from reframe.command.audio import layout_channels
from reframe.definitions import (
    AudioEncoderDef,
    ContainerDef,
    Definitions,
    channels_mixdown,
    load_definitions,
)
from reframe.models.defaults import (
    AudioDefaults,
    AudioRuleExtras,
    PassthruCodec,
    PassthruPolicy,
    RuleMixdown,
    SourceChannels,
    TrackDecision,
)
from reframe.models.job import AudioOutputTrack, Container, Mixdown
from reframe.models.media import AudioStream
from reframe.naming.context import audio_channels_label
from reframe.naming.template import Value

__all__ = [
    "CHANNEL_CONDITIONS",
    "PASSTHRU",
    "apply_codec_rules",
    "bitrate_table",
    "channels_match",
    "language_matches",
    "passthru_codec",
    "requested_mixdown",
    "snap_note",
]

#: The codec value that means passthru in a rule or an extra output.
PASSTHRU = "passthru"

#: The reason text of each source-channels condition.
CHANNEL_CONDITIONS: dict[SourceChannels, str] = {
    "any": "any channels",
    "mono": "mono",
    "stereo_or_less": "stereo or less",
    "5.1_or_more": "5.1 or more",
    "7.1_or_more": "7.1 or more",
}

#: Appended to the reason of a lossy source that is kept above the max.
_KEPT_ABOVE = " (a lossy source is kept above the max)"

BitrateState = Literal["no_max", "within", "above", "lossless", "unknown"]


def channels_match(condition: SourceChannels, channels: int) -> bool:
    """The rule's source-channels condition. An unknown channel count (0) matches only
    ``any``."""
    if condition == "any":
        return True
    if channels <= 0:
        return False
    match condition:
        case "mono":
            return channels == 1
        case "stereo_or_less":
            return channels <= 2
        case "5.1_or_more":
            return channels >= 6
        case "7.1_or_more":
            return channels >= 8


def language_matches(rule_languages: list[str] | None, stream: AudioStream) -> bool:
    """``None`` = any language; else one of the rule's languages matches the track's effective
    language (:func:`reframe.languages.matches`: rule ``pt`` takes ``pt-BR``)."""
    if rule_languages is None:
        return True
    language = effective_language(stream)
    return any(languages.matches(tag, language) for tag in rule_languages)


def passthru_codec(stream: AudioStream, definitions: Definitions) -> PassthruCodec | None:
    """The passthru codec key of the source track, matched on the ffprobe codec name and profile
    (``Definitions.passthru_codecs``), or ``None`` when the codec cannot be passed through."""
    for key, codec in definitions.passthru_codecs.items():
        if stream.codec != codec.codec_name:
            continue
        if codec.profiles is not None and stream.profile not in codec.profiles:
            continue
        if stream.profile is not None and stream.profile in codec.exclude_profiles:
            continue
        return key
    return None


def requested_mixdown(
    rule_mixdown: RuleMixdown, source_channels: int, definitions: Definitions
) -> Mixdown | None:
    """The output layout a rule asks for; ``None`` = keep the source layout. A mixdown never
    upmixes: FFmpeg's upmix adds silent channels, so a source with fewer channels keeps its
    layout. With the same channel count, ``up_to_5.1`` and ``dpl2`` keep the source layout and
    the other mixdowns name it. An unknown channel count (0) gets the rule's layout.

    The encoder's ``snap_mixdown`` then gives the layout it really makes. It applies the same
    no-upmix rule, so the two cannot disagree.
    """
    target = _target_mixdown(rule_mixdown)
    if target is None:
        return None
    channels = definitions.mixdowns[target].channels
    if source_channels == 0 or source_channels > channels:
        return target
    if source_channels == channels and rule_mixdown not in ("up_to_5.1", "dpl2"):
        return target
    return None


def _target_mixdown(rule_mixdown: RuleMixdown) -> Mixdown | None:
    """The layout a rule mixdown stands for (``None`` for ``keep``)."""
    match rule_mixdown:
        case "keep":
            return None
        case "up_to_5.1":
            return "5.1"
        case _:
            return rule_mixdown


def _kbps(bits_per_second: int) -> str:
    value = bits_per_second / 1000
    return str(int(value)) if value.is_integer() else f"{value:.1f}".rstrip("0").rstrip(".")


def _source_layout(stream: AudioStream) -> str:
    return audio_channels_label(stream.channels, stream.channel_layout)


def _mixdown_label(mixdown: Mixdown, definitions: Definitions) -> str:
    return definitions.mixdowns[mixdown].label


def _layout_label(mixdown: Mixdown, definitions: Definitions) -> str:
    mix = definitions.mixdowns[mixdown]
    return f"{mix.channels - mix.lfe}.{mix.lfe}"


def _source_label(stream: AudioStream, key: PassthruCodec | None, defs: Definitions) -> str:
    if stream.display_codec:
        return stream.display_codec
    if key is not None:
        return defs.passthru_codecs[key].label
    return stream.codec or "unknown codec"


def _sentence(text: str) -> str:
    return text[:1].upper() + text[1:]


@dataclass(slots=True)
class _Request:
    """One output a rule asks for: the rule itself, or one of its extra outputs."""

    codec: str
    mixdown: RuleMixdown
    max_bitrate: int | None
    if_fits: Literal["passthru", "reencode"]
    extras: AudioRuleExtras


@dataclass(slots=True)
class _Outcome:
    track: AudioOutputTrack
    passthru: bool
    sentences: list[str]
    """The reason, without the rule prefix."""
    notes: list[str] = field(default_factory=list)
    measure: bool = False
    kept_above: bool = False
    """A lossy source passed through above the max."""
    name_values: dict[str, Value] = field(default_factory=dict)


@dataclass(slots=True)
class _Context:
    stream: AudioStream
    policy: PassthruPolicy
    container: ContainerDef
    defs: Definitions
    source_key: PassthruCodec | None
    source_label: str


def _bitrate_state(stream: AudioStream, max_kbps: int | None) -> BitrateState:
    if max_kbps is None:
        return "no_max"
    value = stream.bitrate.value
    if value is None:
        return "lossless" if stream.lossless else "unknown"
    if value > max_kbps * 1000:
        return "lossless" if stream.lossless else "above"
    return "within"


def _blockers(ctx: _Context, request: _Request) -> list[str]:
    """Why the source cannot be passed through, apart from its bit rate (empty = it can)."""
    stream, defs = ctx.stream, ctx.defs
    found: list[str] = []
    if ctx.source_key is None:
        found.append(f"{ctx.source_label} cannot be passed through")
    elif ctx.source_key not in ctx.policy.allowed:
        found.append(f"{defs.passthru_codecs[ctx.source_key].label} passthru is not allowed")
    if stream.codec is None or not ctx.container.audio.can_copy(stream.codec):
        found.append(f"{ctx.container.label} cannot hold {ctx.source_label}")
    target = _target_mixdown(request.mixdown)
    if target is not None and stream.channels > defs.mixdowns[target].channels:
        found.append(f"{_source_layout(stream)} is more than {_mixdown_label(target, defs)}")
    extras = request.extras
    if extras.gain:
        found.append("the rule changes the gain")
    if extras.drc:
        found.append("the rule applies DRC")
    if extras.loudness != "off":
        found.append("the rule normalises the loudness")
    if extras.samplerate is not None and extras.samplerate != stream.sample_rate:
        found.append(f"the rule resamples to {extras.samplerate} Hz")
    return found


def _passthru(
    ctx: _Context, request: _Request, state: BitrateState, maximum: int | None
) -> _Outcome:
    """``maximum``: the rule's max, or the encoder's default that a lossless source was
    compared with when the rule has none."""
    stream = ctx.stream
    fallback = ctx.policy.fallback_encoder if request.codec == PASSTHRU else request.codec
    track = AudioOutputTrack(action="passthru", encoder=fallback, source_stream=stream.index)
    label = (
        ctx.defs.passthru_codecs[ctx.source_key].label
        if ctx.source_key is not None
        else ctx.source_label
    )
    parts = [label, _source_layout(stream)]
    value = stream.bitrate.value
    if state == "within" and value is not None:
        default = " (the default)" if request.max_bitrate is None else ""
        parts.append(f"{_kbps(value)} ≤ {maximum}{default}")
    elif state == "above" and value is not None:
        parts.append(f"{_kbps(value)} > {maximum}")
    return _Outcome(
        track=track,
        passthru=True,
        sentences=[f"{', '.join(parts)}: passthru{_KEPT_ABOVE if state == 'above' else ''}"],
        kept_above=state == "above",
        name_values={
            "channels": _source_layout(stream),
            "codec": ctx.source_label,
            "bitrate": None,
        },
    )


def _output_mixdown(
    ctx: _Context, request: _Request, encoder: AudioEncoderDef | None, notes: list[str]
) -> Mixdown | None:
    stream, defs = ctx.stream, ctx.defs
    mixdown = requested_mixdown(request.mixdown, stream.channels, defs)
    target = _target_mixdown(request.mixdown)
    if (
        request.mixdown != "up_to_5.1"
        and target is not None
        and 0 < stream.channels < defs.mixdowns[target].channels
    ):
        notes.append(f"{_source_layout(stream)} source: no upmix to {_mixdown_label(target, defs)}")
    if encoder is None:
        return mixdown
    snapped = encoder.snap_mixdown(mixdown, stream.channels, defs.mixdowns)
    if snapped != mixdown:
        shown = _mixdown_label(mixdown, defs) if mixdown is not None else _source_layout(stream)
        got = _mixdown_label(snapped, defs) if snapped is not None else _source_layout(stream)
        notes.append(f"{encoder.label} cannot make {shown}: {got}")
    return snapped


def _samplerate(
    ctx: _Context, request: _Request, encoder: AudioEncoderDef | None, notes: list[str]
) -> int | None:
    """The rule's sample rate (``None`` = the source's), snapped to the encoder. ``None`` stays
    when the encoder takes the source's own rate; a source rate the encoder lacks becomes the
    snapped rate, as the command builder writes it."""
    rate = request.extras.samplerate
    if encoder is None:
        return rate
    source_rate = ctx.stream.sample_rate
    snapped = encoder.snap_samplerate(rate, source_rate)
    wanted = rate if rate is not None else source_rate
    if snapped == wanted:
        return rate
    whose = "" if rate is not None else " (the source's rate)"
    notes.append(f"{encoder.label} has no {wanted} Hz{whose}: {snapped} Hz")
    return snapped


@dataclass(frozen=True, slots=True)
class _Written:
    """The layout the command builder writes for an encoded track
    (:func:`~reframe.command.planned_audio`)."""

    table: Mixdown
    """The bitrate table: the mixdown, else :func:`channels_mixdown` of the written
    channels."""
    layout: str | None = None
    """The ``out_chlayout`` when the source layout stays but is converted, such as a lossless
    relabel or a layout the encoder takes instead of the source's."""
    channels: int = 0
    """The channel count of :attr:`layout` (0 without one)."""


def _written(ctx: _Context, encoder: AudioEncoderDef, mixdown: Mixdown | None) -> _Written:
    """What the command builder writes for ``encoder`` and the snapped ``mixdown``, so that the
    codec rules cap the bitrate with the same table as the builder and validation."""
    track = AudioOutputTrack(action="encode", encoder=encoder.id, mixdown=mixdown)
    try:
        planned = planned_audio(track, ctx.stream, ctx.container, definitions=ctx.defs)
    except PlanError:  # the container cannot hold the encoder: a note says so
        return _Written(mixdown or channels_mixdown(ctx.stream.channels))
    assert planned.bitrate_mixdown is not None  # an encoded track always has a table
    if mixdown is not None or planned.layout is None:
        return _Written(planned.bitrate_mixdown)
    written = layout_channels(planned.layout)
    return _Written(planned.bitrate_mixdown, planned.layout, len(written or ()))


def _encode(ctx: _Context, request: _Request, state: BitrateState, blockers: list[str]) -> _Outcome:
    stream, defs = ctx.stream, ctx.defs
    wants_passthru = request.codec == PASSTHRU or request.if_fits == "passthru"
    encoder_id = ctx.policy.fallback_encoder if request.codec == PASSTHRU else request.codec
    encoder = defs.audio_encoders.get(encoder_id)
    label = encoder.label if encoder is not None else encoder_id
    notes: list[str] = []
    sentences: list[str] = []
    measure = False

    if request.codec == PASSTHRU:
        cause = f"{blockers[0]} → " if blockers else ""
        sentences.append(_sentence(f"{cause}fallback encoder {label}"))
    if not wants_passthru:
        why = "the rule says re-encode"
    elif request.codec == PASSTHRU:
        why = ""  # the fallback sentence says it
    else:
        why = blockers[0] if blockers else ""

    if encoder is None:
        notes.append(f"Unknown audio encoder {encoder_id!r}: its bit rates are not checked")
    elif encoder.codec not in ctx.container.audio.encode:
        notes.append(f"{ctx.container.label} cannot hold {encoder.label}")

    mixdown = _output_mixdown(ctx, request, encoder, notes)
    written = _written(ctx, encoder, mixdown) if encoder is not None else None
    out_channels = defs.mixdowns[mixdown].channels if mixdown is not None else stream.channels
    if mixdown is not None and 0 < out_channels < stream.channels:
        sentences.append(f"Downmix {_source_layout(stream)} → {_mixdown_label(mixdown, defs)}")
    channels_label = _layout_label(mixdown, defs) if mixdown is not None else _source_layout(stream)
    if written is not None and written.layout is not None:
        channels_label = audio_channels_label(written.channels, written.layout)
        if written.channels < stream.channels:
            # libopus refuses the source layout; the command builder writes one it takes.
            assert encoder is not None
            sentences.append(f"Downmix {_source_layout(stream)} → {channels_label}")
            notes.append(f"{encoder.label} cannot take {stream.channel_layout}: {channels_label}")

    bitrate: int | None = None
    if encoder is None:
        bitrate = request.max_bitrate
        sentences.append(f"Encode to {label}")
    elif encoder.bitrate is None:
        sentences.append(_sentence(f"{why + ': ' if why else ''}encode to {label} (lossless)"))
    else:
        assert written is not None
        key = written.table
        limits = encoder.bitrate.by_mixdown.get(key)
        if limits is None:  # pragma: no cover - _output_mixdown picks a mixdown it has
            sentences.append(f"Encode to {label}")
        else:
            maximum = request.max_bitrate or limits.default
            at_max = "encode at the max" if request.max_bitrate else "encode at the default"
            cap = encoder.bitrate.snap(maximum, key, "down")
            assert cap is not None
            if cap != maximum:
                notes.append(_snap_note(maximum, cap, encoder, key, defs))
            effective = _bitrate_state(stream, maximum)
            value = stream.bitrate.value
            if effective == "within" and value is not None:
                wanted = math.ceil(value / 1000)
                up = encoder.bitrate.snap(wanted, key, "up")
                assert up is not None
                bitrate = min(up, cap)
                head = f"{_kbps(value)} ≤ {maximum}" + (f", but {why}" if why else "")
                if bitrate == cap:
                    sentences.append(f"{head} → {at_max}")
                else:
                    sentences.append(
                        f"{head} → encode at {bitrate} kb/s, the smallest allowed value"
                        f" ≥ {_kbps(value)}"
                    )
                    if bitrate != wanted:
                        notes.append(_snap_note(wanted, bitrate, encoder, key, defs))
            else:
                bitrate = cap
                if effective == "lossless":
                    sentences.append(f"Lossless source → {at_max}")
                    measure = value is None
                elif effective == "unknown":
                    # A lossy source only gets here when it does not fit.
                    if why:
                        sentences.append(_sentence(why))
                    sentences.append("Bitrate unknown: treated as above the max; Measure")
                    measure = True
                else:
                    assert value is not None
                    above = f"{_kbps(value)} > {maximum} → {at_max}"
                    sentences.append(_sentence(f"{why}, {above}") if why else above)

    extras = request.extras
    track = AudioOutputTrack(
        action="encode",
        encoder=encoder_id,
        mixdown=mixdown,
        samplerate=_samplerate(ctx, request, encoder, notes),
        bitrate=bitrate,
        gain=extras.gain,
        drc=extras.drc,
        loudness=extras.loudness,
        source_stream=stream.index,
    )
    return _Outcome(
        track=track,
        passthru=False,
        sentences=sentences,
        notes=notes,
        measure=measure,
        name_values={"channels": channels_label, "codec": label, "bitrate": bitrate},
    )


def bitrate_table(
    encoder: AudioEncoderDef,
    rule_mixdown: RuleMixdown,
    stream: AudioStream,
    container: Container,
    definitions: Definitions,
) -> Mixdown:
    """The bit-rate table (a mixdown of ``encoder.bitrate.by_mixdown``) that a rule with
    ``rule_mixdown`` and ``encoder`` uses for ``stream``: the layout the command builder writes
    (``planned_audio``), the same table :func:`apply_codec_rules` caps with."""
    ctx = _Context(
        stream=stream,
        policy=PassthruPolicy(),
        container=definitions.containers[container],
        defs=definitions,
        source_key=None,
        source_label="",
    )
    wanted = requested_mixdown(rule_mixdown, stream.channels, definitions)
    mixdown = encoder.snap_mixdown(wanted, stream.channels, definitions.mixdowns)
    return _written(ctx, encoder, mixdown).table


def snap_note(
    wanted: int, got: int, encoder: AudioEncoderDef, key: Mixdown, definitions: Definitions
) -> str:
    """The note that says why a bit rate snapped, and to what."""
    return _snap_note(wanted, got, encoder, key, definitions)


def _snap_note(
    wanted: int, got: int, encoder: AudioEncoderDef, key: Mixdown, defs: Definitions
) -> str:
    assert encoder.bitrate is not None
    limits = encoder.bitrate.by_mixdown[key]
    where = f"{encoder.label} {_mixdown_label(key, defs)}"
    if wanted > limits.max:
        why = f"{where} goes up to {limits.max} kb/s"
    elif wanted < limits.min:
        why = f"{where} needs at least {limits.min} kb/s"
    else:
        why = f"{wanted} kb/s is not an allowed {where} bit rate"
    return f"{why}: {wanted} → {got} kb/s"


def _default_max(ctx: _Context, request: _Request) -> int | None:
    """The max of a lossy rule without one: the encoder's default bit rate for the layout it
    would encode (the same layout and table as :func:`_encode`). ``None`` for a ``passthru``
    rule (anything that fits passes), a lossless or unknown encoder."""
    if request.max_bitrate is not None or request.codec == PASSTHRU:
        return request.max_bitrate
    encoder = ctx.defs.audio_encoders.get(request.codec)
    if encoder is None or encoder.bitrate is None:
        return None
    channels = ctx.stream.channels
    wanted = requested_mixdown(request.mixdown, channels, ctx.defs)
    mixdown = encoder.snap_mixdown(wanted, channels, ctx.defs.mixdowns)
    limits = encoder.bitrate.by_mixdown.get(_written(ctx, encoder, mixdown).table)
    return limits.default if limits is not None else None


def _resolve(ctx: _Context, request: _Request) -> _Outcome:
    blockers = _blockers(ctx, request)
    state = _bitrate_state(ctx.stream, request.max_bitrate)
    maximum = request.max_bitrate
    if state == "no_max" and ctx.stream.lossless:
        # A lossless source is compared with the encoder's default when the rule has no max;
        # a lossy one still fits at any bit rate.
        maximum = _default_max(ctx, request)
        state = _bitrate_state(ctx.stream, maximum)
    wants_passthru = request.codec == PASSTHRU or request.if_fits == "passthru"
    # A lossy source fits at any bit rate; a lossless one only at or below the max
    # (``_bitrate_state`` calls a lossless source above the max or unknown "lossless").
    if wants_passthru and not blockers and state != "lossless":
        return _passthru(ctx, request, state, maximum)
    return _encode(ctx, request, state, blockers)


def _describe(track: AudioOutputTrack, defs: Definitions) -> str:
    if track.action == "passthru":
        return "Passthru"
    encoder = defs.audio_encoders.get(track.encoder or "")
    text = encoder.label if encoder is not None else str(track.encoder)
    if track.mixdown is not None:
        text += f" {_mixdown_label(track.mixdown, defs)}"
    if track.bitrate is not None:
        text += f" · {track.bitrate} kb/s"
    return text


def _finish(
    ctx: _Context, outcome: _Outcome, extras: AudioRuleExtras, *, extra: bool
) -> AudioOutputTrack:
    """Add the metadata: the source's language, title (or the rule's name template) and
    flags. An extra output is never the default track."""
    stream = ctx.stream
    name: str | None = None
    if extras.name_template:
        language = effective_language(stream)
        values: dict[str, Value] = {
            "lang": language,
            "lang_name": languages.english_name(language),
            "lang_native": languages.native_name(language, capitalize=True),
            "title": stream.title,
            "source_codec": ctx.source_label,
            **outcome.name_values,
        }
        name = render_track_name(extras.name_template, values)
    metadata = track_metadata(stream, name=name)
    if extra:
        metadata = metadata.model_copy(update={"default": False})
    return outcome.track.model_copy(update={"metadata": metadata})


def apply_codec_rules(
    stream: AudioStream,
    defaults: AudioDefaults,
    container: Container,
    *,
    definitions: Definitions | None = None,
    first_of_language: bool = True,
) -> tuple[list[AudioOutputTrack], TrackDecision]:
    """The output track(s) for one selected source audio track, and the decision with its
    reason. The first matching codec rule wins; its extra outputs follow its output.

    ``first_of_language``: whether this track is the first selected track of its language (first
    in the output order), for rules with ``first_track_of_language_only``. A rule limited to the
    first track does not match the others; the next rule is checked.

    No rule matching (only possible when the catch-all is limited to the first track) is data: no
    output, and the decision says why.
    """
    defs = definitions or load_definitions()
    key = passthru_codec(stream, defs)
    ctx = _Context(
        stream=stream,
        policy=defaults.passthru,
        container=defs.containers[container],
        defs=defs,
        source_key=key,
        source_label=_source_label(stream, key, defs),
    )
    skipped: list[str] = []
    for number, rule in enumerate(defaults.codec_rules, start=1):
        if not language_matches(rule.languages, stream):
            continue
        if not channels_match(rule.source_channels, stream.channels):
            skipped.append(f"Rule {number} needs {CHANNEL_CONDITIONS[rule.source_channels]}")
            continue
        if rule.extras.first_track_of_language_only and not first_of_language:
            skipped.append(f"Rule {number} is only for the first track of a language")
            continue
        main = _resolve(
            ctx,
            _Request(rule.codec, rule.mixdown, rule.max_bitrate, rule.if_fits, rule.extras),
        )
        outputs = [_finish(ctx, main, rule.extras, extra=False)]
        notes = list(main.notes)
        for n, extra_output in enumerate(rule.extras.extra_outputs, start=1):
            request = _Request(
                extra_output.codec,
                extra_output.mixdown,
                extra_output.bitrate,
                "passthru" if extra_output.codec == PASSTHRU else "reencode",
                rule.extras,
            )
            outcome = _resolve(ctx, request)
            track = _finish(ctx, outcome, rule.extras, extra=True)
            outputs.append(track)
            notes.append(
                f"Extra output {n}: {_describe(track, defs)} ({'. '.join(outcome.sentences)})"
            )
            notes.extend(outcome.notes)
        if skipped:
            sentences = [*skipped, f"Rule {number} matches"]
            if main.passthru:
                sentences[-1] += ", and the source fits"
                if main.kept_above:
                    sentences[-1] += _KEPT_ABOVE
            else:
                sentences.extend(main.sentences)
        else:
            sentences = main.sentences
        decision = TrackDecision(
            source_stream=stream.index,
            rule=number,
            outputs=outputs,
            reason=". ".join(sentences),
            notes=notes,
            measure=main.measure,
        )
        return outputs, decision
    decision = TrackDecision(
        source_stream=stream.index,
        reason=". ".join([*skipped, "No codec rule matches: the track is not encoded"]),
    )
    return [], decision
