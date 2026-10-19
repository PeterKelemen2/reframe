"""Deriving a template from a job and merging templates into a base."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

from reframe.batch import (
    SECTIONS,
    as_template,
    derive_selector,
    derive_template,
    merge_template,
    resolve_tracks,
)
from reframe.batch.derive import SECTION_FIELDS
from reframe.models import (
    AudioOutputSettings,
    AudioStream,
    ChapterSettings,
    CropRect,
    CropSettings,
    ExternalSubtitle,
    FilterConfig,
    JobNaming,
    JobTemplate,
    MediaSource,
    NamingOptions,
    SourceRef,
    SubtitleOutputSettings,
    SubtitleOutputTrack,
    TagSettings,
    TrackMetadata,
    TrackRole,
    TrackSelector,
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


def test_the_most_specific_selector() -> None:
    e01 = A.recorded(1, 1)
    selector = derive_selector(e01.audio[1], e01)
    assert selector == TrackSelector(
        kind="audio",
        languages=["en"],
        codecs=["dts"],
        profiles=["DTS-HD MA"],
        channels=6,
        roles=[TrackRole.MAIN],
        title_pattern="^English Dub$",
        nth=0,
    )
    signs = derive_selector(e01.subtitles[0], e01)
    assert signs is not None
    assert (signs.languages, signs.codecs, signs.profiles, signs.channels) == (
        ["en"],
        ["ass"],
        None,
        None,
    )
    assert set(signs.roles or []) == {TrackRole.FORCED, TrackRole.SIGNS}
    assert signs.title_pattern == "^Signs & Songs$"


def test_identical_tracks_get_nth() -> None:
    twin = AudioStream(index=1, codec="ac3", channels=2, language="eng")
    source = MediaSource(
        ref=SourceRef(path=Path("/m/a.mkv")),
        audio=[
            twin,
            twin.model_copy(update={"index": 2}),
            twin.model_copy(update={"index": 3, "language": None}),
        ],
    )
    second = derive_selector(source.audio[1], source)
    assert second is not None
    assert (second.nth, second.title_pattern) == (1, None)
    und = derive_selector(source.audio[2], source)
    assert und is not None
    assert (und.languages, und.nth) == (["und"], 0)
    other = MediaSource(ref=SourceRef(path=Path("/m/b.mkv")))
    assert derive_selector(twin, other) is None


def test_apply_audio_and_subtitles_to_the_group() -> None:
    e01 = A.recorded(1, 1)
    job = A.example_job(e01)
    base = A.builtin("h265-mkv-1080p")
    template = derive_template(job, e01, {"audio", "subtitles"}, base=base)
    assert type(template) is JobTemplate  # not the preset: no id, no name
    a1, a2 = template.audio_rules
    assert isinstance(a1.settings, AudioOutputSettings)
    assert (a1.settings.encoder, a1.settings.mixdown, a1.settings.bitrate) == (
        "libopus",
        "5.1",
        448,
    )
    assert (a2.settings.encoder, a2.settings.bitrate) == ("ac3", 640)  # type: ignore[union-attr]
    assert (a1.multiple, a1.required) == (False, True)
    assert a1.metadata.name_template == "Japanese 5.1"
    assert (a1.metadata.language, a1.metadata.default) == ("ja", True)
    assert a2.metadata.default is False
    s1, s2 = template.subtitle_rules
    assert isinstance(s1.settings, SubtitleOutputSettings)
    assert (s1.metadata.forced, s1.metadata.default) == (True, False)
    assert s1.metadata.name_template is None  # unchanged: each file keeps its own title
    assert (s2.metadata.default, s2.selector.title_pattern) == (True, "^Full$")
    assert template.video == base.video
    assert template.audio_defaults == base.audio_defaults
    tracks = resolve_tracks(template, e01).draft
    assert tracks.audio == job.audio
    assert tracks.subtitles == job.subtitles


def test_every_section() -> None:
    e01 = A.recorded(1, 1)
    job = A.example_job(e01)
    job.dimensions.crop = CropSettings(mode="auto", rect=CropRect(top=8, bottom=8))
    job.filters.root = {"deinterlace": FilterConfig(preset="bob")}
    job.video.rate_control = job.video.rate_control.model_copy(update={"value": 18.0})
    job.video.metadata = TrackMetadata(name="Main video", default=True)
    job.chapters = ChapterSettings(enabled=False, generate_every=5.0)
    job.tags = TagSettings(title="{name} {episode_code}")
    job.output.naming = JobNaming(
        template="{name} {episode_code}", name_source="file", field_overrides={"episode": "3"}
    )
    template = derive_template(job, e01, set(SECTIONS))
    assert template.output.container == job.output.container  # no base: the job's options
    assert template.crop_policy == "detect_per_file"
    assert template.dimensions.crop == CropSettings(mode="auto")  # this file's rect is not kept
    assert template.video.rate_control.value == 18.0  # type: ignore[union-attr]
    assert template.filters.root == {"deinterlace": FilterConfig(preset="bob")}
    assert template.video.metadata == TrackMetadata()  # per file
    assert (template.chapters.enabled, template.chapters.generate_every) == (False, 5.0)
    assert template.chapter_name_policy == "source"
    assert template.tags.title == "{name} {episode_code}"
    assert template.naming is not None
    assert (template.naming.movie_template, template.naming.episode_template) == (
        "{name} {episode_code}",
    ) * 2
    assert template.naming.name_source == "file"
    # A manual crop is the same for every file.
    job.dimensions.crop = CropSettings(mode="manual", rect=CropRect(left=4))
    assert derive_template(job, e01, {"dimensions"}).crop_policy == "fixed"


def test_chapter_names_and_naming_without_overrides() -> None:
    e01 = A.recorded(1, 1).model_copy(
        update={
            "chapters": [
                {"index": 0, "start": 0.0, "end": 1.0},
                {"index": 1, "start": 1.0, "end": 2.0},
            ]
        }
    )
    job = A.example_job(e01)
    job.chapters.names = ["Chapter 1", "Chapter 2"]
    base = JobTemplate(naming=NamingOptions(word_separator="space"))
    template = derive_template(job, e01, {"chapters", "naming"}, base=base)
    assert template.chapter_name_policy == "generated"
    assert template.naming == base.naming  # nothing of the job's own: the base's options
    job.chapters.names = ["Intro", "Part 1"]
    assert derive_template(job, e01, {"chapters"}).chapter_name_policy == "source"
    assert derive_template(job, e01, {"naming"}).naming is None


def test_external_subtitles_and_tracks_without_a_source_are_left_out() -> None:
    e01 = A.recorded(1, 1)
    job = A.example_job(e01)
    job.subtitles.append(SubtitleOutputTrack(source=ExternalSubtitle(path=Path("/m/x.srt"))))
    job.subtitles.append(SubtitleOutputTrack(source=99))
    job.audio.append(job.audio[0].model_copy(update={"source_stream": None}))
    job.audio.append(job.audio[0].model_copy(update={"source_stream": 99}))
    template = derive_template(job, e01, {"audio", "subtitles"})
    assert len(template.audio_rules) == 2
    assert len(template.subtitle_rules) == 2


def test_a_name_with_braces_is_a_literal() -> None:
    e01 = A.recorded(1, 1)
    job = A.example_job(e01)
    job.audio[0].metadata.name = "Japanese {5.1}"
    (rule, _) = derive_template(job, e01, {"audio"}).audio_rules
    assert rule.metadata.name_template == "Japanese {{5.1}}"
    assert (
        resolve_tracks(derive_template(job, e01, {"audio"}), e01).draft.audio[0].metadata.name
        == "Japanese {5.1}"
    )


def test_merge_takes_only_the_sections() -> None:
    preset = A.builtin("h265-mkv-1080p")
    incoming = A.example_template()
    merged = merge_template(preset, incoming, {"audio"})
    assert type(merged) is JobTemplate
    assert merged.audio_rules == incoming.audio_rules
    assert merged.subtitle_rules == []
    assert merged.naming == preset.naming
    everything = merge_template(preset, incoming, set(SECTIONS))
    for fields in SECTION_FIELDS.values():
        for field in fields:
            assert getattr(everything, field) == getattr(incoming, field)
    # Neither input changes, and the result does not share their lists.
    everything.audio_rules.clear()
    assert incoming.audio_rules
    assert as_template(preset).model_dump(exclude={"id"}) == JobTemplate.model_validate(
        preset.model_dump(exclude={"id", "name", "category", "description", "built_in"})
    ).model_dump(exclude={"id"})


def test_a_job_without_tracks_of_a_kind() -> None:
    """An empty rule list means "the template's defaults", so a job without audio gets one
    optional rule that takes no track."""
    e01 = A.recorded(1, 1)
    job = A.example_job(e01)
    job.audio = []
    template = derive_template(job, e01, {"audio"})
    (rule,) = template.audio_rules
    assert (rule.selector.languages, rule.required) == ([], False)
    result = resolve_tracks(template, e01)
    assert result.draft.audio == []
    assert [c.label for c in result.columns if c.kind == "audio"] == ["A1 no track"]
    (cell, *_subtitles) = result.matches
    assert (cell.status, cell.message) == ("skipped", "the rule takes no track")
    assert [i.code for i in result.draft.issues] == []
    assert all(not d.selected for d in result.draft.decisions)
