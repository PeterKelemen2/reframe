"""Deriving a group's template from one file's job.

Sections carry the template fields of the job, but not its per-file parts: a manual crop is
``fixed`` for every file and an automatic one is detected per file, and the video track's
metadata, external subtitle files, edited chapter names and a manual name stay per file.
Output options are in no section, so they stay the base's. Pure: no I/O.
"""

from __future__ import annotations

from collections.abc import Collection, Sequence
from typing import Literal

from reframe.batch.rules import literal_title
from reframe.batch.selectors import candidates, describe_kind, match_rules, title_regex
from reframe.models.batch import TemplateSection
from reframe.models.geometry import CropSettings
from reframe.models.job import (
    AudioOutputTrack,
    JobSettings,
    OutputOptions,
    SubtitleOutputTrack,
    TrackMetadata,
)
from reframe.models.media import AudioStream, MediaSource, SubtitleStream
from reframe.models.naming import NamingOptions
from reframe.models.preset import Preset
from reframe.models.template import (
    AudioOutputSettings,
    ChapterOptions,
    JobTemplate,
    OutputTrackRule,
    SubtitleOutputSettings,
    TrackMetadataTemplate,
    TrackSelector,
)

__all__ = [
    "as_template",
    "derive_selector",
    "derive_template",
]

_PRESET_ONLY = frozenset(Preset.model_fields) - frozenset(JobTemplate.model_fields)
_FLAGS = ("default", "forced", "commentary", "hearing_impaired", "visual_impaired", "original")


def as_template(template: JobTemplate) -> JobTemplate:
    """A copy of ``template`` as a plain :class:`~reframe.models.JobTemplate`: the preset-only
    fields are left out, unknown fields are kept."""
    data = template.model_dump(mode="json", exclude=set(_PRESET_ONLY))
    return JobTemplate.model_validate(data)


def derive_selector(
    stream: AudioStream | SubtitleStream, source: MediaSource
) -> TrackSelector | None:
    """The most specific selector of ``stream``. Its ``nth`` picks ``stream`` among the tracks
    that selector finds in ``source``. ``None`` when ``stream`` is not a track of ``source``."""
    kind: Literal["audio", "subtitle"] = "audio" if isinstance(stream, AudioStream) else "subtitle"
    tracks = describe_kind(source.audio if kind == "audio" else source.subtitles)
    track = next((t for t in tracks if t.descriptor.index == stream.index), None)
    if track is None:
        return None
    d = track.descriptor
    selector = TrackSelector(
        kind=kind,
        languages=[d.language or "und"],
        codecs=[d.codec] if d.codec else None,
        profiles=[d.profile] if kind == "audio" and d.profile else None,
        roles=list(d.roles),
        channels=d.channels if kind == "audio" and d.channels else None,
        title_pattern=literal_title(d.title) if d.title else None,
    )
    pattern = title_regex(selector.title_pattern)
    found = candidates(selector, tracks, title=pattern if not isinstance(pattern, str) else None)
    nth = next((n for n, t in enumerate(found) if t.descriptor.index == stream.index), 0)
    return selector.model_copy(update={"nth": nth})


def _escape(text: str) -> str:
    """A literal name as a name template: braces doubled (``<`` and ``>`` are template groups
    and cannot be written)."""
    return text.replace("{", "{{").replace("}", "}}")


def _metadata(meta: TrackMetadata, stream: AudioStream | SubtitleStream) -> TrackMetadataTemplate:
    """The job track's language and flags as they are; its name only when it is not the
    source title."""
    name = meta.name
    return TrackMetadataTemplate(
        language=meta.language,
        name_template=None if name is None or name == stream.title else _escape(name),
        **{flag: getattr(meta, flag) for flag in _FLAGS},
    )


def _audio_rules(tracks: Sequence[AudioOutputTrack], source: MediaSource) -> list[OutputTrackRule]:
    by_index = {s.index: s for s in source.audio}
    rules: list[OutputTrackRule] = []
    for track in tracks:
        stream = by_index.get(track.source_stream) if track.source_stream is not None else None
        selector = derive_selector(stream, source) if stream is not None else None
        if stream is None or selector is None:
            continue
        data = track.model_dump(mode="json", exclude={"source_stream", "metadata"})
        rules.append(
            OutputTrackRule(
                selector=selector,
                settings=AudioOutputSettings.model_validate({**data, "kind": "audio"}),
                metadata=_metadata(track.metadata, stream),
            )
        )
    return rules


def _subtitle_rules(
    tracks: Sequence[SubtitleOutputTrack], source: MediaSource
) -> list[OutputTrackRule]:
    by_index = {s.index: s for s in source.subtitles}
    rules: list[OutputTrackRule] = []
    for track in tracks:
        if not isinstance(track.source, int):
            continue  # an external subtitle file belongs to one source
        stream = by_index.get(track.source)
        selector = derive_selector(stream, source) if stream is not None else None
        if stream is None or selector is None:
            continue
        rules.append(
            OutputTrackRule(
                selector=selector,
                settings=SubtitleOutputSettings(
                    action=track.action,
                    convert_to=track.convert_to,
                    forced_only=track.forced_only,
                ),
                metadata=_metadata(track.metadata, stream),
            )
        )
    return rules


def _no_track(kind: Literal["audio", "subtitle"]) -> OutputTrackRule:
    """The rule of a job without tracks of ``kind``: it takes no track (``languages: []``
    matches none) and is optional. An empty rule list would mean the template's defaults, so
    a job with no tracks needs this rule."""
    settings = AudioOutputSettings() if kind == "audio" else SubtitleOutputSettings()
    return OutputTrackRule(
        selector=TrackSelector(kind=kind, languages=[]), settings=settings, required=False
    )


def _kept_required(
    rules: list[OutputTrackRule], base: Sequence[OutputTrackRule]
) -> list[OutputTrackRule]:
    """A derived rule that selects exactly as a rule of the base keeps that rule's
    ``required``: a group edit derives the whole section again from one file, and must not
    undo a rule made optional for the files that lack its track."""
    found: list[OutputTrackRule] = []
    for rule in rules:
        same = next((b for b in base if b.selector == rule.selector), None)
        found.append(rule if same is None else rule.model_copy(update={"required": same.required}))
    return found


def _with_absent(
    rules: list[OutputTrackRule],
    base: Sequence[OutputTrackRule],
    source: MediaSource,
    kind: Literal["audio", "subtitle"],
) -> list[OutputTrackRule]:
    """``rules`` with each base rule that takes no track in ``source``, unchanged, at its place
    in the base: a job says nothing about a track its file lacks, so the other files keep that
    rule. A ``languages: []`` rule only says a job had no tracks, so it is not kept."""
    tracks = describe_kind(source.audio if kind == "audio" else source.subtitles)
    picks, _ = match_rules(base, tracks, kind, labels=[""] * len(base), list_path="")
    found = list(rules)
    for pick in picks:
        rule = base[pick.rule]
        if not pick.tracks and rule.selector.languages != []:
            found.insert(pick.rule, rule)
    return found


def _naming(job: JobSettings, base: NamingOptions | None) -> NamingOptions | None:
    own = job.output.naming
    if own.template is None and own.name_source is None:
        return base.model_copy(deep=True) if base is not None else None
    options = base.model_copy(deep=True) if base is not None else NamingOptions()
    if own.template is not None:
        options.movie_template = own.template
        options.episode_template = own.template
    if own.name_source is not None:
        options.name_source = own.name_source
    return options


def derive_template(
    job: JobSettings,
    source: MediaSource,
    sections: Collection[TemplateSection],
    *,
    base: JobTemplate | None = None,
) -> JobTemplate:
    """The template of ``job``'s ``sections``, on top of ``base`` (default: a new template with
    the job's output options). ``source`` is the job's probed source: the track rules are
    derived from its tracks."""
    if base is None:
        base = JobTemplate(output=OutputOptions.model_validate(job.output.model_dump()))
    template = as_template(base)
    update: dict[str, object] = {}
    if "dimensions" in sections:
        dims = job.dimensions.model_copy(deep=True)
        if dims.crop.mode == "manual":
            update["crop_policy"] = "fixed"
        else:
            update["crop_policy"] = "detect_per_file"
            dims.crop = CropSettings(mode=dims.crop.mode)
        update["dimensions"] = dims
    if "filters" in sections:
        update["filters"] = job.filters.model_copy(deep=True)
    if "video" in sections:
        video = job.video.model_copy(deep=True)
        video.metadata = TrackMetadata()
        update["video"] = video
    if "audio" in sections:
        rules = _kept_required(_audio_rules(job.audio, source), template.audio_rules)
        rules = _with_absent(rules, template.audio_rules, source, "audio")
        update["audio_rules"] = rules or [_no_track("audio")]
    if "subtitles" in sections:
        rules = _kept_required(_subtitle_rules(job.subtitles, source), template.subtitle_rules)
        rules = _with_absent(rules, template.subtitle_rules, source, "subtitle")
        update["subtitle_rules"] = rules or [_no_track("subtitle")]
    if "chapters" in sections:
        update["chapters"] = ChapterOptions(
            enabled=job.chapters.enabled, generate_every=job.chapters.generate_every
        )
        # A preset holds no names: other names than these two cases are this file's own.
        names = job.chapters.names
        if names is None:
            update["chapter_name_policy"] = "source"
        elif names and all(name == f"Chapter {n}" for n, name in enumerate(names, start=1)):
            update["chapter_name_policy"] = "generated"
    if "tags" in sections:
        update["tags"] = job.tags.model_copy(deep=True)
    if "naming" in sections:
        update["naming"] = _naming(job, template.naming)
    return template.model_copy(update=update)
