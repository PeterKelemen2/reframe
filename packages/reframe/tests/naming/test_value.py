"""``reframe.naming.render_value``: one value template with the naming variables (C-16's public
form of what C-7 writes as a tag value and C-13 as the container title)."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from reframe.models import (
    JobNaming,
    JobSettings,
    NamingOptions,
    OutputSettings,
    SourceRef,
)
from reframe.naming import FileTimes, render_value
from reframe.naming.value import NoFiles

from .conftest import FakeFs, FsFactory


def job(path: str, **naming: object) -> JobSettings:
    return JobSettings(
        source=SourceRef(path=Path(path)),
        output=OutputSettings(naming=JobNaming(**naming)),  # type: ignore[arg-type]
    )


SPACE = NamingOptions(word_separator="space")


def test_plain_text_and_escapes() -> None:
    assert render_value("No variables {{x}}", job("/m/a.mkv")) == "No variables {x}"
    assert render_value("A / B", job("/m/a.mkv")) == "A / B"


def test_variables_from_the_release_name() -> None:
    episode = job("/media/Show.S01E02.Pilot.1080p.mkv")
    text = render_value(
        "{name}< - S{season:02}E{episode:02}>< - {sub_title}>", episode, options=SPACE
    )
    assert text == "Show - S01E02 - Pilot"
    assert render_value("{name} ({year})", job("/m/The.Movie.2024.mkv"), options=SPACE) == (
        "The Movie (2024)"
    )


def test_template_errors_are_written_as_typed() -> None:
    assert render_value("broken {name", job("/m/a.mkv")) == "broken {name"


def test_date_needs_now() -> None:
    movie = job("/m/a.mkv")
    assert render_value("{date:%Y}<, {time}>", movie) == ""
    assert render_value("{date:%Y}", movie, now=datetime(2026, 1, 2, tzinfo=UTC)) == "2026"


def test_field_overrides_and_name_source_of_the_job() -> None:
    fixed = job("/m/Show.S01E02.mkv", field_overrides={"name": "Better Show"})
    assert render_value("{name}", fixed, options=SPACE) == "Better Show"


def test_file_system_reads_only_with_fs(fake_fs: FsFactory) -> None:
    file = Path("/m/a.mkv")
    stamp = datetime(2025, 5, 6, 7, 8, tzinfo=UTC)
    fs: FakeFs = fake_fs({}, {file: FileTimes(modified=stamp)})
    template = "{modification-date:%Y}"
    assert render_value(template, job(str(file))) == ""
    assert render_value(template, job(str(file)), fs=fs) == "2025"
    assert NoFiles().list_files(Path("/m")) is None
    assert NoFiles().file_times(file) is None


def test_output_size_variables() -> None:
    text = render_value("{width}x{height} {resolution}", job("/m/a.mkv"), output_size=(1920, 800))
    assert text == "1920x800 1080p"
