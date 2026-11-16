"""Scenarios for the validation tests: a clean job, a fake file system, the fix check and the
rule cases."""

from __future__ import annotations

import copy
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field, replace
from pathlib import Path, PurePath
from typing import Any

from reframe.definitions import Definitions, load_definitions
from reframe.jsonpatch import apply_patch
from reframe.models import (
    AppSettings,
    AudioOutputTrack,
    AudioStream,
    BitrateInfo,
    BitrateSource,
    CapabilitySnapshot,
    Chapter,
    ContainerInfo,
    CropSettings,
    DimensionSettings,
    EncoderState,
    EncoderStatus,
    Fix,
    JobSettings,
    JobTemplate,
    MediaSource,
    NamingOptions,
    OutputSettings,
    Rational,
    RemoveOp,
    Severity,
    SourceRef,
    SubtitleOutputTrack,
    SubtitleStream,
    ToolInfo,
    ToolSet,
    ToolStatus,
    ValidationIssue,
    VideoSettings,
    VideoStream,
)
from reframe.naming import FileTimes
from reframe.textfile import TextCharset
from reframe.validation import validate, validate_template

DEFS = load_definitions()
UTF8 = TextCharset("UTF-8", ascii=False)
SOURCE = Path("/media/movies/Movie.2019.1080p.BluRay.mkv")
OUTPUT = Path("/out/Movie (2019).mkv")
GB = 1_000_000_000


class FakeFs:
    """Files (with sizes) and folders in memory. Paths of one flavour (POSIX or Windows);
    ``case_insensitive`` compares them case-insensitively, as NTFS and APFS do."""

    def __init__(
        self,
        files: Iterable[PurePath] = (),
        dirs: Iterable[PurePath] = (),
        *,
        readonly: Iterable[PurePath] = (),
        free: int | None = 1000 * GB,
        case_insensitive: bool = False,
    ) -> None:
        self.case_insensitive = case_insensitive
        self.files: dict[str, PurePath] = {}
        self.charsets: dict[str, TextCharset] = {}
        self.dirs: dict[str, PurePath] = {}
        self.readonly = {self._key(p) for p in readonly}
        self.free = free
        for path in dirs:
            self.add_dir(path)
        for path in files:
            self.add_file(path)

    def _key(self, path: PurePath) -> str:
        text = str(path)
        return text.casefold() if self.case_insensitive else text

    def add_dir(self, path: PurePath) -> None:
        for part in [path, *path.parents]:
            self.dirs[self._key(part)] = part

    def add_file(self, path: PurePath, charset: TextCharset = UTF8) -> None:
        self.add_dir(path.parent)
        self.files[self._key(path)] = path
        self.charsets[self._key(path)] = charset

    def exists(self, path: PurePath) -> bool:
        key = self._key(path)
        return key in self.files or key in self.dirs

    def is_dir(self, path: PurePath) -> bool:
        return self._key(path) in self.dirs

    def writable_dir(self, path: PurePath) -> bool:
        return self.is_dir(path) and self._key(path) not in self.readonly

    def writable_file(self, path: PurePath) -> bool:
        key = self._key(path)
        return key in self.files and key not in self.readonly

    def free_bytes(self, path: PurePath) -> int | None:
        return self.free if self.exists(path) else None

    def same_file(self, a: PurePath, b: PurePath) -> bool:
        return self.exists(a) and self.exists(b) and self._key(a) == self._key(b)

    def list_files(self, folder: Path) -> list[str] | None:
        if not self.is_dir(folder):
            return None
        key = self._key(folder)
        return sorted(p.name for p in self.files.values() if self._key(p.parent) == key)

    def file_times(self, file: Path) -> FileTimes | None:
        return None

    def text_charset(self, path: PurePath) -> TextCharset | None:
        return self.charsets.get(self._key(path))


def make_source(path: Path = SOURCE) -> MediaSource:
    return MediaSource(
        ref=SourceRef(path=path),
        container=ContainerInfo(
            format_name="matroska,webm", duration=600.0, size=6 * GB, display_name="MKV"
        ),
        video=[
            VideoStream(
                index=0,
                codec="h264",
                width=1920,
                height=1080,
                pix_fmt="yuv420p",
                bit_depth=8,
                frame_rate=Rational(num=24000, den=1001),
                avg_frame_rate=Rational(num=24000, den=1001),
                bitrate=BitrateInfo(value=8_000_000, source=BitrateSource.STREAM),
            )
        ],
        audio=[
            AudioStream(
                index=1,
                type_index=0,
                codec="ac3",
                display_codec="AC-3",
                channels=6,
                channel_layout="5.1(side)",
                sample_rate=48000,
                language="eng",
                bitrate=BitrateInfo(value=640_000, source=BitrateSource.STREAM),
            ),
            AudioStream(
                index=2,
                type_index=1,
                codec="aac",
                display_codec="AAC-LC",
                channels=2,
                channel_layout="stereo",
                sample_rate=48000,
                language="eng",
                bitrate=BitrateInfo(value=128_000, source=BitrateSource.STREAM),
            ),
        ],
        subtitles=[
            SubtitleStream(index=3, type_index=0, codec="subrip", display_codec="SRT"),
            SubtitleStream(
                index=4,
                type_index=1,
                codec="hdmv_pgs_subtitle",
                display_codec="PGS",
                subtitle_kind="bitmap",
            ),
        ],
        chapters=[
            Chapter(index=0, start=0.0, end=300.0, title="One"),
            Chapter(index=1, start=300.0, end=600.0, title="Two"),
        ],
    )


def make_job(source: MediaSource) -> JobSettings:
    """A job with no issues."""
    return JobSettings(
        source=source.ref,
        output=OutputSettings(container="mkv", path=OUTPUT),
        dimensions=DimensionSettings(crop=CropSettings(mode="none")),
        video=VideoSettings(encoder="libx265"),
        audio=[
            AudioOutputTrack(
                source_stream=1, action="encode", encoder="aac", mixdown="stereo", bitrate=160
            ),
            AudioOutputTrack(source_stream=2, action="passthru", encoder="aac"),
        ],
        subtitles=[
            SubtitleOutputTrack(source=3, action="copy"),
            SubtitleOutputTrack(source=4, action="copy"),
        ],
    )


def make_caps(
    states: dict[str, EncoderState | EncoderStatus] | None = None,
    *,
    filters: list[str] | None = None,
) -> CapabilitySnapshot:
    """Every encoder and filter of the definitions available, unless ``states`` or ``filters``
    says otherwise."""
    states = states or {}
    encoders: dict[str, EncoderStatus] = {}
    for encoder_id in [*DEFS.video_encoders, *DEFS.audio_encoders]:
        value = states.get(encoder_id, EncoderState.AVAILABLE)
        if isinstance(value, EncoderStatus):
            encoders[encoder_id] = value
        else:
            encoders[encoder_id] = EncoderStatus(
                id=encoder_id,
                state=value,
                in_build=value is not EncoderState.UNKNOWN,
                hardware=encoder_id in DEFS.video_encoders
                and DEFS.video_encoders[encoder_id].hardware,
                reason=None if value is EncoderState.AVAILABLE else "No device found",
            )
    if filters is None:
        filters = sorted(
            {
                name
                for definition in DEFS.filters.values()
                for impl in definition.implementations
                for name in impl.filters
            }
        )
    return CapabilitySnapshot(encoders=encoders, filters=filters)


def tool(name: str, status: ToolStatus = ToolStatus.FOUND, **extra: Any) -> ToolInfo:
    path = Path(f"/usr/bin/{name}")
    return ToolInfo(name=name, status=status, path=path, **extra)  # type: ignore[arg-type]


def make_tools(**overrides: ToolInfo) -> ToolSet:
    tools = {name: tool(name) for name in ("ffmpeg", "ffprobe")}
    tools.update(overrides)
    return ToolSet(**tools)


def make_fs() -> FakeFs:
    return FakeFs(files=[SOURCE], dirs=[Path("/out")])


@dataclass
class Scenario:
    """Everything ``validate`` takes. Tests change a fresh one (``base()``) and validate."""

    source: MediaSource
    job: JobSettings
    caps: CapabilitySnapshot = field(default_factory=make_caps)
    tools: ToolSet = field(default_factory=make_tools)
    fs: FakeFs = field(default_factory=make_fs)
    settings: AppSettings = field(default_factory=AppSettings)
    definitions: Definitions = field(default_factory=lambda: DEFS)
    naming: NamingOptions | None = None
    rediscover: Callable[[AppSettings], ToolSet] | None = None
    """Tool discovery for ``settings`` fixes of tool issues."""

    def validate(self) -> list[ValidationIssue]:
        return validate(
            self.job,
            self.source,
            self.caps,
            self.tools,
            self.fs,
            settings=self.settings,
            definitions=self.definitions,
            naming=self.naming,
        )

    def apply(self, fix: Fix) -> Scenario:
        """A copy with ``fix`` applied to its target document."""
        if fix.target == "job":
            data = apply_patch(self.job.model_dump(mode="json"), fix.patch)
            return replace(self, job=JobSettings.model_validate(data))
        assert fix.target == "settings", fix
        data = apply_patch(self.settings.model_dump(mode="json"), fix.patch)
        settings = AppSettings.model_validate(data)
        tools = self.rediscover(settings) if self.rediscover is not None else self.tools
        return replace(self, settings=settings, tools=tools)


def base() -> Scenario:
    source = make_source()
    return Scenario(source=source, job=make_job(source))


def found(issues: Iterable[ValidationIssue], code: str, path: str | None = None) -> bool:
    return any(i.code == code and (path is None or i.path == path) for i in issues)


def error_codes(issues: Iterable[ValidationIssue]) -> set[str]:
    return {i.code for i in issues if i.severity is Severity.ERROR}


def check_fix(
    issue: ValidationIssue, fix: Fix, before: list[ValidationIssue], after: list[ValidationIssue]
) -> None:
    """The fix removed its issue (same code and path) and added no new error: by code and
    path, or by code only when the fix removes something (a removed track renumbers the
    paths of the others)."""
    assert not found(after, issue.code, issue.path), (
        f"fix {fix.label!r} of {issue.code} at {issue.path!r} did not remove it",
        [i for i in after if i.code == issue.code],
    )
    if any(isinstance(op, RemoveOp) for op in fix.patch):
        added = error_codes(after) - error_codes(before)
    else:
        old = {(i.code, i.path) for i in before if i.severity is Severity.ERROR}
        added = {i.code for i in after if i.severity is Severity.ERROR} & {
            i.code for i in after if (i.code, i.path) not in old and i.severity is Severity.ERROR
        }
    assert not added, (
        f"fix {fix.label!r} of {issue.code} at {issue.path!r} added an error",
        [i for i in after if i.code in added],
    )
    FIXES_CHECKED.append((issue.code, fix.label))


def check(scenario: Scenario) -> list[ValidationIssue]:
    """Validate, then apply every fix of every issue and validate again: the issue (same code
    and path) must be gone, and no new error may appear."""
    issues = scenario.validate()
    assert not found(issues, "validation.rule_failed"), issues
    for issue in issues:
        for fix in issue.fixes:
            check_fix(issue, fix, issues, scenario.apply(fix).validate())
    return issues


#: Every (code, fix label) that :func:`check` applied, for the coverage assertion.
FIXES_CHECKED: list[tuple[str, str]] = []


@dataclass
class TemplateScenario:
    template: JobTemplate
    caps: CapabilitySnapshot = field(default_factory=make_caps)
    definitions: Definitions = field(default_factory=lambda: DEFS)
    subject: str | None = None

    def validate(self) -> list[ValidationIssue]:
        return validate_template(
            self.template, self.caps, subject=self.subject, definitions=self.definitions
        )

    def apply(self, fix: Fix) -> TemplateScenario:
        assert fix.target == "template", fix
        data = apply_patch(self.template.model_dump(mode="json"), fix.patch)
        return replace(self, template=type(self.template).model_validate(data))


def check_template(scenario: TemplateScenario) -> list[ValidationIssue]:
    issues = scenario.validate()
    assert not found(issues, "validation.rule_failed"), issues
    for issue in issues:
        for fix in issue.fixes:
            check_fix(issue, fix, issues, scenario.apply(fix).validate())
    return issues


def deep(scenario: Scenario) -> Scenario:
    return copy.deepcopy(scenario)


type Mod = Callable[[Any], None]


@dataclass(frozen=True)
class Case:
    id: str
    code: str
    path: str
    severity: Severity
    positive: Mod
    negative: Mod


def both(*mods: Mod) -> Mod:
    def mod(s: Any) -> None:
        for m in mods:
            m(s)

    return mod
