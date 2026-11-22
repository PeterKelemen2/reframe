"""Validation of in-place metadata edits: a clean edit and the write-a-new-file fix."""

from __future__ import annotations

from typing import Any

from reframe.metadata import remux_job
from reframe.models import NamingOptions

from . import scenario as sc


def in_place() -> Any:
    s = sc.base()
    s.job = remux_job(s.job, s.source, edit_in_place=True)
    return s


def test_a_clean_in_place_edit_has_no_issues() -> None:
    s = in_place()
    assert s.job.output.path == s.source.ref.path
    assert s.validate() == []
    s.job.output.path = None  # the source is edited: no output name needed
    assert s.validate() == []
    s.fs.free = 0  # nothing new is written
    assert s.validate() == []


def test_the_same_job_without_edit_in_place_writes_over_its_source() -> None:
    s = in_place()
    s.job.output.edit_in_place = False
    assert "output.same_as_source" in sc.error_codes(s.validate())


def test_write_a_new_file_fix_takes_a_free_name_when_naming_gives_the_source() -> None:
    s = in_place()
    s.job.audio[0].action = "encode"
    s.naming = NamingOptions(movie_template="{source}")  # the source's own name
    [issue] = [i for i in s.validate() if i.code == "inplace.not_possible"]
    [fix] = issue.fixes
    assert fix.label == "Write a new file (Movie.2019.1080p.BluRay (1).mkv)"
    assert issue in sc.check(s)  # check() asserts that each fix removes its issue


def test_write_a_new_file_fix_without_a_name() -> None:
    s = in_place()
    s.job.audio[0].action = "encode"
    s.naming = NamingOptions(output_folder_mode="fixed", output_folder=None)
    [issue] = [i for i in s.validate() if i.code == "inplace.not_possible"]
    assert issue.fixes[0].label == "Write a new file (Movie.2019.1080p.BluRay (1).mkv)"
