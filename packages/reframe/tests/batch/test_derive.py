"""Deriving a template from a job."""

from __future__ import annotations

from pathlib import Path
from typing import get_args

import pytest

from reframe.batch import as_template, derive_selector, derive_template, resolve, resolve_tracks
from reframe.models import (
    AudioOutputSettings,
    AudioStream,
    ChapterNamePolicy,
    ChapterSettings,
    CropRect,
    CropSettings,
    ExternalSubtitle,
    FilterConfig,
    JobNaming,
    JobTemplate,
    MediaSource,
    NamingOptions,
    OutputTrackRule,
    SourceRef,
    SubtitleOutputSettings,
    SubtitleOutputTrack,
    TagSettings,
    TemplateSection,
    TrackMetadata,
    TrackRole,
    TrackSelector,
)
from reframe.naming.track_names import track_names

from . import anime as A


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
    template = derive_template(job, e01, set(get_args(TemplateSection)))
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


@pytest.mark.parametrize(
    ("names", "own", "policy"),
    [
        (None, "generated", "source"),
        (["Chapter 1", "Chapter 2"], "source", "generated"),
        (["Chapter 1"], "source", "generated"),
        (["Intro", "Chapter 2"], "generated", "generated"),
        (["Intro", "Chapter 2"], "source", "source"),
        (["Chapter 2", "Chapter 1"], "generated", "generated"),
        ([], "source", "source"),
    ],
)
def test_per_file_chapter_names_keep_the_base_presets_policy(
    names: list[str] | None, own: ChapterNamePolicy, policy: ChapterNamePolicy
) -> None:
    """A preset holds a policy, never names: only "the source names" and "Chapter 1 … N" say
    one; other names are this file's."""
    e01 = A.recorded(1, 1)
    job = A.example_job(e01)
    job.chapters.names = names
    base = JobTemplate(chapter_name_policy=own)
    assert derive_template(job, e01, {"chapters"}, base=base).chapter_name_policy == policy


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


def test_a_track_name_template_stays_a_template() -> None:
    e01 = A.recorded(1, 1)
    job = A.example_job(e01)
    job.audio[0].metadata.name = "{lang_name} {channels}< ({title})>"
    (rule, _) = derive_template(job, e01, {"audio"}).audio_rules
    assert rule.metadata.name_template == "{lang_name} {channels}< ({title})>"
    expected = track_names(job, e01).audio[0]
    resolved = resolve_tracks(derive_template(job, e01, {"audio"}), e01).draft.audio[0]
    assert resolved.metadata.name == expected


def test_as_template_leaves_out_the_preset_only_fields() -> None:
    preset = A.builtin("h265-mkv-1080p")
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
    # Derived again on that template: still one rule, and a track added replaces it.
    assert derive_template(job, e01, {"audio"}, base=template).audio_rules == [rule]
    job.audio = A.example_job(e01).audio[:1]
    (again,) = derive_template(job, e01, {"audio"}, base=template).audio_rules
    assert again.selector.languages == ["ja"]


def test_a_rule_made_optional_stays_optional_when_its_section_is_derived_again() -> None:
    e01 = A.recorded(1, 1)
    job = A.example_job(e01)
    first = derive_template(job, e01, {"audio"}, base=A.builtin("h265-mkv-1080p"))
    optional = first.model_copy(
        update={
            "audio_rules": [
                first.audio_rules[0],
                first.audio_rules[1].model_copy(update={"required": False}),
            ]
        }
    )
    edited = job.model_copy(deep=True)
    edited.audio[0].bitrate = 384
    again = derive_template(edited, e01, {"audio"}, base=optional)
    assert [rule.required for rule in again.audio_rules] == [True, False]
    assert again.audio_rules[0].settings.bitrate == 384  # type: ignore[union-attr]
    other = job.model_copy(deep=True)
    other.audio = [other.audio[1]]  # the dub alone: its rule moved to the first place
    assert [
        r.required for r in derive_template(other, e01, {"audio"}, base=optional).audio_rules
    ] == [False]


def test_a_rule_that_takes_no_track_in_the_shown_file_is_kept() -> None:
    """E11 has no dub: a group edit shown on E11 must not drop the dub's rule for the season."""
    template = A.optional_dub_template()
    e01, e11 = A.recorded(1, 1), A.recorded(1, 11)
    job = resolve(template, e11).job
    assert job is not None
    job.audio[0].bitrate = 384
    derived = derive_template(job, e11, {"audio"}, base=template)
    a1, a2 = derived.audio_rules
    assert a1.settings.bitrate == 384  # type: ignore[union-attr]
    assert a2 == template.audio_rules[1]
    assert a2.required is False
    resolved = resolve(derived, e01).job
    assert resolved is not None
    assert [track.source_stream for track in resolved.audio] == [1, 2]


def test_a_subtitle_rule_that_takes_no_track_keeps_its_place() -> None:
    german = OutputTrackRule(
        selector=TrackSelector(kind="subtitle", languages=["de"]),
        settings=SubtitleOutputSettings(),
        required=False,
    )
    base = A.optional_dub_template()
    s1, s2 = base.subtitle_rules
    template = base.model_copy(update={"subtitle_rules": [s1, german, s2]})
    e11 = A.recorded(1, 11)
    job = resolve(template, e11).job
    assert job is not None
    job.subtitles[1].metadata.default = False
    derived = derive_template(job, e11, {"subtitles"}, base=template)
    assert len(derived.subtitle_rules) == 3
    assert derived.subtitle_rules[1] == german
    assert derived.subtitle_rules[2].metadata.default is False


def test_a_removed_track_removes_its_rule() -> None:
    """E01 has the dub and the user removed it: that removal is the edit."""
    template = A.optional_dub_template()
    e01 = A.recorded(1, 1)
    job = resolve(template, e01).job
    assert job is not None
    job.audio = job.audio[:1]
    (rule,) = derive_template(job, e01, {"audio"}, base=template).audio_rules
    assert rule == template.audio_rules[0]
