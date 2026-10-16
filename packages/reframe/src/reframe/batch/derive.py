"""Deriving a template from one file's job, and merging templates (04 §Three ways to edit,
§Deriving rules from a manual selection; 05 §C-12, M7).

*Apply to group…* and *Copy / paste sections* turn a job into a :class:`~reframe.models.
JobTemplate` (:func:`derive_template`) and merge its sections into the group template
(:func:`merge_template`). The sections and the template fields they hold:

==============  ===================================================================
Section         Template fields
==============  ===================================================================
``dimensions``  ``dimensions``, ``crop_policy`` (a manual crop is ``fixed`` for every
                file; an automatic one is detected per file, without this file's rect)
``filters``     ``filters``
``video``       ``video`` (the video track's metadata is per file)
``audio``       ``audio_rules`` (one rule per output track), ``audio_defaults``
``subtitles``   ``subtitle_rules`` (one rule per output track from a source track;
                external subtitle files are per file), ``subtitle_defaults``
``chapters``    ``chapters``, ``chapter_name_policy`` (generated names stay generated;
                edited names are per file)
``tags``        ``tags``
``naming``      ``naming`` (the job's own template and name source; a manual name and
                parsed-name corrections are per file)
==============  ===================================================================

Output options (container, web optimized, …) are in no section: they stay the base's
(decision 0040).

A track rule gets **the most specific selector** of its source track: its language, codec,
commercial name (audio), channels (audio), roles, ``^title$`` and the ``nth`` that picks it
among the tracks this selector finds in the file. The track's settings become fixed settings;
its language and six flags are written as they are; its name only when it is not the source
track's title (an unchanged name stays "from the source" in every file).

Pure: no I/O.
"""

from __future__ import annotations

from collections.abc import Collection, Sequence
from typing import Literal

from reframe.batch.rules import literal_title
from reframe.batch.selectors import candidates, describe_kind, title_regex
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
    "SECTIONS",
    "SECTION_FIELDS",
    "as_template",
    "derive_selector",
    "derive_template",
    "merge_template",
]

#: Every section, in the order of 04's *Apply to group…* dialog.
SECTIONS: tuple[TemplateSection, ...] = (
    "dimensions",
    "filters",
    "video",
    "audio",
    "subtitles",
    "chapters",
    "tags",
    "naming",
)
#: The template fields of each section.
SECTION_FIELDS: dict[TemplateSection, tuple[str, ...]] = {
    "dimensions": ("dimensions", "crop_policy"),
    "filters": ("filters",),
    "video": ("video",),
    "audio": ("audio_rules", "audio_defaults"),
    "subtitles": ("subtitle_rules", "subtitle_defaults"),
    "chapters": ("chapters", "chapter_name_policy"),
    "tags": ("tags",),
    "naming": ("naming",),
}
_PRESET_ONLY = frozenset(Preset.model_fields) - frozenset(JobTemplate.model_fields)
_FLAGS = ("default", "forced", "commentary", "hearing_impaired", "visual_impaired", "original")


def as_template(template: JobTemplate) -> JobTemplate:
    """A copy of ``template`` as a plain :class:`~reframe.models.JobTemplate` (a preset's id,
    name, category, description and built-in flag left out; unknown fields kept)."""
    data = template.model_dump(mode="json", exclude=set(_PRESET_ONLY))
    return JobTemplate.model_validate(data)


def merge_template(
    base: JobTemplate, incoming: JobTemplate, sections: Collection[TemplateSection]
) -> JobTemplate:
    """``base`` with the fields of ``incoming``'s ``sections`` (04: *Apply to group…*).
    The result is a plain template (see :func:`as_template`); neither input changes."""
    copied = incoming.model_copy(deep=True)
    update = {
        name: getattr(copied, name)
        for section in SECTIONS
        if section in sections
        for name in SECTION_FIELDS[section]
    }
    return as_template(base).model_copy(update=update)


# --------------------------------------------------------------------------- selectors


def derive_selector(
    stream: AudioStream | SubtitleStream, source: MediaSource
) -> TrackSelector | None:
    """The most specific selector of ``stream`` (04 §Deriving rules): language, codec,
    commercial name and channels (audio), roles, ``^title$``, and the ``nth`` that picks it
    among what that selector finds in ``source``. ``None`` when ``stream`` is not a track of
    ``source``."""
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
    matches none) and is optional. An empty rule list would mean "the template's defaults"
    (decision 0040)."""
    settings = AudioOutputSettings() if kind == "audio" else SubtitleOutputSettings()
    return OutputTrackRule(
        selector=TrackSelector(kind=kind, languages=[]), settings=settings, required=False
    )


# --------------------------------------------------------------------------- templates


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
    """The template of ``job``'s ``sections`` (04 §Deriving rules), on top of ``base``
    (default: a new template with the job's output options). ``source`` is the job's probed
    source: the track rules are derived from its tracks."""
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
        update["audio_rules"] = _audio_rules(job.audio, source) or [_no_track("audio")]
    if "subtitles" in sections:
        update["subtitle_rules"] = _subtitle_rules(job.subtitles, source) or [_no_track("subtitle")]
    if "chapters" in sections:
        update["chapters"] = ChapterOptions(
            enabled=job.chapters.enabled, generate_every=job.chapters.generate_every
        )
        generated = [f"Chapter {n}" for n in range(1, len(source.chapters) + 1)]
        names = job.chapters.names
        update["chapter_name_policy"] = (
            "generated" if names is not None and names == generated and generated else "source"
        )
    if "tags" in sections:
        update["tags"] = job.tags.model_copy(deep=True)
    if "naming" in sections:
        update["naming"] = _naming(job, template.naming)
    return template.model_copy(update=update)
