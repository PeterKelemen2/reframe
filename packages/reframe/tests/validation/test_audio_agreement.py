"""C-12 x C-7 x C-8: the codec rules, the command builder and validation agree on every audio
value an encoder cannot do (decisions 0024, 0025, 0026).

The full product (no sampling) of

- source layouts: mono, stereo, 5.1, 5.1(side), 7.1 and an unknown channel count, each with
  a known sample rate (44.1 kHz, which Opus lacks) and without one; and the layouts libopus
  refuses, which C-7 makes into one it takes (``2.1``, ``3.0(back)`` → stereo, ``4.0`` →
  3.0, ``6.0`` → 5.0, ``7.1(wide)`` → 5.1), with the known rate;
- encoders: aac, ac3, eac3, libopus, flac, libmp3lame;
- requested bitrate: valid, between two steps, above the maximum, below the minimum (of the
  layout's table), and none with a VBR quality;
- requested mixdown: none, mono, stereo, dpl2, 5.1, 7.1;
- requested sample rate: none, a valid one (48 kHz), one the encoder lacks (47 kHz)

is 17 x 6 x 90 = 9180 tracks. For each track:

- **C-7**: ``build_plan`` writes ``-c:a:0``, ``-b:a:0`` (or the VBR option), ``-ar:a:0`` and
  the ``aresample`` layout (``PlannedAudio.layout``) that ``planned_audio`` says; the bitrate
  table follows the written channels.
- **C-8**: the info notes (``audio.bitrate_out_of_range``, ``audio.mixdown_unsupported``,
  ``audio.mixdown_upmix``, ``audio.samplerate_unsupported``, ``audio.quality_unsupported``)
  are there exactly when C-7 writes something other than the track asks for, and name what
  C-7 writes. Each fix leaves C-7's arguments unchanged and removes its note.
- **C-12**: ``apply_codec_rules`` with a rule that asks for the same values (a lossless
  source of unknown bit rate and ``if_fits="reencode"``, so the rule encodes at its max and
  the "never bigger than the source" cap does not apply) gives the values C-7 writes for the
  request; its already-snapped track has no snap notes (except the note on a layout libopus
  refuses, which a rule cannot name), and C-7 writes it unchanged (:data:`DISAGREE`). The rule
  mixdowns are ``keep`` (= none), ``mono``, ``stereo``, ``dpl2``, ``5.1`` and ``up_to_5.1``
  (rules have no 7.1). C-12's effective values: ``track.samplerate or
  snap_samplerate(None, source rate)``; the mixdown is the rule's ``requested_mixdown``
  snapped.
"""

from __future__ import annotations

import dataclasses
import functools
import importlib.util
import itertools
import sys
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Any, get_args

import pytest

from reframe.batch import apply_codec_rules
from reframe.batch.audio_rules import requested_mixdown
from reframe.command import PlannedAudio, build_plan, planned_audio
from reframe.command.audio import layout_channels
from reframe.definitions import Definitions, channels_mixdown
from reframe.models import (
    AudioCodecRule,
    AudioDefaults,
    AudioOutputTrack,
    AudioRuleExtras,
    AudioStream,
    Mixdown,
    RuleMixdown,
    Severity,
    ValidationIssue,
)
from reframe.validation import JOB_RULES, validate


def _load(name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        f"_reframe_validation_{name}", Path(__file__).with_name(f"{name}.py")
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


sc = _load("scenario")
DEFS: Definitions = sc.DEFS
CAPS = sc.make_caps()
TOOLS = sc.make_tools()
#: The rules that can give an error or a note for an audio track.
RULES = [r for r in JOB_RULES if r.area in ("encoder", "container", "audio")]
SNAP_CODES = {
    "audio.bitrate_out_of_range",
    "audio.mixdown_unsupported",
    "audio.mixdown_upmix",
    "audio.samplerate_unsupported",
    "audio.quality_unsupported",
}
MIXDOWN_CODES = {"audio.mixdown_unsupported", "audio.mixdown_upmix"}

LAYOUTS: dict[str, tuple[int, str | None]] = {
    "mono": (1, "mono"),
    "stereo": (2, "stereo"),
    "5.1": (6, "5.1"),
    "5.1(side)": (6, "5.1(side)"),
    "7.1": (8, "7.1"),
    "unknown": (0, None),
    # Layouts libopus refuses (C-7 downmixes or relabels them, decision 0013 / M2 review).
    "2.1": (3, "2.1"),
    "3.0(back)": (3, "3.0(back)"),
    "4.0": (4, "4.0"),
    "6.0": (6, "6.0"),
    "7.1(wide)": (8, "7.1(wide)"),
}
SOURCE_RATES = {"44.1kHz": 44100, "no-rate": None}
ENCODERS = ["aac", "ac3", "eac3", "libopus", "flac", "libmp3lame"]
BITRATES = ["valid", "between", "above", "below", "vbr"]
MIXDOWNS: list[Mixdown | None] = [None, "mono", "stereo", "dpl2", "5.1", "7.1"]
assert set(MIXDOWNS) == {None, *get_args(Mixdown)}
SAMPLERATES = [None, 48000, 47000]
VBR_QUALITY = 2.0


def source_stream(layout: str, rate: int | None) -> AudioStream:
    """A lossless PCM track of unknown bit rate (stream 1)."""
    channels, name = LAYOUTS[layout]
    return AudioStream(
        index=1,
        type_index=0,
        codec="pcm_s24le",
        display_codec="PCM",
        channels=channels,
        channel_layout=name,
        sample_rate=rate,
        lossless=True,
        language="eng",
    )


# --------------------------------------------------------------------------- C-7


@dataclass(frozen=True)
class Written:
    """The audio arguments of ``build_plan`` for output track 0."""

    argv: tuple[str, ...]
    encoder: str
    bitrate: int | None
    quality: str | None
    samplerate: int | None
    layout: str | None
    """The ``aresample`` ``out_chlayout`` (``None``: the source layout is not changed)."""
    matrix: bool


def _value(argv: list[str], option: str) -> str | None:
    return argv[argv.index(option) + 1] if option in argv else None


def write(scenario: Any) -> Written:
    plan = build_plan(scenario.job, scenario.source, CAPS, TOOLS, definitions=DEFS)
    [step] = [s for s in plan.steps if s.kind == "encode"]
    argv = [a for a in step.argv if isinstance(a, str)]
    assert len(argv) == len(step.argv), "a loudnorm template in an agreement job"
    encoder = _value(argv, "-c:a:0")
    assert encoder is not None
    bitrate = _value(argv, "-b:a:0")
    quality_arg = DEFS.audio_encoders[encoder].quality
    quality = _value(argv, f"{quality_arg.arg}:0") if quality_arg is not None else None
    rate = _value(argv, "-ar:a:0")
    layout: str | None = None
    matrix = False
    for part in (_value(argv, "-filter:a:0") or "").split(","):
        if part.startswith("aresample="):
            options = dict(o.split("=", 1) for o in part.removeprefix("aresample=").split(":"))
            layout = options["out_chlayout"]
            matrix = options.get("matrix_encoding") == "dplii"
    return Written(
        argv=tuple(argv),
        encoder=encoder,
        bitrate=int(bitrate.removesuffix("k")) if bitrate is not None else None,
        quality=quality,
        samplerate=int(rate) if rate is not None else None,
        layout=layout,
        matrix=matrix,
    )


def check_builder(planned: PlannedAudio, written: Written, stream: AudioStream) -> None:
    """``planned_audio`` says what ``build_plan`` writes."""
    assert not planned.copy
    assert written.encoder == planned.encoder
    assert written.bitrate == planned.bitrate
    expected_quality = None if planned.quality is None else f"{planned.quality:g}"
    assert written.quality == expected_quality
    assert written.samplerate == planned.samplerate
    assert written.layout == planned.layout
    if planned.mixdown is None:
        # The source layout stays, relabelled, or made into a layout the encoder takes.
        assert not written.matrix
    else:
        target = DEFS.mixdowns[planned.mixdown]
        assert written.matrix == (target.matrix_encoding is not None)
        assert written.layout in (target.layout, None)
        if written.layout is None:
            assert stream.channel_layout == target.layout
    # The bitrate table follows the written channels.
    channels = layout_channels(written.layout or stream.channel_layout)
    if channels is not None and planned.bitrate_mixdown is not None and planned.mixdown is None:
        assert planned.bitrate_mixdown == channels_mixdown(len(channels))


# --------------------------------------------------------------------------- the jobs


@functools.cache
def _base(stream_json: str) -> Any:
    s = sc.base()
    s.source.audio = [AudioStream.model_validate_json(stream_json)]
    s.job.video.passthrough = True  # the video does not matter here, and is faster
    s.job.subtitles = []
    return s


def scenario(stream: AudioStream, track: AudioOutputTrack) -> Any:
    """The clean scenario (``scenario.base``) on ``stream``, with ``track`` as its only audio
    track. The base is shared: the job is a copy, and nothing else is changed."""
    base = _base(stream.model_dump_json())
    job = base.job.model_copy(
        update={"audio": [track.model_copy(update={"source_stream": stream.index})]}
    )
    return dataclasses.replace(base, job=job)


def issues_of(s: Any) -> list[ValidationIssue]:
    return validate(
        s.job, s.source, CAPS, TOOLS, s.fs, settings=s.settings, definitions=DEFS, rules=RULES
    )


def bitrate_for(category: str, encoder_id: str, table: Mixdown) -> int | None:
    """The requested bitrate of a category, for the layout's table."""
    rates = DEFS.audio_encoders[encoder_id].bitrate
    if category == "vbr":
        return None
    if rates is None:  # FLAC: a bitrate the lossless encoder does not use
        return {"valid": 640, "between": 650, "above": 9000, "below": 8}[category]
    limits = rates.by_mixdown[table]
    steps = rates.values(table)
    match category:
        case "valid":
            return limits.default
        case "between":
            if steps is None:
                return limits.min + 1
            low, high = next((a, b) for a, b in itertools.pairwise(steps) if b - a > 1)
            return (low + high) // 2
        case "above":
            return limits.max + 50
        case _:
            return max(1, limits.min - 1)


def tracks(encoder_id: str, stream: AudioStream) -> Iterator[AudioOutputTrack]:
    for mixdown in MIXDOWNS:
        bare = AudioOutputTrack(encoder=encoder_id, mixdown=mixdown, source_stream=1)
        table = planned_audio(bare, stream, "mkv", definitions=DEFS).bitrate_mixdown
        assert table is not None
        for category in BITRATES:
            bitrate = bitrate_for(category, encoder_id, table)
            quality = VBR_QUALITY if category == "vbr" else None
            for rate in SAMPLERATES:
                yield bare.model_copy(
                    update={"bitrate": bitrate, "quality": quality, "samplerate": rate}
                )


# --------------------------------------------------------------------------- C-8


def is_upmix(requested: Mixdown, channels: int) -> bool:
    """Decision 0019 item 3: more channels than a known source, or Dolby Pro Logic II of a
    source that is not surround."""
    wanted = DEFS.mixdowns[requested].channels
    return channels > 0 and (wanted > channels or (requested == "dpl2" and channels <= 2))


def layout_downmix(planned: PlannedAudio, stream: AudioStream) -> bool:
    """The builder keeps no mixdown but writes fewer channels than the source has (libopus
    refuses the source layout)."""
    written = layout_channels(planned.layout)
    return planned.mixdown is None and written is not None and len(written) < stream.channels


def check_notes(
    s: Any, track: AudioOutputTrack, planned: PlannedAudio, written: Written
) -> set[str]:
    """The notes exist exactly when C-7 writes another value than the track asks for, and
    name it; each fix keeps C-7's arguments and removes its note. Returns the note codes."""
    issues = issues_of(s)
    assert [i for i in issues if i.severity is Severity.ERROR] == []
    notes = {i.code: i for i in issues if i.code in SNAP_CODES}
    assert len(notes) == len([i for i in issues if i.code in SNAP_CODES])
    encoder = DEFS.audio_encoders[planned.encoder or ""]
    stream = s.source.audio[0]

    expected: set[str] = set()
    if track.bitrate is not None and written.bitrate != track.bitrate:
        expected.add("audio.bitrate_out_of_range")
        tail = (
            f"is written at {written.bitrate} kb/s."
            if written.bitrate is not None
            else f"is written without one ({track.bitrate} kb/s is not used)."
        )
        assert notes["audio.bitrate_out_of_range"].message.endswith(tail), notes
    if track.quality is not None and track.bitrate is None and written.quality is None:
        expected.add("audio.quality_unsupported")
        shown = f"at {written.bitrate} kb/s" if written.bitrate is not None else "without one"
        assert f"is written {shown}" in notes["audio.quality_unsupported"].message
    if track.samplerate is not None and written.samplerate != track.samplerate:
        expected.add("audio.samplerate_unsupported")
        assert notes["audio.samplerate_unsupported"].message.endswith(
            f"is written at {written.samplerate} Hz."
        )
    downmixed = layout_downmix(planned, stream)
    if planned.mixdown != track.mixdown or downmixed:
        code = (
            "audio.mixdown_upmix"
            if track.mixdown is not None and is_upmix(track.mixdown, stream.channels)
            else "audio.mixdown_unsupported"
        )
        expected.add(code)
        shown = (
            f"is written as {planned.layout}"
            if downmixed
            else "keeps the source layout"
            if planned.mixdown is None
            else f"is written as {DEFS.mixdowns[planned.mixdown].label}"
        )
        assert shown in notes[code].message, notes[code]
    assert set(notes) == expected, (encoder.id, track, notes)

    for issue in notes.values():
        for fix in issue.fixes:
            after = s.apply(fix)
            assert write(after).argv == written.argv, (issue.code, fix.label)
            assert not sc.found(issues_of(after), issue.code, issue.path), (issue.code, fix)
    return expected


# --------------------------------------------------------------------------- C-12


RULE_MIXDOWNS: dict[Mixdown | None, RuleMixdown] = {
    None: "keep",
    "mono": "mono",
    "stereo": "stereo",
    "dpl2": "dpl2",
    "5.1": "5.1",
}


def check_codec_rules(
    stream: AudioStream, track: AudioOutputTrack, seen: list[AudioOutputTrack]
) -> None:
    """C-12's track for the same request is what C-7 writes for the request, and is already
    snapped: no notes, and C-7 writes its values unchanged."""
    rule_mixdowns: list[RuleMixdown] = []
    if track.mixdown in RULE_MIXDOWNS:
        rule_mixdowns.append(RULE_MIXDOWNS[track.mixdown])
    if track.mixdown == "5.1":
        rule_mixdowns.append("up_to_5.1")
    for rule_mixdown in rule_mixdowns:
        rule = AudioCodecRule(
            codec=track.encoder or "aac",
            mixdown=rule_mixdown,
            max_bitrate=track.bitrate,
            if_fits="reencode",
            extras=AudioRuleExtras(samplerate=track.samplerate),
        )
        [out], _ = apply_codec_rules(
            stream, AudioDefaults(codec_rules=[rule]), "mkv", definitions=DEFS
        )
        assert out.action == "encode"
        encoder = DEFS.audio_encoders[out.encoder or ""]
        effective_rate = out.samplerate or encoder.snap_samplerate(None, stream.sample_rate)

        # The same request to C-7: the rule's mixdown, its max as the bitrate (none = the
        # default), its sample rate.
        request = AudioOutputTrack(
            encoder=out.encoder,
            mixdown=requested_mixdown(rule_mixdown, stream.channels, DEFS),
            bitrate=track.bitrate,
            samplerate=track.samplerate,
            source_stream=stream.index,
        )
        expected = planned_audio(request, stream, "mkv", definitions=DEFS)
        assert (out.mixdown, out.bitrate, effective_rate) == (
            expected.mixdown,
            expected.bitrate,
            expected.samplerate,
        ), (rule_mixdown, track)

        # C-12's own track is already snapped (each distinct track is checked once).
        if out in seen:
            continue
        seen.append(out)
        s = scenario(stream, out)
        planned = planned_audio(s.job.audio[0], stream, "mkv", definitions=DEFS)
        assert (planned.mixdown, planned.bitrate, planned.samplerate) == (
            out.mixdown,
            out.bitrate,
            effective_rate,
        )
        written = write(s)
        assert (written.bitrate, written.samplerate) == (out.bitrate, effective_rate)
        assert written.layout == planned.layout
        # A rule keeps the source layout or names a mixdown: it does not name the layout C-7
        # makes of a source layout libopus refuses (5.0 of 6.0, stereo of 2.1), so that note
        # stays on C-12's track (reported to the M2 lead).
        allowed = {"audio.mixdown_unsupported"} if layout_downmix(planned, stream) else set()
        left = [i for i in issues_of(s) if i.code in SNAP_CODES or i.severity is Severity.ERROR]
        assert {i.code for i in left} <= allowed, left


# --------------------------------------------------------------------------- the test


#: (layout, encoder) where C-12 disagrees with C-7, run as strict xfail until the owner
#: fixes it (then delete the entry). Empty: the libopus layout cases of the M2 review agree
#: since C-12 takes the bitrate table of the layout C-7 writes.
DISAGREE: dict[tuple[str, str], str] = {}


#: The source layouts with both source rates; the layouts libopus refuses (added for C-7's
#: ``PlannedAudio.layout``) with a known rate only, to keep the matrix fast.
SOURCES = [
    *((layout, rate) for layout in list(LAYOUTS)[:6] for rate in SOURCE_RATES),
    *((layout, "44.1kHz") for layout in list(LAYOUTS)[6:]),
]


@pytest.mark.parametrize("encoder_id", ENCODERS)
@pytest.mark.parametrize(("layout", "rate_id"), SOURCES)
def test_codec_rules_builder_and_validation_agree(
    layout: str, rate_id: str, encoder_id: str
) -> None:
    stream = source_stream(layout, SOURCE_RATES[rate_id])
    count = 0
    seen: list[AudioOutputTrack] = []
    notes: set[str] = set()
    codec_rules: list[AssertionError] = []
    for track in tracks(encoder_id, stream):
        s = scenario(stream, track)
        planned = planned_audio(s.job.audio[0], stream, "mkv", definitions=DEFS)
        written = write(s)
        check_builder(planned, written, stream)
        notes |= check_notes(s, s.job.audio[0], planned, written)
        try:
            check_codec_rules(stream, s.job.audio[0], seen)
        except AssertionError as exc:
            codec_rules.append(exc)
        count += 1
    assert count == len(MIXDOWNS) * len(BITRATES) * len(SAMPLERATES)
    reason = DISAGREE.get((layout, encoder_id))
    if reason is not None:
        assert codec_rules, f"C-12 now agrees for {layout} / {encoder_id}: remove DISAGREE"
        pytest.xfail(f"{reason} ({len(codec_rules)} tracks)")
    if codec_rules:
        raise codec_rules[0]
    # The matrix is not empty of notes: every encoder lacks 47 kHz and some bitrates, and
    # only MP3 has a VBR quality.
    assert {"audio.bitrate_out_of_range", "audio.samplerate_unsupported"} <= notes
    assert ("audio.quality_unsupported" in notes) is (encoder_id != "libmp3lame")
