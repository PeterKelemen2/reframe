"""Validation of in-place metadata edits beyond the rule table (C-13,
``reframe.validation.inplace``): a clean in-place job has no issue at all (its output is the
source by design), the file-system checks, and the new output path of the fix."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

from reframe.metadata import remux_job
from reframe.models import NamingOptions


def _load(name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        f"_reframe_validation_{name}", Path(__file__).with_name(f"{name}.py")
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


sc = _load("scenario")


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
    assert sc.check(s) is not None  # every fix removes its issue and adds no error


def test_write_a_new_file_fix_without_a_name() -> None:
    s = in_place()
    s.job.audio[0].action = "encode"
    s.naming = NamingOptions(output_folder_mode="fixed", output_folder=None)
    [issue] = [i for i in s.validate() if i.code == "inplace.not_possible"]
    assert issue.fixes[0].label == "Write a new file (Movie.2019.1080p.BluRay (1).mkv)"
