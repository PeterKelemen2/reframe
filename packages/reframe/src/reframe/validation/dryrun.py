"""The dry run of a job: FFmpeg encodes one frame, and what the encoder refuses becomes issues.

The dry run is async and not a registered rule, since it runs FFmpeg. x264, x265, SVT-AV1 and
libvpx's codec controls go on without a refused parameter and exit 0, so the log line is what
reports it.
"""

from __future__ import annotations

import asyncio
import re
import shutil
import tempfile
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from reframe.capabilities.reasons import informative_line, normalise_line
from reframe.command import PlanError, build_plan
from reframe.definitions import Definitions, EncoderOption, VideoEncoderDef, load_definitions
from reframe.definitions.custom_params import CustomParam, split_custom_params
from reframe.definitions.search import cli_name
from reframe.jsonpatch import parse_pointer
from reframe.models.capabilities import CapabilitySnapshot
from reframe.models.issues import Fix, Severity, ValidationIssue
from reframe.models.job import AverageBitrate, JobSettings
from reframe.models.media import MediaSource
from reframe.models.plan import resolve_argv
from reframe.models.tools import ToolSet
from reframe.tools import CancelToken, run
from reframe.validation.common import error, warning
from reframe.validation.fs import has_nul
from reframe.validation.video import (
    remove_option_fix,
    remove_param_fix,
    video_custom_param_issues,
    video_option_rule_issues,
)

__all__ = [
    "DRY_RUN_CODES",
    "DRY_RUN_TIMEOUT",
    "dry_run",
    "dry_run_argv",
    "dry_run_job",
    "failure_detail",
    "parse_dry_run",
]

#: Seconds before the dry run is stopped (one frame; a hardware encoder needs a moment to
#: start).
DRY_RUN_TIMEOUT = 30.0
_MAX_OUTPUT = 256 * 1024

DRY_RUN_CODES = (
    "encoder.custom_param_rejected",
    "encoder.option_rejected",
    "encoder.dry_run_failed",
    "encoder.dry_run_warning",
    "encoder.dry_run_skipped",
)

# ``+level`` tags each line with its level: x264's warnings through FFmpeg have no other mark.
# The ``+`` keeps FFmpeg's other log flags (``level+info`` would stop folding repeated lines).
_LOG_LEVEL = ("-loglevel", "+level+info")


def dry_run_job(job: JobSettings) -> JobSettings:
    """The job the dry run encodes: only the video (no audio, subtitles, chapters or tags),
    one pass, no fast start, and an output path when naming has not set one (it is replaced
    by ``-f null -``)."""
    probe = job.model_copy(deep=True)
    probe.audio = []
    probe.subtitles = []
    probe.chapters.enabled = False
    probe.chapters.names = None
    probe.chapters.generate_every = None
    probe.output.web_optimized = False
    rc = probe.video.rate_control
    if isinstance(rc, AverageBitrate) and rc.two_pass:
        probe.video.rate_control = rc.model_copy(update={"two_pass": False})
    if probe.output.path is None:
        probe.output.path = Path(f"dry-run.{probe.output.container}")
    return probe


def dry_run_argv(
    job: JobSettings,
    source: MediaSource,
    caps: CapabilitySnapshot,
    tools: ToolSet,
    *,
    definitions: Definitions | None = None,
) -> list[str]:
    """The FFmpeg arguments (without the program) of the dry run. Pure; raises
    :class:`~reframe.command.PlanError` when the job cannot be planned."""
    probe = dry_run_job(job)
    plan = build_plan(probe, source, caps, tools, definitions=definitions)
    step = next((s for s in plan.steps if s.kind == "encode"), None)
    if step is None:  # pragma: no cover - a one-pass video job always has an encode step
        raise PlanError("the plan has no encode step")
    argv = resolve_argv(step.argv, {})
    output = str(plan.output_tmp)
    if len(argv) < 3 or argv[-1] != output or argv[-3] != "-f":  # pragma: no cover
        raise PlanError("the encode step does not end with its output")
    return [*_LOG_LEVEL, *argv[:-3], "-frames:v", "1", "-f", "null", "-"]


# The log lines that name a refused parameter, per encoder (recorded in testdata/README.md).
_PARAM_PROBLEMS: tuple[re.Pattern[str], ...] = (
    re.compile(r"Error parsing option '(?P<name>[^=']+?)\s*=\s*(?P<value>[^']*)'"),
    re.compile(r"Error parsing option (?P<name>[^:\s]+): (?P<value>.*?)\.?$"),
    re.compile(r"Unknown option: (?P<name>\S+?)\.?$"),
    re.compile(r"Invalid value for (?P<name>[^:\s]+): (?P<value>.*?)\.?$"),
    re.compile(r"Unrecognized option '(?P<name>[^']+)'"),
    re.compile(r"Error setting option (?P<name>\S+) to value (?P<value>.*?)\.?$"),
)
# libvpx refuses a codec control with exit code 0; the next line has the detail.
_CODEC_CONTROL = re.compile(r"Failed to set (?P<ctrl>\w+) codec control")
#: libvpx controls whose FFmpeg option has another name (FFmpeg's libvpxenc.c).
_CONTROL_OPTIONS = {
    "CPUUSED": "cpu-used",
    "CQ_LEVEL": "crf",
    "ENABLEAUTOALTREF": "auto-alt-ref",
    "FRAME_PARALLEL_DECODING": "frame-parallel",
    "MAX_INTRA_BITRATE_PCT": "max-intra-rate",
    "STATIC_THRESHOLD": "static-thresh",
    "TARGET_LEVEL": "level",
    "TUNING": "tune",
}
_ADDITIONAL = "Additional information:"
#: The level tag of ``-loglevel +level``, after the line's log contexts.
_LEVEL_TAG = re.compile(
    r"^(?P<contexts>(?:\[[^\]]* @ [^\]]*\] )*)"
    r"\[(?P<level>panic|fatal|error|warning|info|verbose|debug|trace)\] "
)
_ERROR_LEVELS = frozenset({"error", "fatal", "panic"})
# x265 and SVT-AV1 write these lines themselves, without FFmpeg's level tag.
_ENCODER_WARNING = re.compile(r"^(?:x26[45] \[warning\]:|Svt\[warn\]:)\s*(?P<text>.*)$")
_ENCODER_ERROR = re.compile(r"^(?:x26[45] \[error\]:|Svt\[error\]:)\s*(?P<text>.*)$")
# The AMF runtime writes its own lines: ``<time> <thread> [<component>] Error: <file>(<n>):<text>``.
_AMF_ERROR = re.compile(r"\[(?P<component>AMF\w*)\]\s+Error:\s*(?:[^\s(]+\(\d+\):)?(?P<text>.*)$")
_FAILURE_WORDS = re.compile(
    r"error|fail|invalid|cannot|could not|must|not supported|out of range|unsupported", re.I
)
_START_FAILED = re.compile(
    r"Error while opening encoder|Could not open encoder|Nothing was written into output file"
    r"|Failed to initialize encoder|Cannot open libx26[45] encoder|Conversion failed"
)


#: A whole key in a log line: not inside a longer word or key, but after ``--`` (x265 writes
#: ``--rd-refine``).
_WHOLE = r"(?:(?<=--)|(?<![\w-])){}(?![\w-])"


def _norm(name: str) -> str:
    """``bogus:v:0`` → ``bogus``; ``-b_ref_mode`` → ``b-ref-mode`` (``_`` and ``-`` alike)."""
    return name.strip().lstrip("-").split(":", 1)[0].replace("_", "-").casefold()


def control_names(control: str) -> list[str]:
    """The option names of a libvpx codec control: ``VP8E_SET_ARNR_MAXFRAMES`` →
    ``arnr-maxframes``, ``VP8E_SET_CPUUSED`` → ``cpu-used`` (and ``cpuused``)."""
    base = re.sub(r"^VP[89]E_SET_", "", control)
    names = [base.lower().replace("_", "-")]
    other = _CONTROL_OPTIONS.get(base)
    return [other, *names] if other is not None else names


def failure_detail(stderr: str, encoder_id: str) -> str | None:
    """The line that says best why a dry run failed: the encoder library's own error (x265,
    SVT-AV1, the AMF runtime), else a failure line the encoder logged that is not a warning
    (with libvpx's ``Additional information`` appended), else the encoder's first line at the
    error level, else :func:`~reframe.capabilities.reasons.informative_line`. Without tags and
    addresses."""
    lines = _log_lines(stderr)
    for _level, raw in lines:
        match = _ENCODER_ERROR.match(raw)
        if match is not None:
            return match["text"].strip()
        amf = _AMF_ERROR.search(raw)
        if amf is not None:
            return f"{amf['component']}: {amf['text'].strip()}"
    tag = f"[{encoder_id} @"
    tagged = [(level, _strip_tag(raw)) for level, raw in lines if raw.startswith(tag)]
    info = "Additional information:"
    extra = next((t.removeprefix(info).strip() for _, t in tagged if t.startswith(info)), None)
    for level, text in tagged:
        # AMF warns "VBAQ is not supported by cqp …, automatically disabled" before any failure.
        if level != "warning" and _FAILURE_WORDS.search(text) and not text.startswith(info):
            return f"{text} ({extra})" if extra else text
    for level, text in tagged:
        if level in _ERROR_LEVELS and not text.startswith(info):
            return f"{text} ({extra})" if extra else text
    line = informative_line(_untagged(stderr), encoder_id)
    return _strip_tag(line) if line is not None else None


def _strip_tag(line: str) -> str:
    """``[libx265 @ 0x…] Unknown option: x.`` → ``Unknown option: x.``."""
    text = normalise_line(line)
    return re.sub(r"^(?:\[[^\]]+\]\s*)+", "", text).strip()


def _untag(line: str) -> tuple[str | None, str]:
    """``[libx264 @ 0x…] [warning] text`` → ``("warning", "[libx264 @ 0x…] text")``. The level
    is ``None`` on a line without a tag (the second line of a message)."""
    match = _LEVEL_TAG.match(line)
    if match is None:
        return None, line
    return match["level"], match["contexts"] + line[match.end() :]


def _log_lines(stderr: str) -> list[tuple[str | None, str]]:
    """The non-empty lines of ``stderr`` as ``(level, line without the level tag)``."""
    lines = (_untag(raw.strip()) for raw in stderr.splitlines())
    return [(level, line.strip()) for level, line in lines if line.strip()]


def _untagged(stderr: str) -> str:
    """``stderr`` as FFmpeg writes it without ``+level`` (indented lines stay indented)."""
    return "\n".join(_untag(raw)[1] for raw in stderr.splitlines())


def _warning_text(level: str | None, line: str, encoder_id: str) -> str | None:
    """The text of a warning of the encoder: x265's and SVT-AV1's own lines, or a line the
    encoder logs through FFmpeg at the warning level (x264, libvpx, the hardware encoders)."""
    text = _strip_tag(line)
    own = _ENCODER_WARNING.match(text)
    if own is not None:
        return own["text"]
    if level == "warning" and line.startswith(f"[{encoder_id} @"):
        return text
    return None


def _covered(known: Sequence[ValidationIssue]) -> set[str]:
    """The fields that ``known`` is about: each issue's path and the fields its fixes change."""
    paths = {issue.path for issue in known}
    for issue in known:
        for one in issue.fixes:
            paths.update(".".join(parse_pointer(op.path)) for op in one.patch)
    return paths


@dataclass(frozen=True, slots=True)
class _Target:
    path: str
    code: str
    fixes: tuple[Fix, ...]


class _Attribution:
    """Which field of the job a parameter name belongs to."""

    def __init__(self, job: JobSettings, encoder: VideoEncoderDef | None) -> None:
        self.job = job
        self.params = split_custom_params(job.video.custom_params)
        self.options: dict[str, EncoderOption] = {}
        if encoder is not None:
            for key in job.video.advanced:
                option = encoder.option(key)
                if option is not None:
                    self.options[key] = option

    def names(self) -> list[tuple[str, _Target]]:
        found = [(_norm(p.name), self._param_target(p)) for p in self.params]
        for key, option in self.options.items():
            target = self._option_target(key)
            found.append((_norm(key), target))
            found.append((_norm(cli_name(option)), target))
        return found

    def _param_target(self, param: CustomParam) -> _Target:
        return _Target(
            "video.custom_params",
            "encoder.custom_param_rejected",
            (remove_param_fix(self.params, param),),
        )

    def _option_target(self, key: str) -> _Target:
        return _Target(
            f"video.advanced.{key}",
            "encoder.option_rejected",
            (remove_option_fix(key, f"Reset {key} to its default"),),
        )

    def target(self, name: str) -> _Target | None:
        wanted = _norm(name)
        # Custom parameters first: they are appended last, so they win on the command line.
        for param in self.params:
            if _norm(param.name) == wanted:
                return self._param_target(param)
        for key, option in self.options.items():
            if wanted in (_norm(key), _norm(cli_name(option))):
                return self._option_target(key)
        return None

    def mentioned(self, text: str) -> _Target | None:
        """The job parameter that ``text`` names, matched as a whole key. A key as typed (``_``
        and ``-`` alike) is tried before a looser form (any case, words separated by spaces);
        within each form the match that starts first wins, then the longest."""
        best: tuple[tuple[int, int, int], _Target] | None = None
        for name, target in self.names():
            if not name:
                continue
            parts = [re.escape(part) for part in name.split("-")]
            forms = (
                re.compile(_WHOLE.format("[-_]".join(parts))),
                re.compile(_WHOLE.format("[-_ ]".join(parts)), re.IGNORECASE),
            )
            for tier, pattern in enumerate(forms):
                match = pattern.search(text)
                if match is None:
                    continue
                rank = (tier, match.start(), -len(match.group(0)))
                if best is None or rank < best[0]:
                    best = (rank, target)
                break
        return best[1] if best is not None else None

    def fallback_path(self) -> str:
        if self.params:
            return "video.custom_params"
        if self.options:
            return "video.advanced"
        return "video.encoder"


def parse_dry_run(
    job: JobSettings,
    stderr: str,
    returncode: int | None,
    *,
    encoder: VideoEncoderDef | None = None,
    known: Sequence[ValidationIssue] = (),
) -> list[ValidationIssue]:
    """The issues of a finished dry run (``stderr`` and the exit code of FFmpeg). ``encoder``
    defaults to the job's encoder in the packaged definitions. ``known``: validation's issues;
    a warning about a field they are about (an issue's path, or a field its fix changes) is
    left out. Pure."""
    if encoder is None:
        encoder = load_definitions().video_encoders.get(job.video.encoder)
    encoder_id = encoder.id if encoder is not None else job.video.encoder
    who = _Attribution(job, encoder)
    issues: list[ValidationIssue] = []
    seen: set[tuple[str, str]] = set()

    def add(issue: ValidationIssue) -> None:
        key = (issue.code, issue.path)
        if key not in seen:
            seen.add(key)
            issues.append(issue)

    entries = _log_lines(stderr)
    lines = [line for _level, line in entries]
    for index, (level, raw) in enumerate(entries):
        text = _strip_tag(raw)
        control = _CODEC_CONTROL.search(text)
        if control is not None:
            following = _strip_tag(lines[index + 1]) if index + 1 < len(lines) else ""
            detail = f"{text} ({following})" if following.startswith(_ADDITIONAL) else text
            names = control_names(control["ctrl"])
            target = next((t for n in names if (t := who.target(n)) is not None), None)
            if target is None:
                add(
                    error(
                        "encoder.dry_run_failed",
                        who.fallback_path(),
                        f"The encoder refused a value and went on without it: {detail}",
                    )
                )
            else:
                add(
                    error(
                        target.code,
                        target.path,
                        f"The encoder refused {names[0]!r} and went on without it: {detail}",
                        *target.fixes,
                    )
                )
            continue
        for pattern in _PARAM_PROBLEMS:
            match = pattern.search(text)
            if match is None:
                continue
            name = match["name"]
            target = who.target(name)
            if target is None:
                path = who.fallback_path()
                add(error("encoder.dry_run_failed", path, f"FFmpeg refused {name!r}: {text}"))
            else:
                add(
                    error(
                        target.code,
                        target.path,
                        f"FFmpeg refused {name!r}: {text}",
                        *target.fixes,
                    )
                )
            break
        else:
            warned = _warning_text(level, raw, encoder_id)
            if warned is not None:
                target = who.mentioned(warned)
                if target is not None:
                    add(
                        warning(
                            "encoder.dry_run_warning",
                            target.path,
                            f"The encoder changed a setting: {warned}",
                            *target.fixes,
                        )
                    )
    failed = returncode != 0 or any(_START_FAILED.search(line) for line in lines)
    if failed and not any(i.severity is Severity.ERROR for i in issues):
        detail = failure_detail(stderr, encoder_id) or f"exit code {returncode}"
        target = who.mentioned(detail)
        if target is not None:
            add(
                error(
                    target.code,
                    target.path,
                    f"The test encode of one frame failed: {detail}",
                    *target.fixes,
                )
            )
        else:
            add(
                error(
                    "encoder.dry_run_failed",
                    who.fallback_path(),
                    f"The test encode of one frame failed: {detail}",
                )
            )
    # A warning about a field that already has an error, or that validation reports, says
    # nothing new.
    quiet = {i.path for i in issues if i.severity is Severity.ERROR} | _covered(known)
    return [i for i in issues if i.severity is Severity.ERROR or i.path not in quiet]


async def dry_run(
    job: JobSettings,
    source: MediaSource,
    caps: CapabilitySnapshot,
    tools: ToolSet,
    *,
    definitions: Definitions | None = None,
    cancel: CancelToken | None = None,
    work_dir: Path | None = None,
) -> list[ValidationIssue]:
    """Encode one frame with the job's video settings, and turn what FFmpeg refuses into
    ``error`` issues at the path of the field (``video.custom_params``, ``video.advanced.<key>``).
    The caller validates first; a job with errors is not dry-run. An encoder warning about a
    field that validation's option rules already report is left out. A passthrough job and a
    cancelled run give ``[]``.

    Custom parameters that name a file, or that FFmpeg would read as its own options, are
    validation's errors (:func:`~reframe.validation.video.video_custom_param_issues`): they are
    returned, and FFmpeg does not start. The temporary working folder is made in ``work_dir``
    (default: the system's temporary folder)."""
    defs = definitions if definitions is not None else load_definitions()
    if job.video.passthrough:
        return []
    refused = video_custom_param_issues(job.video, caps, defs)
    if refused:
        return refused
    if not job.source.path.is_absolute():  # FFmpeg runs in another folder
        job = job.model_copy(
            update={"source": job.source.model_copy(update={"path": job.source.path.absolute()})}
        )
    ffmpeg = tools.ffmpeg
    if not ffmpeg.usable:
        return [
            warning(
                "encoder.dry_run_skipped",
                "video.encoder",
                "The test encode did not run: FFmpeg was not found.",
            )
        ]
    try:
        argv = dry_run_argv(job, source, caps, tools, definitions=defs)
    except PlanError as exc:
        return [
            error(
                "encoder.dry_run_failed",
                "video.encoder",
                f"The test encode cannot be built: {exc}.",
            )
        ]
    if any(has_nul(arg) for arg in argv):
        # A NUL in the source path (only the API can send one): no process can take it, and
        # ``reframe.tools.run`` raises ``ValueError``.
        nul_source = has_nul(job.source.path) or has_nul(source.ref.path)
        what = "the source path" if nul_source else "a value of the job"
        return [
            warning(
                "encoder.dry_run_skipped",
                "video.encoder",
                f"The test encode did not run: {what} has a NUL character, which no file "
                "system allows.",
            )
        ]
    # An encoder writes its own files (statistics, csv) into the working folder.
    folder = Path(
        await asyncio.to_thread(tempfile.mkdtemp, prefix="reframe-dry-run-", dir=work_dir)
    )
    try:
        result = await run(
            [str(ffmpeg.path), *argv],
            timeout=DRY_RUN_TIMEOUT,
            cancel=cancel,
            max_output=_MAX_OUTPUT,
            cwd=folder,
        )
    finally:
        await asyncio.to_thread(shutil.rmtree, folder, True)
    if result.cancelled:
        return []
    if not result.started:
        return [
            warning(
                "encoder.dry_run_skipped",
                "video.encoder",
                f"The test encode did not run: {result.error}.",
            )
        ]
    if result.timed_out:
        return [
            warning(
                "encoder.dry_run_skipped",
                "video.encoder",
                f"The test encode did not finish within {DRY_RUN_TIMEOUT:g} s.",
            )
        ]
    encoder = defs.video_encoders.get(job.video.encoder)
    known = video_option_rule_issues(job.video, caps, defs)
    return parse_dry_run(job, result.stderr_text, result.returncode, encoder=encoder, known=known)
