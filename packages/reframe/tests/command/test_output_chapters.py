"""The output's chapters (``output_chapters``) and the chapters the plan writes come from one
function: the table the user sees is what the encode writes. The real encodes are in
``reframe-server/tests/test_job_output.py``."""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from reframe.command import build_plan, output_chapters
from reframe.command.metadata import (
    chapter_plan,
    generated_starts,
    planned_chapters,
    rendered_tags,
)
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


@pytest.mark.parametrize(
    "chapters",
    [ChapterSettings(names=["Intro"]), ChapterSettings(names=["Intro", "", "", ""])],
)
def test_a_rename_leaves_an_untitled_chapter_untitled_in_the_table_and_the_file(
    chapters: ChapterSettings,
) -> None:
    source = untitled(FILM, 1)
    job = draft(source, chapters=chapters)
    assert [r[3] for r in rows(job, source)] == ["Intro", "", "Part Two", "Credits"]
    content = written(job, source)
    assert content is not None
    assert "title=Intro\n" in content
    assert "START=1000\nEND=2500\n[CHAPTER]" in content


def test_a_range_cut_inside_an_untitled_chapter_keeps_it_untitled() -> None:
    source = untitled(FILM, 1)
    job = draft(source, range=TimeRange(start=1.5, end=4.0))
    assert [r[3] for r in rows(job, source)] == ["", "Part Two"]
    content = written(job, source)
    assert content is not None
    assert "title=" + "Chapter 2" not in content


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


@pytest.mark.parametrize("every", [1e-7, 1e-300, 5e-324])
def test_an_interval_that_makes_too_many_chapters_makes_none_at_once(every: float) -> None:
    plain = recorded("multitrack.mkv")
    job = draft(plain, chapters=ChapterSettings(generate_every=every))
    started = time.monotonic()
    found = output_chapters(job, plain, definitions=DEFS)
    assert time.monotonic() - started < 0.5
    assert (found.origin, found.chapters) == ("none", [])
    assert found.reason == (
        f"A chapter every {every:g} minutes would make more than 1000 chapters, so none are "
        "generated."
    )
    assert written(job, plain) == "-map_chapters -1"


@pytest.mark.parametrize(
    ("seconds", "count"),
    [
        (1000.0, 1000),  # the last start, 999, is a whole step before the end
        (1000.2, 1000),  # a tail shorter than a quarter step joins the chapter before it
        (1000.5, None),  # a longer tail is chapter 1001
    ],
)
def test_the_limit_counts_the_chapters_that_are_written(seconds: float, count: int | None) -> None:
    starts = generated_starts(1 / 60, seconds)
    assert (len(starts) if starts is not None else None) == count


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
