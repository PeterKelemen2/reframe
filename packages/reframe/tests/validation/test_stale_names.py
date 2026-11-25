"""A re-encoded track's name that names the source's codec or layout, and the name its fix
writes; a lossless track mixed down to a lossy codec."""

from __future__ import annotations

from typing import Any

import pytest

from reframe.models import ReplaceOp, Severity, SubtitleOutputTrack

from . import scenario as sc

AT = "audio[0].metadata.name"


def renamed(name: str | None, **track: Any) -> tuple[str, str] | None:
    """(message, new name) of the issue on the first audio track (AC-3 5.1 → AAC stereo)."""
    s = sc.base()
    s.job.audio[0].metadata.name = name
    for key, value in track.items():
        setattr(s.job.audio[0], key, value)
    issues = [i for i in sc.check(s) if i.code == "metadata.name_stale"]
    if not issues:
        return None
    (issue,) = issues
    assert issue.path == AT
    assert issue.severity is Severity.WARNING
    ((op,),) = [f.patch for f in issue.fixes]
    assert op.op == "add"
    assert op.path == "/audio/0/metadata/name"
    assert isinstance(op.value, str)
    return issue.message, op.value


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("DTS-HD MA 5.1", "AAC 2.0"),
        ("English AC-3 5.1", "English AAC 2.0"),
        ("TrueHD 7.1 Atmos", "AAC 2.0"),
        ("Dolby TrueHD Atmos 5.1", "AAC 2.0"),
        ("Dolby Digital 5.1", "AAC 2.0"),
        ("Dolby Digital Plus + Dolby Atmos", "AAC"),
        ("TrueHD Atmos 7.1", "AAC 2.0"),
        ("English (DTS-HD MA 5.1)", "English (AAC 2.0)"),
        ("English [Atmos]", "English [AAC]"),
        ("Hungarian 5.1 Surround", "Hungarian 2.0 Surround"),
        ("English Mono", "English Stereo"),
        ("English AAC 5.1", "English AAC 2.0"),
        ("English AAC-LC 5.1", "English AAC-LC 2.0"),
        ("Japanese 5.1 - DTS", "Japanese 2.0 - AAC"),
    ],
)
def test_the_fix_names_the_written_codec_and_layout(name: str, expected: str) -> None:
    found = renamed(name)
    assert found is not None
    assert found[1] == expected


@pytest.mark.parametrize(
    "name",
    [
        "English Stereo",
        "English 2.0 AAC",
        "Director's Commentary",
        "English DD5.1",  # not a word of its own
        "English 7.1.4",  # an Atmos bed, not a layout this rule reads
        "English DTS-HD",  # not a commercial name: DTS-HD MA or DTS-HD HRA
        "{lang_name} {channels} {source_codec}",  # a template says what it was asked to
        "",
    ],
)
def test_names_that_do_not_contradict_the_output(name: str) -> None:
    assert renamed(name) is None


def test_the_message_names_the_stale_words() -> None:
    found = renamed("DTS-HD MA 5.1")
    assert found is not None
    assert found[0] == (
        "Audio track 1 is written as AAC Stereo, but its name 'DTS-HD MA 5.1' says DTS-HD MA "
        "and 5.1."
    )


def test_a_track_without_a_name_is_checked_with_its_source_title() -> None:
    s = sc.base()
    s.source.audio[0].title = "DTS-HD MA 5.1"
    [issue] = [i for i in sc.check(s) if i.code == "metadata.name_stale"]
    after = s.apply(issue.fixes[0])
    assert after.job.audio[0].metadata.name == "AAC 2.0"


def test_the_layout_is_checked_against_the_written_layout() -> None:
    """Without a mixdown AAC keeps 5.1: only the codec word is stale."""
    found = renamed("DTS-HD MA 5.1", mixdown=None)
    assert found is not None
    assert found[1] == "AAC 5.1"


def test_a_copied_track_keeps_its_name() -> None:
    assert renamed("DTS-HD MA 5.1", action="passthru") is None


def test_eac3_atmos_encoded_to_eac3_loses_atmos() -> None:
    found = renamed("E-AC-3 Atmos 5.1", encoder="eac3", mixdown="5.1", bitrate=640)
    assert found is not None
    assert found[1] == "E-AC-3 5.1"
    assert renamed("Dolby Digital Plus 5.1", encoder="eac3", mixdown="5.1", bitrate=640) is None


def test_a_subtitle_converted_on_copy_is_checked() -> None:
    """MP4 converts a copied SRT track to mov_text."""
    s = sc.base()
    s.job.output.container = "mp4"
    s.job.output.path = s.job.output.path.with_suffix(".mp4") if s.job.output.path else None
    s.job.subtitles = [SubtitleOutputTrack(source=3, action="copy")]
    s.job.subtitles[0].metadata.name = "English SRT"
    [issue] = [i for i in sc.check(s) if i.code == "metadata.name_stale"]
    assert issue.path == "subtitles[0].metadata.name"
    assert issue.message == (
        "Subtitle track 1 is written as mov_text, but its name 'English SRT' says SRT."
    )
    assert s.apply(issue.fixes[0]).job.subtitles[0].metadata.name == "English mov_text"


def test_a_lossless_downmix_offers_passthru_and_the_source_layout() -> None:
    s = sc.base()
    stream = s.source.audio[0]
    stream.codec, stream.display_codec, stream.lossless = "truehd", "TrueHD", True
    [issue] = [i for i in sc.check(s) if i.code == "audio.lossless_downmix"]
    assert issue.message == (
        "The source of audio track 1 is lossless TrueHD 5.1; the track is written as lossy "
        "AAC Stereo."
    )
    assert [f.label for f in issue.fixes] == ["Pass TrueHD through", "Keep the source layout"]
    assert [op for f in issue.fixes for op in f.patch] == [
        ReplaceOp(path="/audio/0/action", value="passthru"),
        ReplaceOp(path="/audio/0/mixdown", value=None),
    ]


def test_a_lossless_track_kept_at_its_layout_has_no_note() -> None:
    s = sc.base()
    stream = s.source.audio[0]
    stream.codec, stream.display_codec, stream.lossless = "flac", "FLAC", True
    s.job.audio[0].mixdown = "5.1"
    s.job.audio[0].bitrate = 384
    assert not sc.found(s.validate(), "audio.lossless_downmix")


def test_a_lossy_source_mixed_down_has_no_note() -> None:
    assert not sc.found(sc.base().validate(), "audio.lossless_downmix")
