"""The codec-rule stage of the audio defaults (03 §Audio defaults part 2 and 3; 05 §C-12).

For each selected source audio track, the codec rules are checked from top to bottom; **the
first matching rule wins**. A rule matches on its languages (``None`` = any) and on a
condition on the **source** channels. The matched rule then decides passthru or encode with
the bitrate rules of 03 ("Reframe never makes a track bigger than its source"):

=================================================  ========================================
Source                                             Result
=================================================  ========================================
A bit rate above the max (``Lossless source``      Encode at the max (snapped to the
when it is lossless), or lossless and unknown      encoder's allowed values)
The source **fits**                                Passthru (or re-encode if the rule says
                                                   so)
At or below the max, but it does not fit           Encode at the smallest allowed value at
                                                   or above the source bit rate
Bit rate unknown                                   As above the max; the preview offers
                                                   **Measure**
=================================================  ========================================

The source fits when its codec is on the passthru list and allowed by the
:class:`~reframe.models.PassthruPolicy`, the container can hold it, its channels are within
the rule's mixdown, its bit rate is at or below the max, and the rule changes nothing that
needs a decode (gain, DRC, loudness, sample rate). A rule whose codec is ``passthru`` encodes
with the policy's fallback encoder when the source does not fit.

Interpretations of the plan (decision 0019): a mixdown never upmixes; a lossless source with
a known bit rate at or below the max is treated like any other source; the example of 03 is
reproduced with its last row corrected (192 kb/s is above a 160 kb/s max).

Pure: no I/O.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Literal

from reframe import languages
from reframe.batch.metadata import effective_language, render_track_name, track_metadata
from reframe.definitions import AudioEncoderDef, ContainerDef, Definitions, load_definitions
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
    "PASSTHRU",
    "apply_codec_rules",
    "channels_match",
    "language_matches",
    "passthru_codec",
    "requested_mixdown",
]

#: ``AudioCodecRule.codec`` / ``ExtraAudioOutput.codec`` value for "Passthru".
PASSTHRU = "passthru"

_CHANNEL_CONDITIONS: dict[SourceChannels, str] = {
    "any": "any channels",
    "mono": "mono",
    "stereo_or_less": "stereo or less",
    "5.1_or_more": "5.1 or more",
    "7.1_or_more": "7.1 or more",
}

BitrateState = Literal["no_max", "within", "above", "lossless", "unknown"]


# --------------------------------------------------------------------------- matching


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
    """The passthru codec of the source track (``Definitions.passthru_codecs``, matched on the
    ffprobe codec name and profile: DTS-HD MA is ``dtshd``, a DTS core ``dts``), or ``None``
    when the codec cannot be passed through (PCM, Vorbis, ALAC…)."""
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
    """The output layout a rule asks for; ``None`` = keep the source layout.

    ``keep`` keeps it; ``up_to_5.1`` makes 5.1 of a source with more channels and keeps the
    others; ``5.1``, ``stereo`` and ``mono`` downmix a source with more channels and name
    the layout of a source with as many; ``dpl2`` matrix-encodes a source with more than two
    channels. A mixdown never upmixes (decision 0019): FFmpeg's upmix only adds silent
    channels, so a source with fewer channels keeps its layout. An unknown channel count
    (0) gets the rule's layout.
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


def _bitrate_key(channels: int) -> Mixdown:
    """The bit-rate table of a kept source layout: 1 → mono, 2 → stereo, 3 to 6 → 5.1, more →
    7.1 (unknown → stereo)."""
    if channels == 1:
        return "mono"
    if channels <= 2:
        return "stereo"
    if channels <= 6:
        return "5.1"
    return "7.1"


# --------------------------------------------------------------------------- formatting


def _kbps(bits_per_second: int) -> str:
    """``224000`` → ``224``, ``128453`` → ``128.5``."""
    value = bits_per_second / 1000
    return str(int(value)) if value.is_integer() else f"{value:.1f}".rstrip("0").rstrip(".")


def _source_layout(stream: AudioStream) -> str:
    return audio_channels_label(stream.channels, stream.channel_layout)


def _mixdown_label(mixdown: Mixdown, definitions: Definitions) -> str:
    """``5.1``, ``7.1``, ``Stereo``, ``Mono``, ``Dolby Pro Logic II``."""
    return definitions.mixdowns[mixdown].label


def _layout_label(mixdown: Mixdown, definitions: Definitions) -> str:
    """The channel layout of a mixdown for names: ``5.1``, ``2.0``, ``1.0``."""
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


# --------------------------------------------------------------------------- one output


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


def _passthru(ctx: _Context, request: _Request, state: BitrateState) -> _Outcome:
    stream = ctx.stream
    fallback = ctx.policy.fallback_encoder if request.codec == PASSTHRU else request.codec
    track = AudioOutputTrack(action="passthru", encoder=fallback, source_stream=stream.index)
    label = (
        ctx.defs.passthru_codecs[ctx.source_key].label
        if ctx.source_key is not None
        else ctx.source_label
    )
    parts = [label, _source_layout(stream)]
    if state == "within" and stream.bitrate.value is not None:
        parts.append(f"{_kbps(stream.bitrate.value)} ≤ {request.max_bitrate}")
    return _Outcome(
        track=track,
        passthru=True,
        sentences=[f"{', '.join(parts)}: passthru"],
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
    if encoder is None or not encoder.mixdowns:
        return mixdown
    wanted = defs.mixdowns[mixdown].channels if mixdown is not None else stream.channels
    if mixdown is not None and mixdown in encoder.mixdowns:
        return mixdown
    if mixdown is None and wanted <= encoder.max_channels:
        return None
    candidates = [
        m for m in encoder.mixdowns if m != "dpl2" and defs.mixdowns[m].channels <= wanted
    ]
    best = (
        max(candidates, key=lambda m: defs.mixdowns[m].channels)
        if candidates
        else encoder.mixdowns[0]
    )
    shown = _mixdown_label(mixdown, defs) if mixdown is not None else _source_layout(stream)
    notes.append(f"{encoder.label} cannot make {shown}: {_mixdown_label(best, defs)}")
    return best


def _samplerate(request: _Request, encoder: AudioEncoderDef | None, notes: list[str]) -> int | None:
    rate = request.extras.samplerate
    if rate is None or encoder is None or not encoder.samplerates or rate in encoder.samplerates:
        return rate
    closest = min(encoder.samplerates, key=lambda r: (abs(r - rate), -r))
    notes.append(f"{encoder.label} has no {rate} Hz: {closest} Hz")
    return closest


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
    out_channels = defs.mixdowns[mixdown].channels if mixdown is not None else stream.channels
    if mixdown is not None and 0 < out_channels < stream.channels:
        sentences.append(f"Downmix {_source_layout(stream)} → {_mixdown_label(mixdown, defs)}")

    bitrate: int | None = None
    if encoder is None:
        bitrate = request.max_bitrate
        sentences.append(f"Encode to {label}")
    elif encoder.bitrate is None:
        sentences.append(_sentence(f"{why + ': ' if why else ''}encode to {label} (lossless)"))
    else:
        key = mixdown if mixdown is not None else _bitrate_key(stream.channels)
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
                elif effective == "unknown":
                    sentences.append("Bitrate unknown: treated as above the max; Measure")
                    measure = True
                else:
                    assert value is not None
                    sentences.append(f"{_kbps(value)} > {maximum} → {at_max}")

    extras = request.extras
    track = AudioOutputTrack(
        action="encode",
        encoder=encoder_id,
        mixdown=mixdown,
        samplerate=_samplerate(request, encoder, notes),
        bitrate=bitrate,
        gain=extras.gain,
        drc=extras.drc,
        loudness=extras.loudness,
        source_stream=stream.index,
    )
    channels = _layout_label(mixdown, defs) if mixdown is not None else _source_layout(stream)
    return _Outcome(
        track=track,
        passthru=False,
        sentences=sentences,
        notes=notes,
        measure=measure,
        name_values={"channels": channels, "codec": label, "bitrate": bitrate},
    )


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


def _resolve(ctx: _Context, request: _Request) -> _Outcome:
    blockers = _blockers(ctx, request)
    state = _bitrate_state(ctx.stream, request.max_bitrate)
    wants_passthru = request.codec == PASSTHRU or request.if_fits == "passthru"
    if wants_passthru and not blockers and state in ("no_max", "within"):
        return _passthru(ctx, request, state)
    return _encode(ctx, request, state, blockers)


def _describe(track: AudioOutputTrack, defs: Definitions) -> str:
    """``AC-3 5.1 · 320 kb/s``, ``AAC Stereo``, ``Passthru``."""
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


# --------------------------------------------------------------------------- the stage


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

    ``first_of_language``: whether this track is the first selected track of its language,
    for rules with ``first_track_of_language_only`` (in M2, where every track is selected,
    :func:`~reframe.batch.draft_tracks` passes "first in source order"). A rule limited to
    the first track does not match the others; the next rule is checked.

    No rule matching (only possible when the catch-all is limited to the first track) is
    data: no output, and the decision says why.
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
            skipped.append(f"Rule {number} needs {_CHANNEL_CONDITIONS[rule.source_channels]}")
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
