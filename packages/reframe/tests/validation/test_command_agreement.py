"""What the command builder refuses is a validation error, and the snapshot jobs validate
without errors."""

from __future__ import annotations

import ast
import importlib
import importlib.util
import inspect
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path, PurePath
from types import ModuleType
from typing import Any

import pytest

import reframe.command
from reframe.command import PlanError, build_plan
from reframe.definitions import Definitions, load_definitions
from reframe.models import (
    AudioOutputTrack,
    AverageBitrate,
    CapabilitySnapshot,
    ChapterRange,
    ExternalSubtitle,
    FilterConfig,
    FilterSettings,
    FrameRange,
    JobSettings,
    MediaSource,
    Severity,
    SubtitleOutputTrack,
    TimeRange,
    ToolSet,
    ValidationIssue,
)
from reframe.validation import validate

_COMMAND_TESTS = Path(__file__).resolve().parents[1] / "command"


def _load_command_tests() -> tuple[ModuleType, ModuleType]:
    """The ``tests/command`` conftest and ``test_snapshots``, imported as a package of their own
    (they use relative imports; pytest runs with ``--import-mode=importlib``)."""
    name = "_reframe_c7_command_tests"
    if name not in sys.modules:
        spec = importlib.util.spec_from_file_location(
            name, _COMMAND_TESTS / "__init__.py", submodule_search_locations=[str(_COMMAND_TESTS)]
        )
        assert spec is not None
        assert spec.loader is not None
        package = importlib.util.module_from_spec(spec)
        sys.modules[name] = package
        spec.loader.exec_module(package)
    return (
        importlib.import_module(f"{name}.conftest"),
        importlib.import_module(f"{name}.test_snapshots"),
    )


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


c7, snapshots = _load_command_tests()
sc = _load("scenario")
DEFS = load_definitions()


def file_system(job: JobSettings, source: MediaSource) -> Any:
    """The source, the external subtitle files and the output folder exist."""
    files: list[PurePath] = [source.ref.path]
    files += [t.source.path for t in job.subtitles if isinstance(t.source, ExternalSubtitle)]
    dirs = [job.output.path.parent] if job.output.path is not None else []
    return sc.FakeFs(files=files, dirs=dirs)


def run_validation(
    job: JobSettings,
    source: MediaSource,
    caps: CapabilitySnapshot,
    tools: ToolSet,
    definitions: Definitions | None = None,
    **kwargs: Any,
) -> list[ValidationIssue]:
    return validate(
        job,
        source,
        caps,
        tools,
        file_system(job, source),
        definitions=definitions,
        naming=kwargs.get("naming"),
    )


def errors(issues: list[ValidationIssue]) -> list[ValidationIssue]:
    return [i for i in issues if i.severity is Severity.ERROR]


@dataclass(frozen=True)
class Refusal:
    id: str
    raises: str
    """The ``PlanError`` text (a regular expression), which also names the ``raise``."""
    code: str
    """The validation error that reports it."""
    build: Callable[[], tuple[JobSettings, MediaSource, dict[str, Any]]]


def multitrack(change: Callable[[JobSettings], None] | None = None, **draft: Any) -> Any:
    def build() -> tuple[JobSettings, MediaSource, dict[str, Any]]:
        src = c7.recorded("multitrack.mkv")
        job = c7.draft(src, video={"encoder": "libx264"}, **draft)
        if change is not None:
            change(job)
        return job, src, {}

    return build


def on(source: str, change: Callable[[JobSettings], None], **draft: Any) -> Any:
    def build() -> tuple[JobSettings, MediaSource, dict[str, Any]]:
        src = c7.recorded(source)
        job = c7.draft(src, video={"encoder": "libx264"}, **draft)
        change(job)
        return job, src, {}

    return build


def setter(**changes: Any) -> Callable[[JobSettings], None]:
    """``video__encoder="x"`` sets ``job.video.encoder`` (without model validation, as a
    hand-edited or older file could hold it)."""

    def change(job: JobSettings) -> None:
        for key, value in changes.items():
            target, _, attr = key.partition("__")
            setattr(getattr(job, target) if attr else job, attr or target, value)

    return change


def filters(**configs: FilterConfig) -> Callable[[JobSettings], None]:
    def change(job: JobSettings) -> None:
        job.filters = FilterSettings(dict(configs))

    return change


def subtitles(*tracks: SubtitleOutputTrack) -> Callable[[JobSettings], None]:
    def change(job: JobSettings) -> None:
        job.subtitles = list(tracks)

    return change


def both(*changes: Callable[[JobSettings], None]) -> Callable[[JobSettings], None]:
    def change(job: JobSettings) -> None:
        for c in changes:
            c(job)

    return change


def without_video(job: JobSettings) -> None:
    del job


def no_frame_rate() -> tuple[JobSettings, MediaSource, dict[str, Any]]:
    src = c7.recorded("multitrack.mkv")
    src.video[0].frame_rate = None
    src.video[0].avg_frame_rate = None
    job = c7.draft(src, video={"encoder": "libx264"})
    job.range = FrameRange(start=1, end=5)
    return job, src, {}


def source_without_video() -> tuple[JobSettings, MediaSource, dict[str, Any]]:
    src = c7.recorded("multitrack.mkv")
    job = c7.draft(src, video={"encoder": "libx264"})
    return job, src.model_copy(update={"video": []}), {}


def unknown_video_codec() -> tuple[JobSettings, MediaSource, dict[str, Any]]:
    src = c7.recorded("multitrack.mkv")
    src.video[0].codec = None
    job = c7.draft(src, container="mp4", audio="passthru", subtitles=False)
    job.video.passthrough = True
    return job, src, {}


def zero_length_chapters() -> tuple[JobSettings, MediaSource, dict[str, Any]]:
    src = c7.recorded("chapters.mkv")
    for chapter in src.chapters:
        chapter.end = chapter.start = 1.0
    job = c7.draft(src, video={"encoder": "libx264"})
    job.range = ChapterRange(start=1, end=2)
    return job, src, {}


def custom_definitions(
    encoder: str, change: Callable[[Definitions], None], **video: Any
) -> Callable[[], tuple[JobSettings, MediaSource, dict[str, Any]]]:
    def build() -> tuple[JobSettings, MediaSource, dict[str, Any]]:
        defs = DEFS.model_copy(deep=True)
        change(defs)
        src = c7.recorded("multitrack.mkv")
        job = c7.draft(src, video={"encoder": encoder, **video})
        return job, src, {"definitions": defs}

    return build


def with_definitions(
    change_definitions: Callable[[Definitions], None], change: Callable[[JobSettings], None]
) -> Callable[[], tuple[JobSettings, MediaSource, dict[str, Any]]]:
    def build() -> tuple[JobSettings, MediaSource, dict[str, Any]]:
        defs = DEFS.model_copy(deep=True)
        change_definitions(defs)
        job, src, _ = multitrack(change)()
        return job, src, {"definitions": defs}

    return build


def deblock_needs_tune(defs: Definitions) -> None:
    preset = defs.filters["deblock"].implementations[0].preset("medium")
    assert preset is not None
    preset.chain = None


def no_quality_mode(defs: Definitions) -> None:
    defs.video_encoders["libx264"].rate_control.quality = None


def no_bitrate_mode(defs: Definitions) -> None:
    defs.video_encoders["libx264"].rate_control.bitrate = None


#: Text subtitle streams of ``multitrack.mkv`` (SRT); ``pgs`` has PGS streams 2 to 5.
SRT, SRT2 = 4, 5
BURN = SubtitleOutputTrack(source=SRT, action="burn")

REFUSALS: list[Refusal] = [
    Refusal("no output path", "output path is not set", "output.no_path",
            multitrack(setter(output__path=None))),
    Refusal("unknown container", "unknown container", "container.unknown",
            multitrack(setter(output__container="avi"))),
    Refusal("source without video", "no video stream", "source.no_video",
            source_without_video),
    Refusal("video passthrough the container cannot hold", "cannot be copied into WebM",
            "container.codec_unsupported",
            multitrack(both(setter(video__passthrough=True), subtitles()), container="webm",
                       audio="passthru")),
    Refusal("passthrough of an unknown video codec", " video cannot be copied into MP4",
            "container.codec_unsupported", unknown_video_codec),
    Refusal("unknown video encoder", "unknown video encoder", "encoder.unknown",
            multitrack(setter(video__encoder="libx266"))),
    Refusal("video codec the container cannot hold", "H.264 cannot be written into WebM",
            "container.codec_unsupported", multitrack(setter(output__container="webm"))),
    Refusal("no 10-bit mode", "no 10-bit mode", "encoder.no_10bit",
            multitrack(setter(video__encoder="h264_amf", video__bit_depth=10))),
    Refusal("audio source stream missing", "no audio stream 9", "audio.source_missing",
            multitrack(setter(audio=[AudioOutputTrack(source_stream=9)]))),
    Refusal("audio track without a source", "no audio stream None", "audio.source_missing",
            multitrack(setter(audio=[AudioOutputTrack()]))),
    Refusal("frame range without a frame rate", "frame rate", "range.no_frame_rate",
            no_frame_rate),
    Refusal("empty range", "range is empty", "range.outside",
            multitrack(setter(range=TimeRange(start=2.0, end=1.0)))),
    Refusal("chapter range of zero-length chapters", "range is empty", "range.outside",
            zero_length_chapters),
    Refusal("chapter range outside the source", "not in the source", "range.outside",
            on("chapters.mkv", setter(range=ChapterRange(start=5, end=6)))),
    Refusal("unknown audio encoder", "unknown audio encoder", "encoder.unknown",
            multitrack(setter(audio=[AudioOutputTrack(source_stream=1, encoder="vorbis")]))),
    Refusal("audio codec the container cannot hold", "AC-3 cannot be written into WebM",
            "container.codec_unsupported",
            multitrack(setter(video__encoder="libsvtav1",
                              audio=[AudioOutputTrack(source_stream=1, encoder="ac3")]),
                       container="webm", subtitles=False)),
    Refusal("passthru fallback the container cannot hold", "AAC cannot be written into WebM",
            "container.codec_unsupported",
            on("truehd-atmos", both(setter(video__encoder="libsvtav1"), subtitles()),
               container="webm", audio="passthru", audio_encoder=None)),
    Refusal("unknown filter", "unknown filter", "filter.unknown",
            multitrack(filters(vignette=FilterConfig()))),
    Refusal("unknown filter preset", "preset 'nope'", "filter.preset_unknown",
            multitrack(filters(denoise=FilterConfig(preset="nope")))),
    Refusal("unknown filter implementation", "cannot be used", "filter.implementation_unknown",
            multitrack(filters(denoise=FilterConfig(preset="light", implementation="bm3d")))),
    Refusal("filter implementation that cannot run", "cannot be used",
            "filter.implementation_unavailable",
            on("hdr10", filters(tonemap=FilterConfig(implementation="libplacebo")))),
    Refusal("filter preset that needs a tune", "cannot be used", "filter.tune_required",
            with_definitions(deblock_needs_tune, filters(deblock=FilterConfig(preset="medium")))),
    Refusal("more than one burn-in", "only one", "subtitle.burn_multiple",
            multitrack(subtitles(BURN, SubtitleOutputTrack(source=SRT2, action="burn")))),
    Refusal("burn-in with video passthrough", "passed through", "subtitle.burn_passthrough",
            multitrack(both(setter(video__passthrough=True), subtitles(BURN)),
                       audio="passthru")),
    Refusal("subtitle source stream missing", "no subtitle stream 9",
            "subtitle.source_missing", multitrack(subtitles(SubtitleOutputTrack(source=9)))),
    Refusal("conversion without a target", "needs a target",
            "subtitle.convert_target_missing",
            multitrack(subtitles(SubtitleOutputTrack(source=SRT, action="convert")))),
    Refusal("conversion from bitmap", "bitmap subtitles to text", "subtitle.convert_bitmap",
            on("pgs", subtitles(SubtitleOutputTrack(source=2, action="convert",
                                                    convert_to="srt")))),
    Refusal("conversion to a format the container cannot hold", "mov_text cannot be written",
            "container.codec_unsupported",
            multitrack(subtitles(SubtitleOutputTrack(source=SRT, action="convert",
                                                     convert_to="mov_text")))),
    Refusal("PGS into MP4", "cannot go into MP4", "subtitle.bitmap_unsupported",
            on("pgs", subtitles(SubtitleOutputTrack(source=2)), container="mp4")),
    Refusal("external subtitle of an unknown type", "unknown subtitle file type",
            "subtitle.external_unknown",
            multitrack(subtitles(SubtitleOutputTrack(
                source=ExternalSubtitle(path=Path("/media/multitrack.idx")))))),
    Refusal("a choice the encoder does not have", "no level setting",
            "encoder.level_unsupported", multitrack(setter(video__encoder="h264_qsv",
                                                           video__level="4.1"))),
    Refusal("x265 with a tune and fast decode", "takes one tune",
            "encoder.fast_decode_tune_conflict",
            multitrack(setter(video__encoder="libx265", video__tune="grain",
                              video__fast_decode=True))),
    Refusal("no constant-quality mode", "constant-quality", "encoder.rate_control_unsupported",
            custom_definitions("libx264", no_quality_mode)),
    Refusal("no average-bitrate mode", "average-bitrate", "encoder.rate_control_unsupported",
            custom_definitions("libx264", no_bitrate_mode, rate_control=AverageBitrate())),
    Refusal("no 2-pass mode", "no 2-pass", "encoder.two_pass_unsupported",
            multitrack(setter(video__encoder="h264_amf",
                              video__rate_control=AverageBitrate(two_pass=True)))),
]  # fmt: skip

#: ``raise PlanError`` sites that no job can reach (programming errors of the builder
#: itself), by the start of their message.
UNREACHABLE = {
    # video.py: the builder always passes the pass number and the log prefix.
    "a 2-pass encode needs the pass number",
    # video.py: a composite x26x parameter whose other part has no default; every shipped
    # composite part has one (``test_composite_parts_have_defaults``).
    "option ",
}


#: Refusals where the builder and validation disagree (refusal id → reason). The cases fail
#: (strict xfail) once the two agree.
DISAGREE: dict[str, str] = {}


@pytest.mark.parametrize(
    "refusal",
    [
        pytest.param(
            r,
            id=r.id,
            marks=[pytest.mark.xfail(reason=DISAGREE[r.id], strict=True)]
            if r.id in DISAGREE
            else [],
        )
        for r in REFUSALS
    ],
)
def test_plan_errors_are_validation_errors(refusal: Refusal) -> None:
    job, source, kwargs = refusal.build()
    caps = c7.caps(libplacebo=False)
    tools = c7.tools()
    with pytest.raises(PlanError, match=refusal.raises):
        build_plan(job, source, caps, tools, **kwargs)
    found = errors(run_validation(job, source, caps, tools, **kwargs))
    assert refusal.code in {i.code for i in found}, [(i.code, i.path, i.message) for i in found]


def test_a_chapter_range_end_after_the_last_chapter_is_clamped() -> None:
    job, source, kwargs = on("chapters.mkv", setter(range=ChapterRange(start=4, end=5)))()
    assert len(source.chapters) == 4
    caps = c7.caps(libplacebo=False)
    tools = c7.tools()
    build_plan(job, source, caps, tools, **kwargs)
    issues = run_validation(job, source, caps, tools, **kwargs)
    assert errors(issues) == []
    assert [(i.code, i.severity) for i in issues if i.code.startswith("range.")] == [
        ("range.end_beyond", Severity.WARNING)
    ]


def _plan_error_messages() -> list[str]:
    folder = Path(inspect.getfile(reframe.command)).parent
    found: list[str] = []
    for path in sorted(folder.glob("*.py")):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if (
                isinstance(node, ast.Raise)
                and isinstance(node.exc, ast.Call)
                and isinstance(node.exc.func, ast.Name)
                and node.exc.func.id == "PlanError"
            ):
                arg = node.exc.args[0]
                parts = arg.values if isinstance(arg, ast.JoinedStr) else [arg]
                text = "".join(
                    p.value if isinstance(p, ast.Constant) and isinstance(p.value, str) else "\x00"
                    for p in parts
                )
                found.append(text)
    return found


def test_every_plan_error_is_covered() -> None:
    import re

    messages = _plan_error_messages()
    assert len(messages) >= 25
    for message in messages:
        if any(message.startswith(start) for start in UNREACHABLE):
            continue
        pieces = [p for p in message.split("\x00") if len(p.strip()) > 3]
        covered = [
            r.id
            for r in REFUSALS
            if any(re.search(re.escape(p.strip()), _example(r)) for p in pieces)
        ]
        assert covered, f"no REFUSALS case for: raise PlanError({message!r})"


def _example(refusal: Refusal) -> str:
    job, source, kwargs = refusal.build()
    try:
        build_plan(job, source, c7.caps(libplacebo=False), c7.tools(), **kwargs)
    except PlanError as exc:
        return str(exc)
    return ""  # pragma: no cover - test_plan_errors_are_validation_errors fails first


def _composite_parts() -> list[tuple[str, str, str | None]]:
    """The parts of composite x26x parameters (``deblock=-1,-1``) of the shipped encoders,
    with every speed preset and none."""
    cases: list[tuple[str, str, str | None]] = []
    for encoder in DEFS.video_encoders.values():
        presets = [None, *(c.value for c in encoder.presets.choices)] if encoder.presets else [None]
        for option in encoder.options:
            if option.mapping.kind == "x26x_param" and option.mapping.part is not None:
                cases += [(encoder.id, option.key, preset) for preset in presets]
    return cases


@pytest.mark.parametrize(("encoder", "key", "preset"), _composite_parts())
def test_composite_parts_have_defaults(encoder: str, key: str, preset: str | None) -> None:
    """The ``option … has no default to complete …`` refusal cannot happen with the shipped
    definitions: one part of a composite parameter set alone, with any speed preset, is
    completed from the other parts' defaults."""
    src = c7.recorded("multitrack.mkv")
    job = c7.draft(src, video={"encoder": encoder, "preset": preset, "advanced": {key: 1}})
    build_plan(job, src, c7.caps(), c7.tools())


#: Snapshot jobs that test the builder with a value validation refuses on purpose:
#: job → the error codes it has.
KNOWN_ERRORS: dict[str, set[str]] = {}


def test_snapshot_jobs_are_imported() -> None:
    assert len(snapshots.CASES) >= 40


@pytest.mark.parametrize("name", sorted(snapshots.CASES))
def test_snapshot_jobs_validate_without_errors(name: str) -> None:
    job, source, caps, tools, kwargs = snapshots.CASES[name]()
    found = errors(run_validation(job, source, caps, tools, **kwargs))
    assert {i.code for i in found} <= KNOWN_ERRORS.get(name, set()), [
        (i.code, i.path, i.message) for i in found
    ]
