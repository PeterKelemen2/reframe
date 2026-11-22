"""Without any MKVToolNix program, nothing about the Matroska header is refused or lost: an
in-place edit, a BCP 47 language and every track flag validate without an issue."""

from __future__ import annotations

from reframe.definitions.models import TRACK_FLAGS
from reframe.metadata import remux_job

from . import scenario as sc


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
