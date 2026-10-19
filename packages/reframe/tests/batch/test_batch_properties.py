"""Property tests of the batch engine: derived templates, overrides and fingerprint levels.

A template derived from a file resolves to that file's tracks, in order when tracks are twins.
The fingerprint levels nest: equal at strict implies equal at standard, and equal at standard
implies equal at loose.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from pydantic import TypeAdapter

from reframe.batch import derive_template, fingerprint, resolve, resolve_tracks
from reframe.batch.selectors import candidates, describe_kind, title_regex
from reframe.definitions import load_definitions
from reframe.models import (
    AudioOutputTrack,
    AudioStream,
    BitrateInfo,
    BitrateSource,
    Disposition,
    JobSettings,
    JsonPatchOp,
    MediaSource,
    SourceRef,
    SubtitleOutputTrack,
    SubtitleStream,
    TrackMetadata,
    VideoStream,
)


def _load(name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        f"_reframe_batch_{name}", Path(__file__).with_name(f"{name}.py")
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


A = _load("anime")
DEFS = load_definitions()
OPS = TypeAdapter(list[JsonPatchOp])

LANGUAGES = [None, "und", "eng", "jpn", "hun"]
AUDIO = [("ac3", None), ("eac3", None), ("dts", "DTS-HD MA"), ("dts", None), ("truehd", None)]
SUBTITLES = ["ass", "subrip", "hdmv_pgs_subtitle"]
TITLES = [None, "Main", "Commentary", "Signs & Songs", "Full", "English (2.0)", "a.b*c"]


@st.composite
def audio_streams(draw: st.DrawFn, index: int) -> AudioStream:
    codec, profile = draw(st.sampled_from(AUDIO))
    known = draw(st.booleans())
    return AudioStream(
        index=index,
        codec=codec,
        profile=profile,
        display_codec=profile,
        channels=draw(st.sampled_from([1, 2, 6, 8])),
        language=draw(st.sampled_from(LANGUAGES)),
        title=draw(st.sampled_from(TITLES)),
        bitrate=BitrateInfo(
            value=draw(st.sampled_from([192_000, 640_000])), source=BitrateSource.STREAM
        )
        if known
        else BitrateInfo(),
        disposition=Disposition(default=draw(st.booleans()), comment=draw(st.booleans())),
    )


@st.composite
def subtitle_streams(draw: st.DrawFn, index: int) -> SubtitleStream:
    codec = draw(st.sampled_from(SUBTITLES))
    return SubtitleStream(
        index=index,
        codec=codec,
        subtitle_kind="bitmap" if codec == "hdmv_pgs_subtitle" else "text",
        language=draw(st.sampled_from(LANGUAGES)),
        title=draw(st.sampled_from(TITLES)),
        disposition=Disposition(
            default=draw(st.booleans()),
            forced=draw(st.booleans()),
            hearing_impaired=draw(st.booleans()),
        ),
    )


@st.composite
def sources(draw: st.DrawFn) -> MediaSource:
    audio_count = draw(st.integers(0, 4))
    subtitle_count = draw(st.integers(0, 3))
    audio = [draw(audio_streams(1 + n)) for n in range(audio_count)]
    subtitles = [draw(subtitle_streams(1 + audio_count + n)) for n in range(subtitle_count)]
    size = draw(st.sampled_from([(320, 180), (1920, 1080), (1920, 800)]))
    video = VideoStream(index=0, codec="h264", width=size[0], height=size[1])
    return MediaSource(
        ref=SourceRef(path=Path("/m/Show.S01E01.mkv")),
        video=[video],
        audio=audio,
        subtitles=subtitles,
    )


@st.composite
def jobs(draw: st.DrawFn, source: MediaSource) -> JobSettings:
    """A job with output tracks picked by hand from ``source`` (any order, repeats too)."""
    audio = []
    for stream in draw(st.lists(st.sampled_from(source.audio), max_size=4)) if source.audio else []:
        audio.append(
            AudioOutputTrack(
                action=draw(st.sampled_from(["encode", "passthru"])),
                encoder=draw(st.sampled_from(["aac", "libopus", "ac3"])),
                mixdown=draw(st.sampled_from([None, "stereo", "5.1"])),
                bitrate=draw(st.sampled_from([None, 160, 448])),
                source_stream=stream.index,
                metadata=TrackMetadata(
                    language=draw(st.sampled_from([None, "en", "ja"])),
                    name=draw(st.sampled_from([None, stream.title, "Custom {x}"])),
                    default=draw(st.booleans()),
                ),
            )
        )
    subtitles = [
        SubtitleOutputTrack(
            source=stream.index,
            action=draw(st.sampled_from(["copy", "burn"])),
            metadata=TrackMetadata(forced=draw(st.booleans())),
        )
        for stream in (
            draw(st.lists(st.sampled_from(source.subtitles), max_size=3))
            if source.subtitles
            else []
        )
    ]
    return JobSettings(source=source.ref, audio=audio, subtitles=subtitles)


def _twins(source: MediaSource, template: Any, kind: str) -> set[int]:
    """Rules whose full selector finds more than one track of ``source``."""
    tracks = describe_kind(source.audio if kind == "audio" else source.subtitles)
    rules = template.audio_rules if kind == "audio" else template.subtitle_rules
    found = set()
    for n, rule in enumerate(rules):
        pattern = title_regex(rule.selector.title_pattern)
        assert not isinstance(pattern, str)
        if len(candidates(rule.selector, tracks, title=pattern)) > 1:
            found.add(n)
    return found


@settings(max_examples=150, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(data=st.data())
def test_a_derived_template_resolves_to_the_same_tracks_on_its_file(data: st.DataObject) -> None:
    source = data.draw(sources())
    job = data.draw(jobs(source))
    template = derive_template(job, source, {"audio", "subtitles"})
    result = resolve_tracks(template, source, definitions=DEFS)
    assert [t.source_stream for t in result.draft.audio] == [t.source_stream for t in job.audio]
    assert [t.source for t in result.draft.subtitles] == [t.source for t in job.subtitles]
    for track, wanted in zip(result.draft.audio, job.audio, strict=True):
        exclude = {"source_stream", "metadata"}
        assert track.model_dump(exclude=exclude) == wanted.model_dump(exclude=exclude)
    assert [t.action for t in result.draft.subtitles] == [t.action for t in job.subtitles]
    twins = {
        "audio": _twins(source, template, "audio"),
        "subtitle": _twins(source, template, "subtitle"),
    }
    for match in result.matches:
        assert match.relaxed == []
        rules = template.audio_rules if match.kind == "audio" else template.subtitle_rules
        if rules[match.rule].selector.languages == []:
            # A job without tracks of a kind: a rule that takes none (not "the defaults").
            assert (match.status, match.streams) == ("skipped", [])
        elif match.rule in twins[match.kind]:
            assert match.status in ("exact", "ambiguous")
        else:
            assert match.status == "exact"


CHANGES = {
    "video quality": ("/video/rate_control/value", 19.0),
    "A1 bit rate": ("/audio_rules/0/settings/bitrate", 384),
    "A2 bit rate": ("/audio_rules/1/settings/bitrate", 448),
    "S1 forced": ("/subtitle_rules/0/metadata/forced", False),
    "video preset": ("/video/preset", "veryslow"),
    "chapters": ("/chapters/enabled", False),
}


def _job_value(job: JobSettings, field: str) -> object:
    match field:
        case "video quality":
            return job.video.rate_control.value  # type: ignore[union-attr]
        case "A1 bit rate":
            return job.audio[0].bitrate
        case "A2 bit rate":
            return job.audio[1].bitrate
        case "S1 forced":
            return job.subtitles[0].metadata.forced
        case "video preset":
            return job.video.preset
        case _:
            return job.chapters.enabled


@settings(max_examples=60, deadline=None)
@given(
    fields=st.lists(st.sampled_from(sorted(CHANGES)), min_size=2, max_size=2, unique=True),
    episode=st.sampled_from([1, 3, 5, 12]),
)
def test_an_override_survives_a_change_of_the_template(fields: list[str], episode: int) -> None:
    overridden, changed = fields
    source = A.recorded(1, episode)
    template = A.example_template()
    path, value = CHANGES[overridden]
    override = OPS.validate_python([{"op": "replace", "path": path, "value": value}])
    change_path, change_value = CHANGES[changed]
    data = template.model_dump(mode="json")
    tokens = change_path.strip("/").split("/")
    target: Any = data
    for token in tokens[:-1]:
        target = target[int(token)] if token.isdigit() else target[token]
    target[tokens[-1]] = change_value
    new_template = type(template).model_validate(data)
    before = resolve(template, source, override)
    after = resolve(new_template, source, override)
    assert before.job is not None
    assert after.job is not None
    assert _job_value(after.job, overridden) == value
    assert _job_value(after.job, changed) == change_value
    assert [i.code for i in after.issues if i.code.startswith("batch.override")] == []


@st.composite
def mutations(draw: st.DrawFn, source: MediaSource) -> MediaSource:
    """A copy of ``source`` with one small change (or none)."""
    kind = draw(
        st.sampled_from(["none", "title", "flag", "bitrate", "channels", "codec", "swap", "size"])
    )
    audio = [a.model_copy() for a in source.audio]
    video = [v.model_copy() for v in source.video]
    if audio and kind != "none":
        n = draw(st.integers(0, len(audio) - 1))
        match kind:
            case "title":
                audio[n] = audio[n].model_copy(update={"title": "Other"})
            case "flag":
                audio[n] = audio[n].model_copy(
                    update={"disposition": Disposition(default=True, original=True)}
                )
            case "bitrate":
                audio[n] = audio[n].model_copy(
                    update={"bitrate": BitrateInfo(value=999_000, source=BitrateSource.STREAM)}
                )
            case "channels":
                audio[n] = audio[n].model_copy(update={"channels": 3})
            case "codec":
                swap = {"ac3": "eac3", "eac3": "ac3", "dts": "dts", "truehd": "mlp"}
                audio[n] = audio[n].model_copy(update={"codec": swap[audio[n].codec or "ac3"]})
            case "swap" if len(audio) > 1:
                first, second = audio[0], audio[1]
                audio[0] = second.model_copy(update={"index": first.index})
                audio[1] = first.model_copy(update={"index": second.index})
            case "size":
                video = [video[0].model_copy(update={"height": 804})]
            case _:
                pass
    return source.model_copy(update={"audio": audio, "video": video})


@settings(max_examples=300, deadline=None)
@given(data=st.data())
def test_the_fingerprint_levels_nest(data: st.DataObject) -> None:
    a = data.draw(sources())
    b = data.draw(mutations(a))
    strict = fingerprint(a, "strict").digest == fingerprint(b, "strict").digest
    standard = fingerprint(a, "standard").digest == fingerprint(b, "standard").digest
    loose = fingerprint(a, "loose").digest == fingerprint(b, "loose").digest
    assert not strict or standard
    assert not standard or loose
