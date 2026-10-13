"""Shared helpers of the command builder tests (C-7).

- :func:`recorded`: a ``MediaSource`` from the recorded ffprobe JSON (``testdata/probes``),
  parsed as C-3 parses it, at a fixed path (``/media/<name>``) so plans do not depend on
  the machine.
- :func:`caps`: a capability snapshot where every encoder of the definitions is available
  (VAAPI on ``/dev/dri/renderD128``) and the build has every filter.
- :func:`tools`: a tool set with ffmpeg, ffprobe and mkvpropedit found (no paths: the
  display shows the bare names).
- :func:`draft`: a job like the M2 draft (decision 0018): every audio track (encoded or
  passed through), every subtitle copied, the metadata of the source tracks.
- :func:`run_plan`: runs a plan's steps with real tools, as the queue (C-11) will: writes
  the plan files, parses the ``loudnorm`` measurements of ``analyse`` steps, resolves the
  templates, renames the partial file.
"""

from __future__ import annotations

import json
import re
import subprocess
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from reframe.definitions import load_definitions
from reframe.models import (
    AudioAction,
    AudioOutputTrack,
    CapabilitySnapshot,
    Container,
    EncodePlan,
    EncoderState,
    EncoderStatus,
    JobSettings,
    MediaSource,
    OutputSettings,
    SourceFingerprint,
    SourceRef,
    SubtitleOutputTrack,
    ToolInfo,
    ToolName,
    ToolSet,
    ToolStatus,
    TrackMetadata,
    resolve_argv,
)
from reframe.probe import parse_ffprobe

ROOT = Path(__file__).resolve().parents[4]
PROBES = ROOT / "testdata" / "probes"
MEDIA = Path("/media")
OUT = Path("/out")


def recorded(name: str, *, path: Path | None = None) -> MediaSource:
    """``multitrack.mkv`` (a generated fixture) or ``truehd-atmos`` (a recorded probe, at its
    recorded file name: ``/media/movie-truehd-atmos.mkv``)."""
    probe = PROBES / "fixtures" / f"{name}.json"
    file_name = name
    if not probe.exists():
        probe = PROBES / f"{name}.json"
        file_name = ""
    frames = probe.with_name(probe.name.removesuffix(".json") + ".frames.json")
    data = json.loads(probe.read_text(encoding="utf-8"))
    file_name = file_name or str(data["format"]["filename"])
    return parse_ffprobe(
        data,
        path if path is not None else MEDIA / file_name,
        frames=json.loads(frames.read_text(encoding="utf-8")) if frames.exists() else None,
        fingerprint=SourceFingerprint(size=0, mtime=0.0),
    )


def caps(
    *,
    libplacebo: bool | None = True,
    devices: dict[str, str] | None = None,
    unavailable: Iterable[str] = (),
    filters: bool = True,
) -> CapabilitySnapshot:
    defs = load_definitions()
    down = set(unavailable)
    encoders: dict[str, EncoderStatus] = {}
    for enc_id in [*defs.video_encoders, *defs.audio_encoders]:
        device = None
        if enc_id.endswith("_vaapi"):
            device = (devices or {}).get(enc_id, "/dev/dri/renderD128")
        encoders[enc_id] = EncoderStatus(
            id=enc_id,
            state=EncoderState.UNAVAILABLE if enc_id in down else EncoderState.AVAILABLE,
            device=device,
        )
    names = sorted({n for f in defs.filters.values() for i in f.implementations for n in i.filters})
    failures = {"libplacebo": "No working Vulkan driver"} if libplacebo is False else {}
    untested = ["libplacebo"] if libplacebo is None else []
    return CapabilitySnapshot(
        encoders=encoders,
        filters=names if filters else None,
        filter_failures=failures,
        untested_filters=untested,
    )


def tools(*, mkvpropedit: bool = True, paths: dict[ToolName, Path] | None = None) -> ToolSet:
    def info(name: ToolName, found: bool = True) -> ToolInfo:
        return ToolInfo(
            name=name,
            status=ToolStatus.FOUND if found else ToolStatus.MISSING,
            path=(paths or {}).get(name),
        )

    return ToolSet(
        ffmpeg=info("ffmpeg"),
        ffprobe=info("ffprobe"),
        mkvpropedit=info("mkvpropedit", mkvpropedit),
        mediainfo=info("mediainfo", False),
    )


def source_metadata(stream: Any) -> TrackMetadata:
    """The flags of a source track (decision 0018: a draft keeps them)."""
    d = stream.disposition
    return TrackMetadata(
        default=d.default,
        forced=d.forced,
        commentary=d.comment,
        hearing_impaired=d.hearing_impaired,
        visual_impaired=d.visual_impaired,
        original=d.original,
    )


def draft(
    source: MediaSource,
    *,
    output: Path | None = None,
    container: Container = "mkv",
    audio: AudioAction = "encode",
    audio_encoder: str | None = "aac",
    subtitles: bool = True,
    **settings: Any,
) -> JobSettings:
    """An M2-style draft job; ``settings`` are JobSettings fields (``video=…``)."""
    ext = {"mkv": ".mkv", "mp4": ".mp4", "webm": ".webm"}[container]
    path = output if output is not None else OUT / (source.ref.path.stem + ext)
    out = settings.pop("output_settings", {})
    job = JobSettings(
        source=SourceRef(path=source.ref.path),
        output=OutputSettings(container=container, path=path, **out),
        audio=[
            AudioOutputTrack(
                source_stream=a.index,
                action=audio,
                encoder=audio_encoder,
                metadata=source_metadata(a),
            )
            for a in source.audio
        ],
        subtitles=(
            [
                SubtitleOutputTrack(source=s.index, metadata=source_metadata(s))
                for s in source.subtitles
            ]
            if subtitles
            else []
        ),
    )
    video = settings.pop("video", None)
    if video is not None:
        job.video = job.video.model_validate(
            {**job.video.model_dump(), "passthrough": False, **video}
        )
    video_metadata = source_metadata(source.video[0]) if source.video else TrackMetadata()
    job.video.metadata = video_metadata
    return job.model_copy(update=settings)


# --------------------------------------------------------------------------- running plans

_LOUDNORM = re.compile(r"\{[^{}]*\"input_i\"[^{}]*\}", re.S)


@dataclass
class RunResult:
    plan: EncodePlan
    measured: dict[str, str] = field(default_factory=dict)
    stderr: list[str] = field(default_factory=list)
    leftovers: list[Path] = field(default_factory=list)
    """Temp files that existed after the steps ran (before the cleanup)."""


def run_plan(plan: EncodePlan, tool_paths: dict[str, str], *, cleanup: bool = True) -> RunResult:
    """Run every step like the queue (C-11) will. Raises ``AssertionError`` when a step
    fails (with its stderr)."""
    result = RunResult(plan)
    for f in plan.files:
        f.path.write_text(f.content, encoding="utf-8", newline="\n")
    try:
        for step in plan.steps:
            if step.tool is None:
                plan.output_tmp.replace(plan.output_final)
                continue
            argv = [tool_paths[step.tool], *resolve_argv(step.argv, result.measured)]
            proc = subprocess.run(argv, capture_output=True, text=True, timeout=300, check=False)
            result.stderr.append(proc.stderr)
            assert proc.returncode == 0, f"{step.kind} failed ({proc.returncode}):\n{proc.stderr}"
            if step.measures:
                blocks = _LOUDNORM.findall(proc.stderr)
                assert len(blocks) == len(step.measures), proc.stderr
                for measurement, block in zip(step.measures, blocks, strict=True):
                    for key, value in json.loads(block).items():
                        result.measured[f"{measurement.id}.{key}"] = str(value)
    finally:
        result.leftovers = [p for p in plan.temp_files if p.exists()]
        if cleanup:
            for p in [*plan.temp_files, *(f.path for f in plan.files)]:
                p.unlink(missing_ok=True)
    return result


def ffprobe_json(tool: str, path: Path, *args: str) -> dict[str, Any]:
    proc = subprocess.run(
        [tool, "-v", "error", "-of", "json", *args, str(path)],
        capture_output=True,
        text=True,
        check=True,
        timeout=60,
    )
    data: dict[str, Any] = json.loads(proc.stdout)
    return data
