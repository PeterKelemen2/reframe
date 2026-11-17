"""Several output tracks of one kind marked default: one warning per kind with a fix that keeps
the first, naming the tracks that the command builder marks default. A template's track rules
get the same code at the rule that marks the tracks."""

from __future__ import annotations

import itertools
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from reframe.command import build_plan
from reframe.metadata import remux_job
from reframe.models import (
    AudioOutputSettings,
    AudioOutputTrack,
    EncodePlan,
    JobTemplate,
    MediaSource,
    OutputTrackRule,
    Severity,
    SubtitleOutputSettings,
    SubtitleOutputTrack,
    TrackMetadata,
    TrackMetadataTemplate,
    TrackSelector,
    ValidationIssue,
)

from . import scenario as sc

CODE = "metadata.several_defaults"
DEFAULT = TrackMetadata(default=True)


def mark(tracks: list[Any], *indexes: int) -> None:
    for index in indexes:
        tracks[index].metadata.default = True


def several(issues: list[ValidationIssue]) -> list[ValidationIssue]:
    return [i for i in issues if i.code == CODE]


def test_two_default_audio_tracks() -> None:
    s = sc.base()
    mark(s.job.audio, 0, 1)
    [issue] = several(sc.check(s))
    assert issue.severity is Severity.WARNING
    assert issue.path == "audio[1].metadata.default"
    assert issue.message == (
        "Audio tracks 1 and 2 are both marked default; usually only one audio track is."
    )
    [fix] = issue.fixes
    assert fix.label == "Keep only audio track 1 default"
    fixed = s.apply(fix)
    assert [t.metadata.default for t in fixed.job.audio] == [True, False]
    assert several(fixed.validate()) == []


def test_three_default_audio_tracks_keep_the_first() -> None:
    s = sc.base()
    s.job.audio.append(AudioOutputTrack(source_stream=1, encoder="ac3", mixdown="5.1"))
    mark(s.job.audio, 0, 1, 2)
    [issue] = several(sc.check(s))
    assert issue.message == (
        "Audio tracks 1, 2 and 3 are all marked default; usually only one audio track is."
    )
    fixed = s.apply(issue.fixes[0])
    assert [t.metadata.default for t in fixed.job.audio] == [True, False, False]


def test_the_issue_is_at_the_second_default_track() -> None:
    s = sc.base()
    s.job.audio.append(AudioOutputTrack(source_stream=1, encoder="ac3", mixdown="5.1"))
    mark(s.job.audio, 1, 2)
    [issue] = several(sc.check(s))
    assert issue.path == "audio[2].metadata.default"
    assert issue.message.startswith("Audio tracks 2 and 3 are both marked default")
    assert issue.fixes[0].label == "Keep only audio track 2 default"


def test_two_default_subtitle_tracks() -> None:
    s = sc.base()
    mark(s.job.subtitles, 0, 1)
    [issue] = several(sc.check(s))
    assert issue.path == "subtitles[1].metadata.default"
    assert issue.message == (
        "Subtitle tracks 1 and 2 are both marked default; usually only one subtitle track is."
    )
    assert issue.fixes[0].label == "Keep only subtitle track 1 default"


def test_one_warning_per_kind() -> None:
    s = sc.base()
    mark(s.job.audio, 0, 1)
    mark(s.job.subtitles, 0, 1)
    paths = [i.path for i in several(sc.check(s))]
    assert paths == ["audio[1].metadata.default", "subtitles[1].metadata.default"]


def test_one_default_track_of_each_kind_is_clean() -> None:
    s = sc.base()
    mark(s.job.audio, 0)
    mark(s.job.subtitles, 1)
    assert sc.check(s) == []


def test_a_burned_in_subtitle_is_not_an_output_track() -> None:
    s = sc.base()
    s.job.subtitles = [
        SubtitleOutputTrack(source=4, metadata=DEFAULT.model_copy()),
        SubtitleOutputTrack(source=3, action="burn", metadata=DEFAULT.model_copy()),
    ]
    assert several(sc.check(s)) == []


def test_the_tracks_are_named_by_their_job_number() -> None:
    s = sc.base()
    s.job.subtitles = [
        SubtitleOutputTrack(source=3, action="burn", metadata=DEFAULT.model_copy()),
        SubtitleOutputTrack(source=4, metadata=DEFAULT.model_copy()),
        SubtitleOutputTrack(source=4, metadata=DEFAULT.model_copy()),
    ]
    [issue] = several(sc.check(s))
    assert issue.path == "subtitles[2].metadata.default"
    assert issue.message.startswith("Subtitle tracks 2 and 3 are both marked default")


def plan_defaults(plan: EncodePlan, source: MediaSource) -> dict[str, list[int]]:
    """The 1-based output track numbers, per type (``a``, ``s``), that the file has marked
    default after the plan: the FFmpeg dispositions, then the header edits (an in-place edit
    starts from the source's flags)."""
    flags: dict[tuple[str, int], bool] = {}
    if plan.job_type == "metadata_edit":
        for kind, streams in (("a", source.audio), ("s", source.subtitles)):
            for number, stream in enumerate(streams, 1):
                flags[(kind, number)] = stream.disposition.default
    for step in plan.steps:
        if step.header_edit is not None:
            for edit in step.header_edit.tracks:
                if "default" in edit.flags:
                    flags[(edit.track_type[0], edit.number)] = edit.flags["default"]
            continue
        argv = [str(a) for a in step.argv]
        for arg, value in itertools.pairwise(argv):
            found = re.fullmatch(r"-disposition:([as]):(\d+)", arg)
            if found is not None:
                flags[(found[1], int(found[2]) + 1)] = "default" in value.split("+")
    marked: dict[str, list[int]] = {}
    for (kind, number), default in sorted(flags.items()):
        if default and kind in ("a", "s"):
            marked.setdefault(kind, []).append(number)
    return {kind: numbers for kind, numbers in marked.items() if len(numbers) > 1}


def named(issues: list[ValidationIssue], s: Any) -> dict[str, list[int]]:
    """The output track numbers that the warnings name (a message names job tracks; a
    burned-in subtitle has no output track)."""
    outputs = [i for i, t in enumerate(s.job.subtitles) if t.action != "burn"]
    found: dict[str, list[int]] = {}
    for issue in several(issues):
        numbers = [int(n) for n in re.findall(r"\d+", issue.message.split(" are ")[0])]
        if issue.path.startswith("audio"):
            found["a"] = numbers
        else:
            found["s"] = [outputs.index(n - 1) + 1 for n in numbers]
    return found


def two_of_each_kind(s: Any) -> None:
    mark(s.job.audio, 0, 1)
    mark(s.job.subtitles, 0, 1)


def one_of_each_kind(s: Any) -> None:
    mark(s.job.audio, 1)
    mark(s.job.subtitles, 0)


def mp4(s: Any) -> None:
    s.job.output.container = "mp4"
    s.job.output.path = Path("/out/Movie (2019).mp4")
    s.job.subtitles = []
    mark(s.job.audio, 0, 1)


def burn_and_copies(s: Any) -> None:
    s.job.subtitles = [
        SubtitleOutputTrack(source=4, metadata=DEFAULT.model_copy()),
        SubtitleOutputTrack(source=3, action="burn", metadata=DEFAULT.model_copy()),
        SubtitleOutputTrack(source=4, metadata=DEFAULT.model_copy()),
    ]


def in_place(s: Any) -> None:
    s.job = remux_job(s.job, s.source, edit_in_place=True)
    mark(s.job.audio, 0, 1)
    mark(s.job.subtitles, 1)


AGREEMENT: dict[str, Callable[[Any], None]] = {
    "two of each kind": two_of_each_kind,
    "one of each kind": one_of_each_kind,
    "mp4": mp4,
    "a burned-in subtitle between two copies": burn_and_copies,
    "in-place edit": in_place,
}


@pytest.mark.parametrize("change", AGREEMENT.values(), ids=AGREEMENT.keys())
def test_validation_names_the_tracks_the_plan_marks_default(change: Callable[[Any], None]) -> None:
    s = sc.base()
    change(s)
    plan = build_plan(s.job, s.source, s.caps, s.tools, definitions=s.definitions)
    assert named(s.validate(), s) == plan_defaults(plan, s.source)


def test_the_agreement_cases_cover_both_answers() -> None:
    results = []
    for change in AGREEMENT.values():
        s = sc.base()
        change(s)
        results.append(bool(several(s.validate())))
    assert True in results
    assert False in results


def audio_rule(default: bool | None, *, multiple: bool = False) -> OutputTrackRule:
    return OutputTrackRule(
        selector=TrackSelector(kind="audio", languages=["en"]),
        multiple=multiple,
        settings=AudioOutputSettings(encoder="aac", mixdown="stereo", bitrate=160),
        metadata=TrackMetadataTemplate(default=default),
    )


def subtitle_rule(default: bool | None) -> OutputTrackRule:
    return OutputTrackRule(
        selector=TrackSelector(kind="subtitle", languages=["en"]),
        settings=SubtitleOutputSettings(),
        metadata=TrackMetadataTemplate(default=default),
    )


def test_a_template_rule_that_marks_every_track_default() -> None:
    template = JobTemplate(audio_rules=[audio_rule(True, multiple=True)])
    issues = several(sc.check_template(sc.TemplateScenario(template)))
    assert [(i.path, i.severity) for i in issues] == [
        ("audio_rules[0].metadata.default", Severity.WARNING)
    ]


def test_two_template_rules_that_mark_their_tracks_default() -> None:
    template = JobTemplate(subtitle_rules=[subtitle_rule(True), subtitle_rule(True)])
    issues = several(sc.check_template(sc.TemplateScenario(template)))
    assert [i.path for i in issues] == ["subtitle_rules[1].metadata.default"]


def test_template_rules_with_one_default_per_kind_are_clean() -> None:
    template = JobTemplate(
        audio_rules=[audio_rule(True), audio_rule(None, multiple=True)],
        subtitle_rules=[subtitle_rule(False), subtitle_rule(True)],
    )
    assert several(sc.TemplateScenario(template).validate()) == []
