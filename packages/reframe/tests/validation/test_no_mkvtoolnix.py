"""Without any MKVToolNix program, nothing about the Matroska header is refused or lost: an
in-place edit, a BCP 47 language and every track flag validate without an issue."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

from reframe.definitions.models import TRACK_FLAGS
from reframe.metadata import remux_job


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


def test_an_in_place_edit_needs_no_mkvtoolnix() -> None:
    s = sc.base()
    s.job = remux_job(s.job, s.source, edit_in_place=True)
    s.job.audio[0].metadata.language = "pt-BR"
    s.job.audio[0].metadata.original = True
    assert s.validate() == []


def test_a_bcp47_language_and_every_flag_need_no_mkvtoolnix() -> None:
    s = sc.base()
    s.job.audio[0].metadata.language = "pt-BR"
    s.source.subtitles[0].language_ietf = "zh-Hant"
    for flag in TRACK_FLAGS:
        setattr(s.job.subtitles[0].metadata, flag, True)
    assert s.validate() == []
