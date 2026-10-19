"""Regression tests for the audio and subtitle track selection."""

from __future__ import annotations

import importlib.util
import sys
from collections.abc import Callable
from pathlib import Path
from types import ModuleType
from typing import Literal

import pytest

from reframe.batch import draft_tracks, effective_language, foreign_audio_search, select_tracks
from reframe.batch.explain import forced_evidence, subtitle_stage
from reframe.jsonpatch import apply_patch
from reframe.models import (
    AudioDefaults,
    AudioStream,
    JobTemplate,
    LanguageSettings,
    MediaSource,
    Preset,
    Severity,
    SubtitleDefaults,
    SubtitleStream,
    TrackSelection,
    ValidationIssue,
)
from reframe.presets import builtin_presets
from reframe.probe import ProbeError
from reframe.service import Reframe


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


T = _load("defaults_tracks")
audio: Callable[..., AudioStream] = T.audio
subtitle: Callable[..., SubtitleStream] = T.subtitle
source: Callable[..., MediaSource] = T.source

NO_LISTED = "defaults.no_listed_language"


def errors(issues: list[ValidationIssue]) -> list[str]:
    return [i.code for i in issues if i.severity is Severity.ERROR]


def builtin(name: str) -> Preset:
    return next(p for p in builtin_presets() if p.name == name)


def test_r1_1_a_listed_audio_description_is_not_a_listed_language_found() -> None:
    """A French main track and an English audio description; English is preferred."""
    media = source(
        [
            audio(1, "fre", "ac3", 6, 448, default=True),
            audio(2, "eng", "ac3", 2, 192, visual_impaired=True, title="Audio Description"),
        ]
    )
    preset = builtin("H.265 MKV 1080p")
    draft = draft_tracks(media, preset, languages=LanguageSettings(preferred_audio=["en"]))
    assert [t.source_stream for t in draft.audio] == [1]
    assert [(d.source_stream, d.selected, d.selection) for d in draft.decisions] == [
        (1, True, "No listed language found (English): the default-flagged track"),
        (2, False, "Audio description (disposition visual_impaired): dropped"),
    ]
    assert errors(draft.issues) == []


def test_r1_1_no_listed_language_counts_main_tracks_only() -> None:
    streams = [audio(1, "jpn"), audio(2, "hun", comment=True)]
    found = select_tracks(streams, TrackSelection(languages=["hu"], no_match="first_track"))
    assert found.no_listed_language
    assert [p.stream.index for p in found.selected] == [1]
    # A listed main track is found as before; a source of extras only has no main track.
    assert not select_tracks([audio(1, "hun")], TrackSelection(languages=["hu"])).no_listed_language
    only_extras = select_tracks([audio(1, "hun", comment=True)], TrackSelection(languages=["hu"]))
    assert not only_extras.no_listed_language


def test_r1_1_the_kept_commentary_comes_after_the_no_match_track() -> None:
    streams = [audio(1, "jpn", default=True), audio(2, "eng"), audio(3, "hun", comment=True)]
    selection = select_tracks(
        streams, TrackSelection(languages=["hu"], commentary="keep_after_main")
    )
    assert [(p.stream.index, p.group) for p in selection.selected] == [
        (1, "no_match"),
        (3, "extra"),
    ]


def test_r1_1_subtitles_use_the_same_rule() -> None:
    """The subtitle defaults use the same track selection as audio, so a listed-language
    commentary subtitle does not stop the no-match rule either."""
    streams = [subtitle(1, "eng", default=True), subtitle(2, "hun", comment=True)]
    selection = select_tracks(
        streams, TrackSelection(languages=["hu"], no_match="default_flagged"), kind="subtitle"
    )
    assert selection.no_listed_language
    assert [(p.stream.index, p.group) for p in selection.selected] == [(1, "no_match")]


@pytest.mark.parametrize("commentary", ["drop", "keep_after_main"])
def test_r1_1_take_none_with_only_a_listed_commentary_is_an_error(
    commentary: Literal["drop", "keep_after_main"],
) -> None:
    """Take none with only a listed commentary: no main track, so the no-match error."""
    defaults = AudioDefaults(
        selection=TrackSelection(languages=["hu"], no_match="none", commentary=commentary)
    )
    template = JobTemplate(audio_defaults=defaults)
    media = source([audio(1, "jpn", default=True), audio(2, "hun", "ac3", 2, 192, comment=True)])
    draft = draft_tracks(media, template)
    assert [t.source_stream for t in draft.audio] == (
        [2] if commentary == "keep_after_main" else []
    )
    (issue,) = [i for i in draft.issues if i.code == NO_LISTED]
    assert issue.message == (
        "This source has no main audio track in Hungarian (only commentary, description or "
        "music-only tracks), and the audio defaults take no track when no listed language is "
        "found."
    )
    for fix in issue.fixes:
        fixed = JobTemplate.model_validate(apply_patch(template.model_dump(mode="json"), fix.patch))
        again = draft_tracks(media, fixed)
        assert [t.source_stream for t in again.audio][:1] == [1]
        assert NO_LISTED not in [i.code for i in again.issues]


@pytest.mark.needs_ffmpeg
@pytest.mark.anyio
async def test_r1_1_and_r1_2_through_the_facade(
    fixture_media: Callable[[str], Path], tmp_path: Path
) -> None:
    """Drafts through the facade on the real fixtures (``Reframe.jobs.draft``)."""
    app = await Reframe.create(tmp_path / "config", tmp_path / "data", cache_dir=tmp_path / "c")
    try:
        base = app.presets.default()

        def preset(selection: TrackSelection) -> Preset:
            data = base.model_dump()
            data["audio_defaults"] = AudioDefaults(
                selection=selection, codec_rules=base.audio_defaults.codec_rules
            ).model_dump()
            return Preset.model_validate({**data, "id": "r1", "name": "R1", "built_in": False})

        # multitrack.mkv without its English main track: Japanese 5.1 (default) and
        # the English director's commentary; English listed.
        probed = await app.sources.probe(fixture_media("multitrack"))
        assert isinstance(probed, MediaSource)
        media = probed.model_copy(update={"audio": [probed.audio[0], probed.audio[2]]})
        assert [(a.index, a.language, a.title) for a in media.audio] == [
            (1, "jpn", "Japanese 5.1"),
            (3, "eng", "Director's Commentary"),
        ]
        draft = await app.jobs.draft(
            media, preset(TrackSelection(languages=["en"])), output=tmp_path / "r1-1.mkv"
        )
        assert not isinstance(draft, ProbeError)
        assert [a.source_stream for a in draft.job.audio] == [1]

        # German listed, take none, other languages: keep the first track.
        draft = await app.jobs.draft(
            fixture_media("dts-hd-ma"),
            preset(TrackSelection(languages=["de"], no_match="none", other_languages="keep_first")),
            output=tmp_path / "r1-2.mkv",
        )
        assert not isinstance(draft, ProbeError)
        assert [a.source_stream for a in draft.job.audio] == [1]
        assert NO_LISTED not in [i.code for i in draft.issues]
    finally:
        await app.close()


@pytest.mark.parametrize(
    ("other", "expected"), [("keep_first", [1]), ("keep_all", [1, 2]), ("drop", [])]
)
def test_r1_2_take_none_is_an_error_only_when_no_track_is_taken(
    other: Literal["drop", "keep_first", "keep_all"], expected: list[int]
) -> None:
    media = source([audio(1, "jpn", "ac3", 6, 448, default=True), audio(2, "fre", "ac3", 2, 192)])
    template = JobTemplate(
        audio_defaults=AudioDefaults(
            selection=TrackSelection(languages=["hu"], no_match="none", other_languages=other)
        )
    )
    draft = draft_tracks(media, template)
    assert [t.source_stream for t in draft.audio] == expected
    assert (NO_LISTED in errors(draft.issues)) == (not expected)


#: English main audio, a Hungarian commentary (audio and subtitle), English subtitles.
EXTRAS = source(
    [
        audio(1, "eng", "ac3", 6, 448, default=True),
        audio(2, "hun", "ac3", 2, 192, comment=True, title="Commentary"),
    ],
    [subtitle(3, "hun", comment=True, title="Commentary"), subtitle(4, "eng")],
)


def _extras_template(
    default_track: Literal["first_output", "first_in_first_language"],
) -> JobTemplate:
    return JobTemplate(
        audio_defaults=AudioDefaults(
            selection=TrackSelection(
                languages=["hu", "en"], commentary="keep_after_main", default_track=default_track
            )
        ),
        subtitle_defaults=SubtitleDefaults(
            selection=TrackSelection(
                languages=["hu"],
                commentary="keep_after_main",
                tracks_per_language="first",
                no_match="none",
            ),
            burn_in="foreign_audio",
        ),
    )


def test_r1_3_a_kept_commentary_is_never_the_first_language_default_audio() -> None:
    """``first_in_first_language`` skips the Hungarian commentary, which is not a main track."""
    draft = draft_tracks(EXTRAS, _extras_template("first_in_first_language"))
    assert [(t.source_stream, t.metadata.commentary, t.metadata.default) for t in draft.audio] == [
        (1, False, True),
        (2, True, False),
    ]
    assert draft.decisions[0].notes == [
        "The default audio track (the first track in the first language)"
    ]
    assert draft.decisions[1].notes == []


def test_r1_3_a_commentary_subtitle_is_never_burned_in_for_foreign_audio() -> None:
    """English audio, Hungarian viewer, burn-in ``foreign_audio``: the only Hungarian subtitle
    is a commentary, which is not "the Hungarian subtitles for the English audio"."""
    draft = draft_tracks(EXTRAS, _extras_template("first_output"))
    assert [(t.source, t.action) for t in draft.subtitles] == [(3, "copy")]
    row = next(d for d in draft.subtitle_decisions if d.source_stream == 3)
    assert not row.reason.startswith("Burn in")


def test_r1_3_foreign_audio_burn_in_takes_the_main_subtitle() -> None:
    media = EXTRAS.model_copy(update={"subtitles": [*EXTRAS.subtitles, subtitle(5, "hun")]})
    draft = draft_tracks(media, _extras_template("first_output"))
    assert [(t.source, t.action) for t in draft.subtitles] == [(5, "burn"), (3, "copy")]


def test_r1_3_a_commentary_subtitle_is_never_the_first_language_default() -> None:
    """Subtitle ``first_in_first_language``: the Hungarian commentary is skipped, and with no
    Hungarian main subtitle the default is the first copied track."""
    defaults = SubtitleDefaults(
        selection=TrackSelection(
            languages=["hu", "en"],
            commentary="keep_after_main",
            no_match="none",
            default_track="first_in_first_language",
        )
    )
    stage = subtitle_stage(defaults, EXTRAS)
    assert [(t.source, t.metadata.default) for t in stage.outputs] == [(4, True), (3, False)]


def test_r1_6_an_empty_subtitle_track_is_not_the_forced_track() -> None:
    """A subtitle track with 0 events (an empty track) is not "few events"."""
    full, empty = subtitle(2, "eng", events=900), subtitle(3, "eng", events=0)
    assert forced_evidence(empty, [full]) is None
    found = foreign_audio_search(
        [full, empty], audio_language="en", user_language="en", can_burn=False
    )
    assert found.searched
    assert found.track is None
    # A real low count is still found.
    few = subtitle(4, "eng", events=20)
    assert forced_evidence(few, [full, empty]) == (
        3,
        "20 events, 2 % of the 900 events of track #2",
    )


@pytest.mark.parametrize("broken", ["xx", "abcdefgh", "hu-Latn-ZZ9", "hu-XY-1"])
def test_an_invalid_language_ietf_falls_back_to_the_language(broken: str) -> None:
    """A broken ``LanguageIETF`` (right shape, not a language) falls back to ``language``."""
    track = audio(1, "hun", ietf=broken)
    assert effective_language(track) == "hu"
    assert effective_language(subtitle(2, "eng", ietf=broken)) == "en"
    draft = draft_tracks(
        source([track]),
        JobTemplate(audio_defaults=AudioDefaults(selection=TrackSelection(languages=["hu"]))),
    )
    assert [(t.source_stream, t.metadata.language) for t in draft.audio] == [(1, "hu")]
    assert draft.decisions[0].selection == "Hungarian: the first matching track"
    # A valid tag still wins, and a track with nothing valid keeps its raw tag.
    assert effective_language(audio(1, "hun", ietf="hu-HU")) == "hu-HU"
    assert effective_language(audio(1, "zzz", ietf=broken)) == broken
    assert effective_language(audio(1, "zzz")) == "zzz"
    assert effective_language(audio(1, None)) is None
