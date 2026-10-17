"""C-12 M7: the fixes of the core-complete review (2026-10-16; decision 0040 "Follow-up").

- R2-2: roles that C-3 infers from per-episode statistics (heuristic evidence) neither split a
  season nor break a derived rule: fingerprints and selectors use flag and title roles only.
- R2-3: a per-file override that changes the structure of the rule lists is
  ``batch.override_invalid`` (its template part is not applied), so the row's cells stay in
  the template's columns.
- R2-4: a changed track counts once at every level (the loose level too).
- R2-6: the matrix names the season when a group spans seasons, and a file name when two rows
  would have one label.
- The suspected points: a hand pick counts as an exact match for relaxation; a source track
  that two rules take is the first of its language for both; a rule with settings of the
  other kind is not "✓ exact" in the matrix.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

from pydantic import TypeAdapter

from reframe.batch import (
    derive_template,
    group_sources,
    grouping,
    matrix_columns,
    resolve,
    resolve_group,
)
from reframe.batch.descriptors import MATCH_LEVELS, fingerprint, stream_roles
from reframe.batch.grouping import compare
from reframe.batch.report import matrix_lines
from reframe.batch.rules import resolve_tracks
from reframe.definitions import load_definitions
from reframe.jobs import draft_from_preset
from reframe.models import (
    AudioCodecRule,
    AudioCodecRules,
    AudioOutputSettings,
    AudioRuleExtras,
    AudioStream,
    BatchResolution,
    JobTemplate,
    JsonPatchOp,
    MediaSource,
    OutputTrackRule,
    SourceFingerprint,
    SubtitleOutputSettings,
    SubtitleStream,
    TrackRole,
    TrackSelector,
)
from reframe.probe import parse_ffprobe


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
OPS = TypeAdapter(list[JsonPatchOp])
DEFS = load_definitions()


# --------------------------------------------------------------------------- R2-2


def _episode_with_counts(episode: int, signs_events: int, full_events: int) -> MediaSource:
    """An episode of the 04 example whose first subtitle is an untitled, unflagged track with
    ``NUMBER_OF_FRAMES`` statistics (a signs track as mkvmerge writes it): C-3's heuristic
    calls it forced when it has at most 25 % of the full track's events."""
    rel = f"{A.media.anime_folder(1)}/{A.media.anime_file_name(1, episode)}"
    data = json.loads((A.PROBES / f"{rel}.json").read_text(encoding="utf-8"))
    signs, full = [s for s in data["streams"] if s["codec_type"] == "subtitle"]
    signs["disposition"]["forced"] = 0
    signs["tags"].pop("title", None)
    signs["tags"]["NUMBER_OF_FRAMES"] = str(signs_events)
    full["tags"]["NUMBER_OF_FRAMES"] = str(full_events)
    return parse_ffprobe(data, A.path(1, episode), fingerprint=SourceFingerprint(size=0, mtime=0.0))


def test_heuristic_roles_neither_split_a_season_nor_break_a_derived_rule() -> None:
    """R2-2: the signs track has 22 % of the full track's events in E01 and 27 % in E02 (the
    heuristic's limit is 25 %): one release, one layout, one group, and the rule derived from
    E01 matches E02 exactly."""
    e01 = _episode_with_counts(1, 90, 400)
    e02 = _episode_with_counts(2, 110, 400)
    signs01, signs02 = e01.subtitles[0], e02.subtitles[0]
    assert [(r.role, r.evidence.value) for r in signs01.roles] == [(TrackRole.FORCED, "heuristic")]
    assert [(r.role, r.evidence.value) for r in signs02.roles] == [(TrackRole.MAIN, "heuristic")]
    for level in MATCH_LEVELS:
        (group,) = group_sources([e01, e02], level)
        assert [m.match for m in group.members] == ["exact", "exact"], level
    base = A.builtin("h265-mkv-1080p")
    job, _tracks, _notes = draft_from_preset(e01, base)
    template = derive_template(job, e01, {"subtitles"}, base=base)
    assert [r.selector.roles for r in template.subtitle_rules] == [
        [TrackRole.MAIN],
        [TrackRole.MAIN],
    ]
    # The untitled signs track: its rule can only go by order (2 candidates, 0040 §2), in
    # E01 as in E02; never "✗ none".
    for source in (e01, e02):
        row = resolve(template, source)
        assert [(m.status, m.streams) for m in row.matches if m.kind == "subtitle"] == [
            ("ambiguous", [3]),
            ("exact", [4]),
        ]
        assert row.status == "warning"


def test_descriptor_roles_have_flag_or_title_evidence() -> None:
    """R2-2: a heuristic role (C-3's untitled low-bitrate 2.0 commentary, a forced track by its
    event count) is not a descriptor role; flag and title roles are."""
    heuristic = AudioStream.model_validate(
        {
            "index": 2,
            "codec": "ac3",
            "channels": 2,
            "roles": [{"role": "commentary", "evidence": "heuristic"}],
        }
    )
    assert stream_roles(heuristic) == [TrackRole.MAIN]
    flagged = AudioStream.model_validate(
        {
            **heuristic.model_dump(mode="json"),
            "roles": [{"role": "commentary", "evidence": "flag"}],
        }
    )
    assert stream_roles(flagged) == [TrackRole.COMMENTARY]
    forced = SubtitleStream.model_validate(
        {
            "index": 3,
            "codec": "ass",
            "roles": [
                {"role": "signs", "evidence": "title"},
                {"role": "forced", "evidence": "heuristic"},
            ],
        }
    )
    assert stream_roles(forced) == [TrackRole.SIGNS]


# --------------------------------------------------------------------------- R2-3


def test_an_override_that_changes_the_rule_lists_is_invalid() -> None:
    """R2-3: removing, adding or moving a rule for one file would put the file's cells under
    other rules' columns: such an override is ``batch.override_invalid``, and its template
    part is not applied (the cells stay in the template's columns)."""
    template = A.example_template()
    sources = A.season(1)[:3]
    (group,) = group_sources(sources, "standard")
    e02 = str(A.path(1, 2))
    plain = resolve(template, sources[1])
    signs = template.subtitle_rules[0].model_dump(mode="json")
    for ops in (
        [{"op": "remove", "path": "/audio_rules/0"}],
        [{"op": "add", "path": "/subtitle_rules/-", "value": signs}],
        [{"op": "move", "from": "/audio_rules/1", "path": "/audio_rules/0"}],
        [{"op": "replace", "path": "/audio_rules", "value": []}],
        [
            {"op": "replace", "path": "/video/preset", "value": "slow"},
            {"op": "copy", "from": "/audio_rules/0", "path": "/audio_rules/1"},
        ],
    ):
        patch = OPS.validate_python(ops)
        rows = resolve_group(group, template, sources, {e02: patch})
        row = rows[1]
        assert "batch.override_invalid" in [i.code for i in row.issues], ops
        assert row.job is not None
        assert plain.job is not None
        assert row.job.audio == plain.job.audio, ops
        assert row.job.video.preset == plain.job.video.preset  # the whole template part
        assert row.matches == plain.matches
        resolution = BatchResolution(group=group, columns=matrix_columns(template), rows=rows)
        lines = matrix_lines(resolution)
        a1 = lines[0].index("A1")
        assert lines[3][a1:].startswith("✓ #1"), lines[3]
    # A change inside a rule is fine: it keeps its column.
    bitrate = OPS.validate_python(
        [{"op": "replace", "path": "/audio_rules/1/settings/bitrate", "value": 448}]
    )
    row = resolve_group(group, template, sources, {e02: bitrate})[1]
    assert row.job is not None
    assert [a.bitrate for a in row.job.audio] == [448, 448]
    assert all(i.severity.value != "error" for i in row.issues)


# --------------------------------------------------------------------------- R2-4


def test_a_changed_track_counts_once_at_every_level() -> None:
    """R2-4 (0040 §3: an extra, a missing or a changed track each count 1): an episode whose
    dub and full subtitles are German instead of English has 2 changed tracks at every
    level, so the loose level keeps it as a near member as the standard level does."""
    e01, e03 = A.recorded(1, 1), A.recorded(1, 3)
    e02 = A.recorded(1, 2)
    audio = [e02.audio[0], e02.audio[1].model_copy(update={"language": "ger"})]
    subs = [e02.subtitles[0], e02.subtitles[1].model_copy(update={"language": "ger"})]
    changed = e02.model_copy(update={"audio": audio, "subtitles": subs})
    counts = {}
    for level in MATCH_LEVELS:
        found = compare(fingerprint(e01, level), fingerprint(changed, level))
        counts[level] = found.count
        assert found.lines == [
            '2 tracks differ (eng DTS-HD MA 5.1 "English Dub" → ger DTS-HD MA 5.1 "English Dub"; '
            'eng ASS "Full" → ger ASS "Full")'
        ], level
    assert counts == {"strict": 2, "standard": 2, "loose": 2}
    for level in MATCH_LEVELS[1:]:
        (group,) = group_sources([e01, e03, changed], level)
        assert [m.match for m in group.members] == ["exact", "near", "exact"], level


def test_loose_pairs_changed_tracks_by_kind() -> None:
    """An extra audio track and a missing subtitle are not one changed track."""
    e01 = A.recorded(1, 1)
    other = e01.model_copy(
        update={
            "audio": [*e01.audio, e01.audio[1].model_copy(update={"index": 9, "language": "ger"})],
            "subtitles": e01.subtitles[:1],
        }
    )
    found = compare(fingerprint(e01, "loose"), fingerprint(other, "loose"))
    assert found.count == 2
    assert found.lines == [
        '1 extra track (ger DTS-HD MA 5.1 "English Dub")',
        '1 track missing (eng ASS "Full")',
    ]


# --------------------------------------------------------------------------- R2-6


def test_matrix_labels_name_the_season_when_a_group_spans_seasons() -> None:
    """R2-6: ``reframe batch <S01> <S02>`` makes one group (one layout); its rows are
    ``S01E01`` … ``S02E01``, not two ``E01``."""
    sources = [*A.season(1)[:2], *A.season(2)[:2]]
    (group,) = group_sources(sources, "standard")
    template = A.example_template()
    rows = resolve_group(group, template, sources)
    resolution = BatchResolution(group=group, columns=matrix_columns(template), rows=rows)
    labels = [line.split()[0] for line in matrix_lines(resolution)[2:]]
    assert labels == ["S01E01", "S01E02", "S02E01", "S02E02"]
    one_season = BatchResolution(group=group, columns=matrix_columns(template), rows=rows[:2])
    assert [line.split()[0] for line in matrix_lines(one_season)[2:]] == ["E01", "E02"]


def test_episode_labels() -> None:
    folder = Path("/media/Show.S01")
    paths = [
        folder / "Show.S01E01.BluRay.mkv",
        folder / "Show.S01E01.WEB.mkv",
        folder / "Show.S01E02.mkv",
        folder / "movie.mkv",
    ]
    # Two files of one episode: their file names.
    episode_labels = grouping.episode_labels
    assert episode_labels(paths) == [
        "Show.S01E01.BluRay.mkv",
        "Show.S01E01.WEB.mkv",
        "E02",
        "movie.mkv",
    ]
    assert episode_labels(paths[2:], season=True) == ["S01E02", "movie.mkv"]
    assert episode_labels([Path("/a/Show.S01E01.mkv"), Path("/a/Show.S02E01.mkv")]) == [
        "S01E01",
        "S02E01",
    ]


# --------------------------------------------------------------------------- suspected points


def _audio_rule(**kw: Any) -> OutputTrackRule:
    settings = kw.pop("settings", AudioOutputSettings())
    return OutputTrackRule(
        selector=TrackSelector.model_validate({"kind": "audio", **kw}), settings=settings
    )


def test_a_hand_pick_counts_as_an_exact_match() -> None:
    """0040 §2: a relaxed rule never takes a track that another rule matches exactly; a track
    picked by hand (``selector.stream``) is such a match."""
    e05 = A.recorded(1, 5)  # #1 jpn TrueHD, #2 eng DTS-HD MA, #3 eng AC-3 2.0 "Commentary"
    rules = [
        _audio_rule(stream=2),
        _audio_rule(languages=["eng"], codecs=["eac3"]),  # relaxed: any eng track
    ]
    result = resolve_tracks(JobTemplate(audio_rules=rules), e05, definitions=DEFS)
    assert [(m.status, m.streams) for m in result.matches[:2]] == [
        ("exact", [2]),
        ("relaxed", [3]),
    ]


def test_a_track_that_two_rules_take_is_the_first_of_its_language_for_both() -> None:
    """A codec rule for the first track of a language applies to every output of that track
    (a second rule that takes the same source track does not make it a second track)."""
    e01 = A.recorded(1, 1)
    first_only = AudioCodecRule(
        languages=["ja"],
        codec="libopus",
        mixdown="5.1",
        max_bitrate=448,
        if_fits="reencode",
        extras=AudioRuleExtras(first_track_of_language_only=True),
    )
    codec_rules = AudioCodecRules(rules=[first_only, AudioCodecRule(codec="aac")])
    rules = [
        _audio_rule(languages=["jpn"], settings=codec_rules),
        _audio_rule(languages=["jpn"], settings=codec_rules),
    ]
    result = resolve_tracks(JobTemplate(audio_rules=rules), e01, definitions=DEFS)
    assert [(a.source_stream, a.encoder) for a in result.draft.audio] == [
        (1, "libopus"),
        (1, "libopus"),
    ]


def test_a_rule_with_settings_of_the_other_kind_is_not_an_exact_cell() -> None:
    e05 = A.recorded(1, 5)
    wrong = _audio_rule(languages=["jpn"], settings=SubtitleOutputSettings())
    result = resolve_tracks(JobTemplate(audio_rules=[wrong]), e05, definitions=DEFS)
    assert result.draft.audio == []
    (cell,) = [m for m in result.matches if m.kind == "audio"]
    assert (cell.status, cell.severity.value if cell.severity else None) == ("missing", "error")
    assert cell.message == "the rule has subtitle settings: it makes no audio track"
    assert [i.code for i in result.draft.issues] == ["batch.rule_settings"]
