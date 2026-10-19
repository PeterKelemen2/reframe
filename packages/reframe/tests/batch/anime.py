"""Recorded probes of the example anime season, and the example job and template built from them.

The probes are the committed JSON of the generated ``anime-s01`` and ``anime-s02`` fixtures,
recorded with the pinned FFmpeg build. Their media paths are virtual, under ``/media``, so the
tests do not depend on the FFmpeg that runs them.
"""

from __future__ import annotations

import json
from pathlib import Path

from reframe.batch import derive_template, resolve
from reframe.jobs import draft_from_preset
from reframe.jsonpatch import apply_patch
from reframe.models import (
    JobSettings,
    JobTemplate,
    MediaSource,
    NamingOptions,
    Preset,
    PresetFile,
    SourceFingerprint,
)
from reframe.presets import builtin_presets
from reframe.probe import parse_ffprobe
from reframe_testing import media

ROOT = Path(__file__).resolve().parents[4]
PROBES = ROOT / "testdata" / "probes" / "fixtures"
MEDIA = Path("/media")
#: Output names such as ``Show - S01E01 - Pilot.mkv``.
EXAMPLE_NAMING = NamingOptions(
    movie_template="{name}",
    episode_template="{name} - S{season:02}E{episode:02}< - {sub_title}>",
    word_separator="space",
)
#: The name of the user preset that :func:`preset_document` writes.
PRESET_NAME = "Anime Season (04 example)"
#: The preset file that the ``__main__`` block writes and the tests import.
PRESET_FILE = Path(__file__).with_name("data") / "anime-season.preset.json"


def builtin(preset_id: str) -> Preset:
    return next(p for p in builtin_presets() if p.id == preset_id)


def path(season: int, episode: int) -> Path:
    return MEDIA / media.anime_folder(season) / media.anime_file_name(season, episode)


def recorded(season: int, episode: int) -> MediaSource:
    rel = f"{media.anime_folder(season)}/{media.anime_file_name(season, episode)}"
    data = json.loads((PROBES / f"{rel}.json").read_text(encoding="utf-8"))
    return parse_ffprobe(
        data, path(season, episode), fingerprint=SourceFingerprint(size=0, mtime=0.0)
    )


def season(number: int = 1) -> list[MediaSource]:
    """Every episode of ``number``, in episode order."""
    return [recorded(number, n) for n in range(1, len(media.ANIME_TITLES[number]) + 1)]


def example_job(e01: MediaSource) -> JobSettings:
    """E01's job with its audio and subtitle tracks set by hand."""
    job, _tracks, _notes = draft_from_preset(e01, builtin("h265-mkv-1080p"))
    a1, a2 = job.audio
    job.audio = [
        a1.model_copy(
            update={
                "action": "encode",
                "encoder": "libopus",
                "mixdown": "5.1",
                "bitrate": 448,
                "metadata": a1.metadata.model_copy(
                    update={"name": "Japanese 5.1", "default": True}
                ),
            }
        ),
        a2.model_copy(
            update={
                "action": "encode",
                "encoder": "ac3",
                "mixdown": "5.1",
                "bitrate": 640,
                "metadata": a2.metadata.model_copy(
                    update={"name": "English 5.1", "default": False}
                ),
            }
        ),
    ]
    s1, s2 = job.subtitles
    job.subtitles = [
        s1.model_copy(
            update={"metadata": s1.metadata.model_copy(update={"forced": True, "default": False})}
        ),
        s2.model_copy(
            update={"metadata": s2.metadata.model_copy(update={"forced": False, "default": True})}
        ),
    ]
    return job


def example_template(e01: MediaSource | None = None) -> JobTemplate:
    """The group template of :func:`example_job`'s audio and subtitles, with the example naming."""
    source = e01 if e01 is not None else recorded(1, 1)
    template = derive_template(
        example_job(source), source, {"audio", "subtitles"}, base=builtin("h265-mkv-1080p")
    )
    return template.model_copy(update={"naming": EXAMPLE_NAMING})


#: The id of the preset in :data:`PRESET_FILE`. Fixed, so rewriting the file changes nothing.
PRESET_ID = "5f0c1d3e-04e0-4a7e-9b1a-0000000000c7"


def demo_template() -> JobTemplate:
    """:func:`example_template` with the fix that E11's missing track offers, so that every
    episode can be queued."""
    template = example_template()
    e11 = resolve(template, recorded(1, 11))
    (missing,) = [issue for issue in e11.issues if issue.code == "batch.track_missing"]
    (fix,) = missing.fixes
    patched: JobTemplate = JobTemplate.model_validate(
        apply_patch(template.model_dump(mode="json"), fix.patch)
    )
    return patched


def preset_document() -> dict[str, object]:
    """The :func:`demo_template` as the user preset :data:`PRESET_NAME`, in the format that
    ``reframe presets export`` writes."""
    data = demo_template().model_dump(mode="json", exclude={"schema_version"})
    data.update(
        id=PRESET_ID,
        name=PRESET_NAME,
        category="Custom",
        description="04 §Example: jpn TrueHD → Opus 5.1, eng DTS-HD MA → AC-3 5.1 (optional: "
        "E11 has no dub), Signs & Songs (forced), Full (default); Show - S01E01 - Title.mkv",
        built_in=False,
    )
    preset = Preset.model_validate(data)
    return PresetFile(presets=[preset]).model_dump(mode="json")


if __name__ == "__main__":  # write the preset file: PYTHONPATH=testing uv run python <this file>
    PRESET_FILE.parent.mkdir(exist_ok=True)
    text = json.dumps(preset_document(), indent=2, ensure_ascii=False) + "\n"
    PRESET_FILE.write_text(text, encoding="utf-8")
    print(PRESET_FILE)
