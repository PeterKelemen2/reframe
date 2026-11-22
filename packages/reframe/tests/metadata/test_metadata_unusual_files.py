"""Metadata edits of unusual files through the facade, the real queue and the real writer:
the file's BCP 47 tags, an invalid ``LanguageIETF``, and a SeekHead position past 2^63.
mkvpropedit only makes the unusual files."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from reframe.models import JobDraft, JobState
from reframe_testing.ebml import with_bogus_seek_entry
from reframe_testing.mkvtoolnix import mkvtoolnix_tool, with_bad_tag

from .test_metadata_edit_real import Env, draft_remux, env, mkvmerge, reprobe, run

pytestmark = [pytest.mark.needs_ffmpeg, pytest.mark.anyio]
__all__ = ["env"]


async def test_the_reprobe_shows_only_the_files_bcp47_tags(env: Env) -> None:
    """Untouched tracks have no ``LanguageIETF``: no tag is derived from ``eng``."""
    app = await env.app()
    try:
        job = await draft_remux(app, env.source)
        hungarian, brazilian, commentary = job.audio
        hungarian.metadata.language = "hu"
        brazilian.metadata.language = "pt-BR"
        commentary.metadata.commentary = True
        job.subtitles[0].metadata.language = "hu"
        ended = await run(app, job)
        assert ended.state is JobState.DONE, ended.error
        out = await reprobe(app, env.source)
        assert [(s.language, s.language_ietf) for s in [*out.audio, *out.subtitles]] == [
            ("hun", "hu"), ("por", "pt-BR"), ("eng", None),
            ("hun", "hu"), ("eng", None), ("eng", None),
        ]  # fmt: skip
        tracks = mkvmerge(env.source)
        if tracks:  # MKVToolNix agrees
            assert [t.get("language_ietf") for t in tracks[1:]] == [
                "hu", "pt-BR", None, "hu", None, None,
            ]  # fmt: skip
    finally:
        await app.close()


@pytest.mark.needs_mkvtoolnix
@pytest.mark.parametrize("bad", [b"en_US", b"j\na;x"])
async def test_a_file_with_an_invalid_language_ietf_can_be_drafted_and_planned(
    env: Env, bad: bytes
) -> None:
    with_bad_tag(env.source, mkvtoolnix_tool("mkvpropedit"), bad)
    app = await env.app()
    try:
        draft = await app.jobs.draft(env.source)
        assert isinstance(draft, JobDraft), draft
        assert draft.job.audio[0].metadata.language in (None, "ja")
        job = await draft_remux(app, env.source)
        assert job.audio[0].metadata.language == "ja"  # the legacy jpn
        plan = await app.jobs.plan(job)
        assert not isinstance(plan, list), plan
        source = await reprobe(app, env.source)
        assert any("is not a language tag" in w for w in source.warnings)
    finally:
        await app.close()


def with_long_names(path: Path, name: str) -> None:
    names = [arg for n in (1, 2, 3) for arg in ("--edit", f"track:a{n}", "--set", f"name={name}")]
    subprocess.run(
        [mkvtoolnix_tool("mkvpropedit"), str(path), *names], check=True, capture_output=True
    )


@pytest.mark.needs_mkvtoolnix
async def test_an_in_place_edit_of_a_file_with_a_seek_position_past_2_63_is_refused(
    env: Env,
) -> None:
    long = "N" * 6000
    with_long_names(env.source, long)
    with_bogus_seek_entry(env.source)
    before = env.source.read_bytes()
    app = await env.app()
    try:
        source = await reprobe(app, env.source)
        assert [a.title for a in source.audio] == [long, long, long]
        job = await draft_remux(app, env.source)
        job.audio[0].metadata.name = "Short"
        ended = await run(app, job)
        assert ended.state is JobState.FAILED
        assert ended.error is not None
        assert ended.error.startswith(
            "Reframe cannot edit the Matroska header of Show.S01E01.mkv:"
        ), ended.error
        assert env.source.read_bytes() == before
    finally:
        await app.close()
