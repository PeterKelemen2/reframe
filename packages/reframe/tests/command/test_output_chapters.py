"""The output's chapters (``output_chapters``) and the chapters the plan writes come from one
function: the table the user sees is what the encode writes. The real encodes are in
``reframe-server/tests/test_job_output.py``."""

from __future__ import annotations

from pathlib import Path

import pytest

from reframe.command import build_plan, output_chapters
from reframe.command.metadata import chapter_plan, planned_chapters, rendered_tags
from reframe.definitions import load_definitions
from reframe.models import (
    Chapter,
    ChapterRange,
    ChapterSettings,
    ContainerInfo,
    FrameRange,
    JobSettings,
    MediaSource,
    NamingOptions,
    TagSettings,
    TimeRange,
)

from .conftest import caps, draft, recorded, tools

DEFS = load_definitions()
FILM = recorded("chapters.mkv")


def untitled(source: MediaSource, *indexes: int) -> MediaSource:
    chapters = [
        c.model_copy(update={"title": None}) if c.index in indexes else c for c in source.chapters
    ]
    return source.model_copy(update={"chapters": chapters})


def rows(job: JobSettings, source: MediaSource = FILM) -> list[tuple[object, ...]]:
    found = output_chapters(job, source, definitions=DEFS)
    return [(c.number, c.start, c.end, c.name, c.source_index) for c in found.chapters]


def written(job: JobSettings, source: MediaSource = FILM) -> str | None:
    """The FFMETADATA file of the plan, or ``-map_chapters`` when there is none."""
    plan = build_plan(job, source, caps(), tools(), definitions=DEFS)
    if plan.files:
        return plan.files[0].content
    argv = plan.steps[-2].argv
    return "-map_chapters " + str(argv[argv.index("-map_chapters") + 1])


def test_copied_chapters_keep_a_missing_title_and_are_mapped_from_the_source() -> None:
    source = untitled(FILM, 1)
    job = draft(source)
    assert rows(job, source) == [
        (1, 0.0, 1.0, "Opening", 0),
        (2, 1.0, 2.5, "", 1),
        (3, 2.5, 4.0, "Part Two", 2),
        (4, 4.0, 5.0, "Credits", 3),
    ]
    assert written(job, source) == "-map_chapters 0"


def test_renamed_chapters_without_a_name_or_title_get_chapter_n_in_the_table_and_the_file() -> None:
    source = untitled(FILM, 1)
    job = draft(source, chapters=ChapterSettings(names=["Intro"]))
    assert [r[3] for r in rows(job, source)] == ["Intro", "Chapter 2", "Part Two", "Credits"]
    content = written(job, source)
    assert content is not None
    assert "title=Intro\n" in content
    assert "title=Chapter 2\n" in content


def test_a_range_that_ends_on_a_chapter_edge_writes_the_same_chapters_as_the_table() -> None:
    """``-map_chapters 0`` would write an empty chapter there, so the plan writes a file."""
    job = draft(FILM, range=ChapterRange(start=2, end=3))
    assert rows(job) == [(1, 0.0, 1.5, "Part One", 1), (2, 1.5, 3.0, "Part Two", 2)]
    content = written(job)
    assert content is not None
    assert "START=0\nEND=1500\ntitle=Part One" in content
    assert "START=1500\nEND=3000\ntitle=Part Two" in content


def test_a_range_outside_every_chapter_has_none_and_maps_none() -> None:
    source = FILM.model_copy(
        update={"chapters": [Chapter(index=0, start=0.0, end=1.0, title="Only")]}
    )
    job = draft(source, range=TimeRange(start=2.0, end=3.0))
    found = output_chapters(job, source, definitions=DEFS)
    assert (found.origin, found.reason) == ("none", "No chapter of the source is inside the range.")
    assert written(job, source) == "-map_chapters -1"


@pytest.mark.parametrize(
    ("change", "reason"),
    [
        ({"chapters": ChapterSettings(enabled=False)}, "Create chapter markers is off."),
        (
            {"range": ChapterRange(start=7, end=9)},
            "The range is not inside the source, so its chapters are not known.",
        ),
        ({"range": FrameRange(start=0, end=10)}, None),
    ],
)
def test_no_chapters_say_why(change: dict[str, object], reason: str | None) -> None:
    found = output_chapters(draft(FILM).model_copy(update=change), FILM, definitions=DEFS)
    if reason is None:
        assert found.origin == "source"
    else:
        assert (found.origin, found.chapters, found.reason) == ("none", [], reason)


def test_a_frame_range_of_a_source_without_video_is_not_known() -> None:
    source = FILM.model_copy(update={"video": []})
    job = draft(FILM, range=FrameRange(start=0, end=10))
    found = output_chapters(job, source, definitions=DEFS)
    assert found.reason == "The range is not inside the source, so its chapters are not known."


def test_an_unknown_container_says_so() -> None:
    job = draft(FILM)
    job.output.container = "avi"  # type: ignore[assignment]
    assert output_chapters(job, FILM, definitions=DEFS).reason == "The container avi is not known."


def test_a_container_without_chapters_says_so() -> None:
    mkv = DEFS.containers["mkv"].model_copy(update={"chapters": False})
    found, _ = planned_chapters(draft(FILM), FILM, mkv, start=0, duration=None, expected_duration=5)
    assert found.reason == "Matroska (MKV) files cannot hold chapters."
    plan = chapter_plan(
        draft(FILM), FILM, mkv, start=0, duration=None, expected_duration=5, file_path=Path("c")
    )
    assert plan.map_from is None


def test_generated_chapters_are_numbered_and_named_by_position() -> None:
    plain = recorded("multitrack.mkv")
    job = draft(plain, chapters=ChapterSettings(generate_every=1.5 / 60, names=["", "Two"]))
    assert rows(job, plain) == [
        (1, 0.0, 1.5, "Chapter 1", None),
        (2, 1.5, 3.0, "Two", None),
        (3, 3.0, 4.021, "Chapter 3", None),
    ]
    content = written(job, plain)
    assert content is not None
    assert content.count("[CHAPTER]") == 3


@pytest.mark.parametrize(
    ("generate", "duration", "reason"),
    [
        (None, 4.0, "The source has no chapters."),
        (1.0, None, "The source's duration is not known, so no chapters can be generated."),
    ],
)
def test_a_source_without_chapters_says_why_none_are_made(
    generate: float | None, duration: float | None, reason: str
) -> None:
    plain = recorded("multitrack.mkv")
    plain = plain.model_copy(
        update={
            "container": ContainerInfo(duration=duration),
            "video": [v.model_copy(update={"duration": None}) for v in plain.video],
        }
    )
    job = draft(plain, chapters=ChapterSettings(generate_every=generate))
    assert output_chapters(job, plain, definitions=DEFS).reason == reason


def test_the_source_value_of_a_tag_is_found_in_any_case() -> None:
    source = FILM.model_copy(
        update={
            "container": FILM.container.model_copy(
                update={"tags": {"ARTIST": "Cast", "synopsis": "Story"}, "title": "Film"}
            )
        }
    )
    job = draft(source, tags=TagSettings(director="{file_name}"))
    found = rendered_tags(
        job, source, options=NamingOptions(), output_size=(320, 180), now=None, definitions=DEFS
    )
    assert (found.source.title, found.source.actors, found.source.plot) == ("Film", "Cast", "Story")
    assert found.values.director == "chapters"
    assert found.values.title is None
