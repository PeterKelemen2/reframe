"""Command-line entry point (``reframe``, C-15). Needs the ``[cli]`` extra (typer; rich comes
with it).

Commands:

- ``reframe probe FILE [--json]``: every track of a file (M1).
- ``reframe encoders [--json]``: the encoder statuses: the cached result at once (or
  "checking…" without a cache), then each status that detection changes, then a summary.
- ``reframe plan FILE [--preset NAME] [-o OUT] [--json]``: the job drafted from the preset,
  its issues (errors, warnings, info, with their fixes), then the FFmpeg command.
- ``reframe encode FILE|DIR… [--preset NAME] [-o OUT] [-r]``: one job per media file
  (decision 0018), queued and run with progress and ETA. Ctrl+C cancels the jobs.
- ``reframe name PATH… [--template T] [--preset NAME] [--json]``: the name source and why,
  the parsed fields and the output name of each path.
- ``reframe tools status [--json]``: which ffmpeg / ffprobe / mkvpropedit / mediainfo is used
  (the lines of ``python -m reframe.tools``) and the fetched build.
- ``reframe tools fetch [--build NAME] [--platform P]``: the pinned FFmpeg build of the
  manifest, checked and installed as the bundled build in ``<data dir>/tools/ffmpeg``.
- ``reframe presets list [--json]``, ``reframe presets export [NAME…] [-o FILE]``,
  ``reframe presets import FILE [--on-conflict rename|replace|skip]``.
- ``reframe version``.

``plan`` runs the one-frame dry run when the job has custom encoder parameters; ``encode``
shows the when-done countdown (sleep, shut down) that the queue starts after its jobs, and
Ctrl+C cancels it. Decision 0038.

No ``--preset``: the default preset (Settings, else *H.265 MKV 1080p*, decision 0024). Output
formats, exit codes and the other CLI choices: decision 0017.

Exit codes:

- ``0``: success (``plan``: no validation errors; ``encode``: every job done).
- ``1``: failure: ffprobe could not read the file (``probe``, ``plan``); the job has
  validation errors (``plan``); a job failed, was cancelled or was not queued (``encode``);
  a name has errors (``name``).
- ``2``: wrong command-line usage: typer/click errors, an unknown preset, ``-o`` with more
  than one file, a template with errors (``name --template``).
- ``3``: a file or folder does not exist, is not a file, or cannot be read; no media files
  in the given folders (``encode``).
- ``4``: no usable ffprobe (``probe``, ``plan``) or ffmpeg (``encoders``); ffmpeg or ffprobe
  cannot be used (``tools status``).
- ``130``: interrupted (Ctrl+C). ``encode`` first cancels its running and waiting jobs
  through the queue, which removes their partial files, or the when-done countdown;
  ``tools fetch`` stops the download and installs nothing.

``tools fetch``: ``1`` the download, the checksum, the archive or the version check failed;
``2`` an unknown build or a platform the build has no archive for. ``presets export``: ``1``
FILE cannot be written; ``2`` an unknown preset. ``presets import``: ``1`` the file is not a
preset file or a preset was not imported (an ``error`` issue); ``3`` FILE does not exist or
cannot be read.

Errors are one line on stderr, never a traceback (an unexpected error is one ``error:`` line
and exit code 1; ``REFRAME_TRACEBACK=1`` shows the traceback). The core's warnings
(``app.warning``: a damaged settings file, a queue store used by another process, …) are
``warning:`` lines on stderr. ``--json`` prints only JSON on stdout. The
human output uses rich: no colour when stdout is not a terminal or ``NO_COLOR`` is set, ASCII
table borders when stdout cannot encode box-drawing characters, and characters that stdout
cannot encode are replaced (never a ``UnicodeEncodeError``).
"""

from __future__ import annotations

import asyncio
import difflib
import io
import json
import logging
import os
import sys
import tempfile
import time
from collections.abc import AsyncIterator, Coroutine, Iterable, Sequence
from contextlib import asynccontextmanager
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Any, Protocol

from pydantic import BaseModel

from reframe import __version__, languages
from reframe.events import Subscription
from reframe.jobs import find_media_files, has_errors
from reframe.mediatask import TaskFailed
from reframe.models.capabilities import CapabilitySnapshot, EncoderState, EncoderStatus
from reframe.models.draft import JobDraft
from reframe.models.events import (
    AppWarningEvent,
    CapabilitiesChangedEvent,
    JobProgressEvent,
    JobStateEvent,
    PowerCountdownEvent,
    ResyncEvent,
    TaskDoneEvent,
    TaskProgressEvent,
)
from reframe.models.issues import Severity, ValidationIssue
from reframe.models.job import JobSettings
from reframe.models.media import (
    AudioStream,
    BitrateInfo,
    BitrateSource,
    ColorInfo,
    Disposition,
    FieldOrder,
    HdrFormat,
    HdrInfo,
    MediaSource,
    RoleEvidence,
    SubtitleStream,
    TrackRoleInfo,
    VideoStream,
)
from reframe.models.naming import NameResult
from reframe.models.plan import EncodePlan
from reframe.models.preset import Preset
from reframe.models.queue import JobProgress, JobState, QueueJob
from reframe.models.tasks import TaskInfo, TaskState
from reframe.models.tools import ToolFetchResult, ToolInfo, ToolName, ToolOrigin, ToolSet
from reframe.presets import ConflictPolicy, ImportResult
from reframe.service import ProbeError, ProbeErrorKind, Reframe, tool_usable
from reframe.tools.__main__ import status_lines
from reframe.tools.fetch import (
    PLATFORMS,
    FetchError,
    host_platform,
    install_dir_for,
    installed_build,
    load_manifest,
)

try:  # the [cli] extra; main() says so when it is missing
    import typer
    from rich import box
    from rich.console import Console
    from rich.live import Live
    from rich.progress import BarColumn, Progress, TaskID, TextColumn
    from rich.table import Table
    from rich.text import Text
except ImportError:  # pragma: no cover - depends on the installed extras
    _CLI_EXTRA = False
else:
    _CLI_EXTRA = True
    #: ``--preset NAME`` of ``plan``, ``encode`` and ``name``.
    _PresetOption = Annotated[
        str | None,
        typer.Option(
            "--preset",
            "-p",
            metavar="NAME",
            help="Preset name or id (without case). Default: the default preset.",
        ),
    ]
    #: ``-o OUT`` of ``plan`` and ``encode``.
    _OutputOption = Annotated[
        Path | None,
        typer.Option(
            "--output",
            "-o",
            metavar="OUT",
            help="Output file (manual name; without an extension the container's is added), "
            "or an existing folder for the template name. Only with a single file.",
        ),
    ]

__all__ = [
    "EXIT_FAILED",
    "EXIT_INTERRUPTED",
    "EXIT_NOT_FOUND",
    "EXIT_NO_FFPROBE",
    "EXIT_NO_TOOL",
    "EXIT_OK",
    "EXIT_PROBE_FAILED",
    "EXIT_USAGE",
    "QueueLike",
    "build_app",
    "get_queue",
    "main",
]

EXIT_OK = 0
EXIT_PROBE_FAILED = 1
#: The same code for every command: something failed (see the module doc).
EXIT_FAILED = 1
EXIT_USAGE = 2
EXIT_NOT_FOUND = 3
EXIT_NO_FFPROBE = 4
#: ``reframe encoders`` without a usable ffmpeg.
EXIT_NO_TOOL = 4
#: 128 + SIGINT, what shells report for a Ctrl+C.
EXIT_INTERRUPTED = 130
#: Set to ``1`` to get the traceback of an unexpected error instead of one ``error:`` line.
TRACEBACK_ENV = "REFRAME_TRACEBACK"

_EXIT_HELP = (
    "Exit codes: 0 probed; 1 ffprobe could not read the file; 2 usage error; "
    "3 file missing or unreadable; 4 no usable ffprobe."
)

_EXIT_HELP_ENCODERS = "Exit codes: 0 done; 4 no usable ffmpeg; 130 interrupted (Ctrl+C)."
_EXIT_HELP_PLAN = (
    "Exit codes: 0 the command is printed; 1 the job has errors, or ffprobe could not read the "
    "file; 2 usage error or unknown preset; 3 file missing or unreadable; 4 no usable ffprobe."
)
_EXIT_HELP_ENCODE = (
    "Exit codes: 0 every job done; 1 a job failed, was cancelled or was not queued; 2 usage "
    "error, unknown preset, or -o with several files; 3 a path does not exist, or no media "
    "files; 130 interrupted (Ctrl+C: the jobs are cancelled first)."
)
_EXIT_HELP_NAME = "Exit codes: 0 named; 1 a name has errors; 2 usage error or a bad template."

_EXIT_BY_KIND = {
    ProbeErrorKind.NOT_FOUND: EXIT_NOT_FOUND,
    ProbeErrorKind.NOT_A_FILE: EXIT_NOT_FOUND,
    ProbeErrorKind.UNREADABLE: EXIT_NOT_FOUND,
    ProbeErrorKind.TOOL_FAILED: EXIT_NO_FFPROBE,
}

# --------------------------------------------------------------------------- plain formatting

#: The dash for "no value".
NONE = "—"
#: Between width and height (03 §Summary).
TIMES = "\N{MULTIPLICATION SIGN}"

_BITRATE_SOURCE = {
    BitrateSource.STREAM: "stream",
    BitrateSource.STATS_TAG: "stats tag",
    BitrateSource.MEDIAINFO: "MediaInfo",
    BitrateSource.MEASURED: "measured",
    BitrateSource.UNKNOWN: "unknown",
}

_HDR_NAMES = {
    HdrFormat.HDR10: "HDR10",
    HdrFormat.HDR10_PLUS: "HDR10+",
    HdrFormat.HLG: "HLG",
    HdrFormat.DOLBY_VISION: "Dolby Vision",
}

_PRIMARIES = {
    "bt709": "BT.709",
    "bt2020": "BT.2020",
    "smpte170m": "BT.601 NTSC",
    "bt470bg": "BT.601 PAL",
    "bt470m": "BT.470 M",
    "smpte240m": "SMPTE 240M",
    "smpte431": "DCI-P3",
    "smpte432": "Display P3",
    "film": "Film",
}

_SCAN = {
    FieldOrder.PROGRESSIVE: "progressive",
    FieldOrder.TOP_FIRST: "interlaced TFF",
    FieldOrder.BOTTOM_FIRST: "interlaced BFF",
}

_TRANSFERS = {
    "smpte2084": "PQ",
    "arib-std-b67": "HLG",
    "bt709": "BT.709",
    "smpte170m": "BT.601",
    "bt470bg": "BT.601",
    "bt2020-10": "BT.2020",
    "bt2020-12": "BT.2020",
    "iec61966-2-1": "sRGB",
    "linear": "linear",
}

#: Disposition flags in display order, with their labels (``attached_pic`` is never shown:
#: cover art is listed separately).
_FLAGS: tuple[tuple[str, str], ...] = (
    ("default", "default"),
    ("forced", "forced"),
    ("hearing_impaired", "hearing impaired"),
    ("visual_impaired", "visual impaired"),
    ("original", "original"),
    ("comment", "commentary"),
    ("dub", "dub"),
    ("descriptions", "descriptions"),
    ("captions", "captions"),
    ("clean_effects", "clean effects"),
    ("lyrics", "lyrics"),
    ("karaoke", "karaoke"),
    ("non_diegetic", "non-diegetic"),
    ("metadata", "metadata"),
    ("dependent", "dependent"),
    ("still_image", "still image"),
    ("timed_thumbnails", "timed thumbnails"),
    ("multilayer", "multilayer"),
)

_ROLE_NAMES = {
    "main": "Main",
    "commentary": "Commentary",
    "description": "Audio description",
    "music": "Music only",
    "sdh": "SDH",
    "forced": "Forced",
    "signs": "Signs & Songs",
}

ROLE_LEGEND = "[Role] = set by a flag in the file; (Role?) = guessed from the title or layout."


def fmt_int(value: int) -> str:
    """``3912345`` → ``3 912 345`` (space as the thousands separator, as in 03)."""
    return f"{value:,}".replace(",", " ")


def fmt_bps(bps: int) -> str:
    """Bits per second as ``kb/s``: ``2104000`` → ``2 104 kb/s``, ``1500`` → ``1.5 kb/s``."""
    kbps = bps / 1000
    if kbps < 10:
        return f"{kbps:.1f} kb/s".replace(".0 ", " ")
    return f"{fmt_int(round(kbps))} kb/s"


def fmt_bitrate(info: BitrateInfo) -> str:
    """``2 104 kb/s (stats tag)``, ``— (unknown)``."""
    if info.value is None:
        return f"{NONE} (unknown)"
    return f"{fmt_bps(info.value)} ({_BITRATE_SOURCE[info.source]})"


def fmt_duration(seconds: float | None) -> str:
    """``5025.5`` → ``1:23:45.500``; ``None`` → ``—``."""
    if seconds is None:
        return NONE
    millis = round(seconds * 1000)
    hours, rest = divmod(millis, 3_600_000)
    minutes, rest = divmod(rest, 60_000)
    secs, millis = divmod(rest, 1000)
    return f"{hours}:{minutes:02d}:{secs:02d}.{millis:03d}"


def fmt_size(size: int | None) -> str:
    """``378781`` → ``369.9 KiB (378 781 bytes)``."""
    if size is None:
        return NONE
    if size < 1024:
        return f"{size} bytes"
    value = float(size)
    for unit in ("KiB", "MiB", "GiB", "TiB"):
        value /= 1024
        if value < 1024 or unit == "TiB":
            break
    return f"{value:.1f} {unit} ({fmt_int(size)} bytes)"


def fmt_number(value: float, places: int = 3) -> str:
    """``23.976023`` → ``23.976``, ``25.0`` → ``25``."""
    return f"{value:.{places}f}".rstrip("0").rstrip(".")


def fmt_sample(rate: int | None, depth: int | None) -> str:
    """``48 kHz / 24-bit``, ``44.1 kHz``, ``—``."""
    parts = []
    if rate is not None:
        parts.append(f"{fmt_number(rate / 1000, 1)} kHz")
    if depth is not None:
        parts.append(f"{depth}-bit")
    return " / ".join(parts) or NONE


def fmt_channels(stream: AudioStream) -> str:
    """``5.1(side), 6 ch``; ``2 ch`` when there is no layout."""
    count = f"{stream.channels} ch"
    return f"{stream.channel_layout}, {count}" if stream.channel_layout else count


def fmt_language(tag: str | None) -> str:
    """``jpn Japanese``; ``—`` when the track has no language tag."""
    if not tag:
        return NONE
    if languages.normalize(tag) is None:
        return f"{tag} (unknown code)"
    return f"{tag} {languages.english_name(tag)}"


def fmt_flags(disposition: Disposition) -> list[str]:
    """The set disposition flags, as labels: ``["default", "hearing impaired"]``."""
    return [label for name, label in _FLAGS if getattr(disposition, name)]


def fmt_hdr(hdr: HdrInfo | None) -> str:
    """``HDR10``, ``HDR10+``, ``Dolby Vision 8.1 + HDR10``, ``SDR``."""
    if hdr is None or not hdr.formats:
        return "SDR"
    names = []
    for fmt in hdr.formats:
        name = _HDR_NAMES[fmt]
        dovi = hdr.dolby_vision
        if fmt is HdrFormat.DOLBY_VISION and dovi is not None:
            name += f" {dovi.profile}"
            if dovi.bl_signal_compatibility_id:
                name += f".{dovi.bl_signal_compatibility_id}"
        names.append(name)
    return " + ".join(names)


def fmt_color(color: ColorInfo) -> str | None:
    """``BT.2020 PQ``, ``BT.2020 HLG``, ``BT.709``; ``None`` when nothing is tagged."""
    parts = []
    primaries = _PRIMARIES.get(color.primaries or "", color.primaries)
    if primaries:
        parts.append(primaries)
    transfer = _TRANSFERS.get(color.transfer or "", color.transfer)
    if transfer and transfer not in parts:
        parts.append(transfer)
    return " ".join(parts) or None


def video_line(stream: VideoStream) -> str:
    """03 §Summary: ``HEVC Main 10 · 3840×2160 · 23.976 fps · HDR10 · BT.2020 PQ``."""  # noqa: RUF002
    parts = [stream.display_codec or stream.codec or "unknown codec"]
    parts.append(f"{stream.width}{TIMES}{stream.height}")
    avg, base = stream.avg_frame_rate, stream.frame_rate
    if not stream.vfr:
        rate = avg or base
        if rate is not None and rate.num > 0:
            parts.append(f"{fmt_number(float(rate))} fps")
    elif avg is not None and avg.num > 0:
        parts.append(f"{fmt_number(float(avg))} fps average (VFR)")
    elif base is not None and base.num > 0:
        parts.append(f"VFR (base {fmt_number(float(base))} fps)")
    else:
        parts.append("VFR")
    parts.append(fmt_hdr(stream.hdr))
    color = fmt_color(stream.color)
    if color:
        parts.append(color)
    return " · ".join(parts)


def video_details(stream: VideoStream) -> str:
    """The second video line: depth, pixel format, scan, aspect, light levels, bit rate."""
    parts = []
    if stream.bit_depth:
        parts.append(f"{stream.bit_depth}-bit {stream.pix_fmt or ''}".strip())
    elif stream.pix_fmt:
        parts.append(stream.pix_fmt)
    scan = _SCAN.get(stream.field_order)
    if scan:
        parts.append(scan)
    if stream.sar is not None:
        parts.append(f"SAR {stream.sar.num}:{stream.sar.den}")
    if stream.dar is not None:
        parts.append(f"DAR {stream.dar.num}:{stream.dar.den}")
    if stream.vfr and stream.frame_rate is not None and stream.avg_frame_rate is not None:
        # The base rate when the line shows the average (else the line shows the base).
        parts.append(f"base rate {fmt_number(float(stream.frame_rate))} fps")
    if stream.rotation:
        parts.append(f"rotated {stream.rotation}°")
    hdr = stream.hdr
    if hdr is not None and hdr.mastering_display is not None:
        md = hdr.mastering_display
        parts.append(
            f"mastering {fmt_number(md.min_luminance, 4)}-{fmt_number(md.max_luminance)} cd/m²"
        )
    if hdr is not None and hdr.content_light is not None:
        cll = hdr.content_light
        parts.append(f"MaxCLL {cll.max_cll} / MaxFALL {cll.max_fall}")
    if stream.closed_captions:
        parts.append("closed captions")
    parts.append(f"bitrate {fmt_bitrate(stream.bitrate)}")
    if stream.language:
        parts.append(f"lang {fmt_language(stream.language)}")
    if stream.title:
        parts.append(f'"{stream.title}"')
    flags = fmt_flags(stream.disposition)
    if flags:
        parts.append(f"flags: {', '.join(flags)}")
    return " · ".join(parts)


def role_badge(role: TrackRoleInfo) -> str:
    """``[Commentary]`` when a disposition flag sets the role, ``(Commentary?)`` when a title
    keyword or the track layout suggests it (03: solid vs outlined badge)."""
    name = _ROLE_NAMES.get(role.role.value, role.role.value)
    return f"[{name}]" if role.evidence is RoleEvidence.FLAG else f"({name}?)"


def fmt_events(stream: SubtitleStream) -> str:
    """``212 (stats tag)``, ``8 (3 forced)``, ``— (unknown)``."""
    if stream.event_count is None:
        return f"{NONE} (unknown)"
    text = fmt_int(stream.event_count)
    notes = []
    if stream.event_count_source is not None:
        notes.append(stream.event_count_source.replace("_", " "))
    if stream.forced_event_count is not None:
        notes.append(f"{stream.forced_event_count} forced")
    return f"{text} ({', '.join(notes)})" if notes else text


def origin_text(info: ToolInfo) -> str:
    """Where a tool path came from, for messages: ``REFRAME_FFPROBE``, ``PATH``, …"""
    if info.origin is ToolOrigin.ENV:
        where = f"set by {info.env_var}"
    elif info.origin is ToolOrigin.SETTINGS:
        where = "set in Settings > Tools"
    elif info.origin is ToolOrigin.BUNDLED:
        where = "bundled build"
    elif info.origin is ToolOrigin.PATH:
        where = "found on PATH"
    else:
        where = "not found anywhere"
    if info.next_to_ffmpeg:
        where += ", next to ffmpeg"
    return f"{where}: {info.path}" if info.path is not None else where


def printable(text: str) -> str:
    """``text`` with the bytes of a file name that is not valid UTF-8 (``os.fsdecode`` keeps
    them as lone surrogates, U+DCFF) shown as U+FFFD: such a string cannot be
    written to a UTF-8 stream."""
    try:
        return text.encode("utf-8", "surrogateescape").decode("utf-8", "replace")
    except UnicodeEncodeError:  # other lone surrogates (a broken UTF-16 name on Windows)
        return text.encode("utf-8", "replace").decode("utf-8")


def display_path(path: Path | str) -> str:
    """A path for the human output (:func:`printable`)."""
    return printable(str(path))


def _one_line(text: str) -> str:
    return " ".join(printable(text).split())


def error_message(error: ProbeError, ffprobe: ToolInfo | None) -> str:
    """The one-line error for a failed probe."""
    if error.kind is ProbeErrorKind.TOOL_FAILED and ffprobe is not None:
        if not tool_usable(ffprobe):
            reason = ffprobe.reason or "no reason given"
            return _one_line(
                f"error: ffprobe is not usable ({ffprobe.status.value}, {origin_text(ffprobe)}): "
                f"{reason}"
            )
        return _one_line(
            f"error: ffprobe ({origin_text(ffprobe)}) could not be started: "
            f"{error.detail or error.message}"
        )
    message = f"error: {error.path}: {error.message}"
    if error.detail:
        message += f" ({error.detail})"
    return _one_line(message)


# --------------------------------------------------------------------------- rich rendering

#: Indent of the lines under a section title.
_INDENT = 2


def _text(value: str | None, style: str = "") -> Text:
    return Text(value if value else NONE, style=style)


def _badges(roles: Sequence[TrackRoleInfo]) -> Text:
    badges = Text()
    for i, role in enumerate(roles):
        if i:
            badges.append(" ")
        solid = role.evidence is RoleEvidence.FLAG
        badges.append(role_badge(role), style="bold cyan" if solid else "cyan")
    return badges


def _roles_cell(
    roles: Sequence[TrackRoleInfo], disposition: Disposition, extra: Iterable[str] = ()
) -> Text:
    """The "Role & flags" cell: the badges, then the set flags (and the audio delay)."""
    lines = [_badges(roles)] if roles else []
    items = [*fmt_flags(disposition), *extra]
    if items:
        lines.append(Text(", ".join(items), style="yellow"))
    return Text("\n").join(lines)


def _table(columns: Sequence[str]) -> Table:
    table = Table(box=box.SQUARE, show_lines=True, header_style="bold")
    for name in columns:
        table.add_column(name, justify="right" if name == "#" else "left", overflow="fold")
    return table


def _audio_table(streams: Sequence[AudioStream]) -> Table:
    table = _table(
        ("#", "Lang", "Name", "Codec", "Channels", "Rate / depth", "Bitrate", "Role & flags")
    )
    for s in streams:
        codec = _text(s.display_codec or s.codec, "bold")
        if s.lossless:
            codec.append(" lossless", style="dim")
        delay = (
            [f"delay {round(s.delay * 1000):+d} ms"] if s.delay and round(s.delay * 1000) else []
        )
        table.add_row(
            _text(str(s.index)),
            _text(fmt_language(s.language)),
            _text(s.title),
            codec,
            _text(fmt_channels(s)),
            _text(fmt_sample(s.sample_rate, s.bit_depth)),
            _text(fmt_bitrate(s.bitrate)),
            _roles_cell(s.roles, s.disposition, delay),
        )
    return table


def _subtitle_table(streams: Sequence[SubtitleStream]) -> Table:
    table = _table(("#", "Lang", "Name", "Format", "Type", "Events", "Role & flags"))
    for s in streams:
        kind: str = s.subtitle_kind
        if s.width and s.height:
            kind += f" {s.width}{TIMES}{s.height}"
        table.add_row(
            _text(str(s.index)),
            _text(fmt_language(s.language)),
            _text(s.title),
            _text(s.display_codec or s.codec, "bold"),
            _text(kind),
            _text(fmt_events(s)),
            _roles_cell(s.roles, s.disposition),
        )
    return table


def _evidence_lines(streams: Sequence[AudioStream | SubtitleStream]) -> list[Text]:
    """``#3  [Commentary]  disposition comment``: the tooltip of each badge (03)."""
    lines = []
    for s in streams:
        for role in s.roles:
            line = Text(f"#{s.index}  ")
            line.append_text(_badges([role]))
            line.append(f"  {role.detail or role.evidence.value}", style="dim")
            lines.append(line)
    return lines


def _plural(count: int, word: str) -> str:
    return f"{count} {word}" if count == 1 else f"{count} {word}s"


def _indented(console: Console, line: Text, indent: int = _INDENT, first: str = "") -> None:
    """Print ``line`` indented by ``indent`` spaces after the prefix ``first`` (which replaces
    the indent on the first line). Wrapped parts keep the indent; no trailing spaces."""
    lead = max(indent, len(first))
    width = max(console.width - lead, 20)
    for i, part in enumerate(line.wrap(console, width, overflow="fold")):
        part.rstrip()
        prefix = Text(first.ljust(lead) if i == 0 and first else " " * lead, style="dim")
        console.print(prefix + part, overflow="fold", soft_wrap=True)


def _section(console: Console, title: str) -> None:
    console.print()
    console.print(Text(title, style="bold"))


def render_source(source: MediaSource, console: Console) -> None:
    """Print the human form of ``reframe probe``."""
    c = source.container
    console.print(Text(display_path(source.ref.path.name), style="bold"))
    container = c.display_name or c.format_name or NONE
    if c.format_long_name:
        container += f" ({c.format_long_name})"
    counts = [
        _plural(len(source.video), "video track"),
        _plural(len(source.audio), "audio track"),
        _plural(len(source.subtitles), "subtitle track"),
        _plural(len(source.attachments), "attachment"),
    ]
    rows = [
        ("Path", str(source.ref.path)),
        ("Container", container),
        ("Title", c.title),
        ("Duration", fmt_duration(c.duration)),
        ("Size", fmt_size(c.size)),
        ("Bitrate", fmt_bps(c.bitrate) if c.bitrate is not None else NONE),
        ("Tracks", " · ".join(counts)),
        ("Chapters", str(len(source.chapters))),
        ("Probed by", f"ffprobe {source.probe_tool}" if source.probe_tool else None),
    ]
    for key, value in rows:
        if value is not None:
            _indented(console, Text(value), first=f"{'':{_INDENT}}{key:<10} ")

    _section(console, f"Video ({len(source.video)})")
    if not source.video:
        _indented(console, Text(NONE))
    for v in source.video:
        _indented(console, Text.assemble(f"#{v.index}  ", (video_line(v), "bold")))
        _indented(console, Text(video_details(v), style="dim"), _INDENT + 4)

    _section(console, f"Audio ({len(source.audio)})")
    if source.audio:
        console.print(_audio_table(source.audio))
    _section(console, f"Subtitles ({len(source.subtitles)})")
    if source.subtitles:
        console.print(_subtitle_table(source.subtitles))

    evidence = _evidence_lines([*source.audio, *source.subtitles])
    if evidence:
        _section(console, "Role evidence")
        for line in evidence:
            _indented(console, line)
        _indented(console, Text(ROLE_LEGEND, style="dim"))

    _print_list(
        console,
        f"Attachments ({len(source.attachments)})",
        [
            f"#{a.index}  {a.filename or NONE} · {a.mimetype or a.codec or NONE} · "
            f"{fmt_size(a.size).split(' (')[0]}"
            for a in source.attachments
        ],
    )
    _print_list(
        console,
        f"Cover art ({len(source.cover_art)})",
        [
            f"#{p.index}  {(p.codec or NONE).upper()}"
            + (f" {p.width}{TIMES}{p.height}" if p.width and p.height else "")
            + (f" · {p.filename}" if p.filename else "")
            for p in source.cover_art
        ],
    )
    _print_list(
        console,
        f"Data streams ({len(source.data)})",
        [
            f"#{d.index}  {d.codec or d.codec_tag or NONE}" + (f" · {d.title}" if d.title else "")
            for d in source.data
        ],
    )
    _print_list(
        console,
        f"Chapters ({len(source.chapters)})",
        [
            f"{ch.index + 1:>2}  {fmt_duration(ch.start)}  {ch.title or NONE}"
            for ch in source.chapters
        ],
        limit=CHAPTER_LIMIT,
    )
    _print_list(console, f"Warnings ({len(source.warnings)})", source.warnings, style="yellow")


#: Chapters listed by ``reframe probe`` (the rest is counted).
CHAPTER_LIMIT = 50


def _print_list(
    console: Console, title: str, items: Sequence[str], *, limit: int = 0, style: str = ""
) -> None:
    if not items:
        return
    _section(console, title)
    shown = items[:limit] if limit else items
    for item in shown:
        _indented(console, Text(item, style=style))
    if len(items) > len(shown):
        _indented(console, Text(f"… and {len(items) - len(shown)} more", style="dim"))


# --------------------------------------------------------------------------- commands


def _write_json(source: MediaSource) -> None:
    """``model_dump_json(indent=2)`` on stdout. If stdout cannot encode every character, the
    JSON is written with ``\\uXXXX`` escapes instead (same value, valid JSON)."""
    text = source.model_dump_json(indent=2)
    encoding = (getattr(sys.stdout, "encoding", None) or "utf-8").lower().replace("_", "-")
    if encoding not in ("utf-8", "utf8"):
        text = json.dumps(json.loads(text), indent=2, ensure_ascii=True)
    sys.stdout.write(text + "\n")
    sys.stdout.flush()


async def run_probe(file: Path, *, as_json: bool) -> int:
    """``reframe probe``: probe ``file``, print it, return the exit code."""
    async with open_reframe() as app:
        outcome = await app.sources.probe(file)
        if isinstance(outcome, ProbeError):
            ffprobe = None
            if outcome.kind is ProbeErrorKind.TOOL_FAILED:
                ffprobe = (await app.tools.status()).ffprobe
            print(error_message(outcome, ffprobe), file=sys.stderr)
            return _EXIT_BY_KIND.get(outcome.kind, EXIT_PROBE_FAILED)
    if as_json:
        _write_json(outcome)
    else:
        render_source(outcome, make_console())
    return EXIT_OK


#: Width for the human output when neither stdout, stdin nor stderr is a terminal and
#: ``COLUMNS`` is not set (CI logs, ``subprocess``): wider than rich's 80, so that the tables
#: do not wrap.
DEFAULT_PIPE_WIDTH = 120


def make_console() -> Console:
    """The console for the human output. rich decides colour (none when stdout is not a
    terminal or ``NO_COLOR`` is set) and the box style (ASCII when stdout is not UTF-8).

    rich's legacy Windows console mode (no VT support) is used only when stdout is a
    terminal: for a pipe it would only make the lines one column shorter.
    """
    width = None
    if not os.environ.get("COLUMNS", "").strip() and not any(_isatty(fd) for fd in (0, 1, 2)):
        width = DEFAULT_PIPE_WIDTH
    stdout_isatty = getattr(sys.stdout, "isatty", None)
    legacy = None if callable(stdout_isatty) and stdout_isatty() else False
    return Console(highlight=False, emoji=False, width=width, legacy_windows=legacy)


def _isatty(fd: int) -> bool:
    try:
        return os.isatty(fd)
    except OSError:  # pragma: no cover - a closed standard stream
        return False


# --------------------------------------------------------------------------- shared helpers


def _error(message: str) -> None:
    """One ``error:`` line on stderr."""
    print(_one_line(f"error: {message}"), file=sys.stderr)


class WarningPrinter:
    """Prints the core's ``app.warning`` events as ``warning: <message> (<detail>)`` lines on
    stderr: the start-up problems that the settings and presets services keep (published
    before anyone could subscribe), then every event until Reframe is closed. Each warning
    is printed once."""

    def __init__(self, app: Reframe) -> None:
        self._seen: set[tuple[str, str, str | None]] = set()
        self._subscription = app.events.subscribe(types={"app.warning"})
        for problem in [*app.settings.problems, *app.presets.problems]:
            self.show(problem)
        self._task = asyncio.get_running_loop().create_task(self._consume())

    def show(self, warning: AppWarningEvent) -> None:
        key = (warning.code, warning.message, warning.detail)
        if key in self._seen:
            return
        self._seen.add(key)
        detail = f" ({warning.detail})" if warning.detail else ""
        print(_one_line(f"warning: {warning.message}{detail}"), file=sys.stderr)

    async def _consume(self) -> None:
        async for event in self._subscription:
            if isinstance(event, AppWarningEvent):
                self.show(event)

    async def finish(self) -> None:
        """After ``Reframe.close()``: print what is still queued, then stop."""
        try:
            async with asyncio.timeout(5):
                await asyncio.shield(self._task)
        except TimeoutError:  # pragma: no cover - the bus was not closed
            self._subscription.close()
            self._task.cancel()


@asynccontextmanager
async def open_reframe() -> AsyncIterator[Reframe]:
    """``Reframe.create()`` for a command, with its warnings printed (:class:`WarningPrinter`)
    also those published while it closes."""
    app = await Reframe.create()
    printer = WarningPrinter(app)
    try:
        yield app
    finally:
        try:
            await app.close()
        finally:
            await printer.finish()


def _write_model_json(value: BaseModel | Sequence[BaseModel] | dict[str, BaseModel | None]) -> None:
    """Models as JSON on stdout (``\\uXXXX`` escapes when stdout is not UTF-8)."""
    if isinstance(value, BaseModel):
        data: object = value.model_dump(mode="json")
    elif isinstance(value, dict):
        data = {k: None if v is None else v.model_dump(mode="json") for k, v in value.items()}
    else:
        data = [item.model_dump(mode="json") for item in value]
    encoding = (getattr(sys.stdout, "encoding", None) or "utf-8").lower().replace("_", "-")
    text = json.dumps(data, indent=2, ensure_ascii=encoding not in ("utf-8", "utf8"))
    try:
        text.encode("utf-8")
    except UnicodeEncodeError:  # a file name that is not valid UTF-8: \udcff escapes
        text = json.dumps(data, indent=2, ensure_ascii=True)
    sys.stdout.write(text + "\n")
    sys.stdout.flush()


def find_preset(app: Reframe, name: str | None) -> Preset | str:
    """The preset named ``name`` (id or name, without case), the default preset for ``None``,
    else the error message (with the closest names)."""
    if name is None:
        return app.presets.default()
    found = app.presets.find(name)
    if found is not None:
        return found
    names = [preset.name for preset in app.presets.list()]
    by_folded = {n.casefold(): n for n in names}
    close = difflib.get_close_matches(name.casefold(), list(by_folded), n=3, cutoff=0.5)
    message = f'there is no preset named "{name}".'
    if close:
        return message + " Did you mean " + " or ".join(f'"{by_folded[c]}"' for c in close) + "?"
    return message + " Presets: " + ", ".join(f'"{n}"' for n in names) + "."


def fmt_clock(seconds: float | None) -> str:
    """``83.4`` → ``0:01:23``; ``None`` → ``—``."""
    if seconds is None:
        return NONE
    whole = round(seconds)
    hours, rest = divmod(whole, 3600)
    minutes, secs = divmod(rest, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}"


def fmt_bytes(size: int | None) -> str:
    """``12_900_000`` → ``12.3 MiB`` (no byte count)."""
    return fmt_size(size).split(" (")[0]


_SEVERITY_STYLE = {Severity.ERROR: "bold red", Severity.WARNING: "yellow", Severity.INFO: "cyan"}
_SEVERITY_ORDER = {Severity.ERROR: 0, Severity.WARNING: 1, Severity.INFO: 2}


def issue_counts(issues: Sequence[ValidationIssue]) -> str:
    """``1 error, 0 warnings, 2 info``."""
    count = {s: sum(1 for i in issues if i.severity is s) for s in Severity}
    return (
        f"{_plural(count[Severity.ERROR], 'error')}, "
        f"{_plural(count[Severity.WARNING], 'warning')}, {count[Severity.INFO]} info"
    )


def render_issues(
    console: Console,
    issues: Sequence[ValidationIssue],
    *,
    severities: Iterable[Severity] = tuple(Severity),
    indent: int = _INDENT,
) -> None:
    """Each issue: ``error    <message>``, then ``[code · path]`` and one ``fix:`` line per
    fix, errors first (03 §Validation and error display)."""
    wanted = set(severities)
    shown = sorted(
        (issue for issue in issues if issue.severity in wanted),
        key=lambda issue: _SEVERITY_ORDER[issue.severity],
    )
    lead = indent + 9
    for issue in shown:
        label = f"{'':{indent}}{issue.severity.value:<8} "
        line = Text(printable(issue.message))
        _labelled(console, label, _SEVERITY_STYLE[issue.severity], line, lead)
        where = issue.code + (f" · {issue.path}" if issue.path else "")
        _indented(console, Text(f"[{where}]", style="dim"), lead)
        for fix in issue.fixes:
            _indented(console, Text(printable(f"fix: {fix.label}"), style="green"), lead)


def _labelled(console: Console, label: str, style: str, line: Text, lead: int) -> None:
    """``line`` after the styled ``label`` (padded to ``lead``); wrapped parts keep the
    indent."""
    width = max(console.width - lead, 20)
    for i, part in enumerate(line.wrap(console, width, overflow="fold")):
        part.rstrip()
        prefix = Text(label.ljust(lead), style=style) if i == 0 else Text(" " * lead)
        console.print(prefix + part, overflow="fold", soft_wrap=True)


# --------------------------------------------------------------------------- encoders


def encoder_text(status: EncoderStatus) -> str:
    """``hevc_nvenc — unavailable: NVIDIA driver not found`` (M2 demo item 1)."""
    state = status.state
    if state is EncoderState.AVAILABLE:
        text = "available"
        extras = []
        if status.device:
            extras.append(status.device)
        if status.hardware and status.supports_10bit is False:
            extras.append("8-bit only")
        if extras:
            text += f" ({', '.join(extras)})"
    elif state is EncoderState.CHECKING:
        text = "checking…"
    elif state is EncoderState.UNKNOWN:
        text = "not tested" + (f": {status.reason}" if status.reason else "")
    elif state is EncoderState.ERROR:
        text = "error: " + (status.reason or "no reason given")
    else:
        text = "unavailable: " + (status.reason or "no reason given")
    return f"{status.id} — {text}"


def _encoder_key(status: EncoderStatus) -> tuple[str, str]:
    return (status.state.value, encoder_text(status))


def _ffmpeg_text(snapshot: CapabilitySnapshot) -> str:
    if snapshot.ffmpeg is None:
        return "ffmpeg"
    version = f" {snapshot.ffmpeg_version}" if snapshot.ffmpeg_version else ""
    return f"ffmpeg{version} ({snapshot.ffmpeg})"


async def run_encoders(*, as_json: bool) -> int:
    """``reframe encoders``: the cached statuses at once, then the changes while detection
    runs, then a summary. Returns the exit code."""
    console = make_console()
    async with open_reframe() as app:
        # Subscribed before the first await: the detection task has not run yet, so no event
        # is missed.
        subscription = app.events.subscribe(types={"capabilities.changed"})
        capabilities = app.capabilities
        started = time.monotonic()
        if as_json:
            subscription.close()
            snapshot = await capabilities.wait()
        else:
            snapshot = await _follow_encoders(console, capabilities, subscription, started)
        tools = await app.tools.status()
    if as_json:
        _write_model_json(snapshot)
    if not tool_usable(tools.ffmpeg):
        _error(
            f"ffmpeg is not usable ({tools.ffmpeg.status.value}, {origin_text(tools.ffmpeg)}): "
            f"{tools.ffmpeg.reason or 'no reason given'}"
        )
        return EXIT_NO_TOOL
    return EXIT_OK


class _CapabilitySource(Protocol):
    @property
    def snapshot(self) -> CapabilitySnapshot: ...

    async def wait(self) -> CapabilitySnapshot: ...


async def _follow_encoders(
    console: Console,
    capabilities: _CapabilitySource,
    subscription: Subscription,
    started: float,
) -> CapabilitySnapshot:
    shown: dict[str, tuple[str, str]] = {}
    cached: dict[str, tuple[str, str]] = {}
    first = True

    def show(status: EncoderStatus) -> None:
        if status.state is EncoderState.CHECKING:
            return
        key = _encoder_key(status)
        if shown.get(status.id) != key:
            shown[status.id] = key
            console.print(Text(encoder_text(status)), soft_wrap=True)

    async with subscription:
        async for event in subscription:
            if not isinstance(event, CapabilitiesChangedEvent):
                continue  # a resync marker: the snapshot below is read again anyway
            snapshot = capabilities.snapshot
            if first:
                first = False
                checking = all(s.state is EncoderState.CHECKING for s in event.encoders)
                if not snapshot.detecting:
                    console.print(Text(f"Encoders of {_ffmpeg_text(snapshot)}:"), soft_wrap=True)
                elif checking:
                    console.print(
                        Text(
                            f"No cached result: checking the encoders of {_ffmpeg_text(snapshot)}…"
                        ),
                        soft_wrap=True,
                    )
                else:
                    when = snapshot.checked_at
                    at = f" of {when.astimezone():%Y-%m-%d %H:%M}" if when is not None else ""
                    console.print(
                        Text(f"Encoders of {_ffmpeg_text(snapshot)} (cached result{at}):"),
                        soft_wrap=True,
                    )
                for status in event.encoders:
                    show(status)
                cached = dict(shown)
                if snapshot.detecting and not checking:
                    console.print(Text("Checking again…", style="dim"), soft_wrap=True)
            else:
                for status in event.encoders:
                    show(status)
            if not capabilities.snapshot.detecting:
                break
    # The detection task stores its result in the cache after the last event: let it finish,
    # or closing Reframe would cancel that write.
    final = await capabilities.wait()
    for status in final.encoders.values():
        show(status)
    states = [s.state for s in final.encoders.values()]
    available = states.count(EncoderState.AVAILABLE)
    changed = sum(1 for key, value in shown.items() if cached.get(key) != value) if cached else 0
    summary = (
        f"Done in {time.monotonic() - started:.1f} s: {available} available, "
        f"{len(states) - available} not available"
    )
    if cached:
        summary += f" ({changed} changed since the cached result)" if changed else " (no changes)"
    console.print(Text(summary + ".", style="bold"), soft_wrap=True)
    return final


# --------------------------------------------------------------------------- plan


def _draft_header(console: Console, draft: JobDraft, source_name: str) -> None:
    job = draft.job
    console.print(Text(display_path(source_name), style="bold"), soft_wrap=True)
    name = draft.naming
    if name.template_kind == "manual":
        how = f"the manual name {name.template}"
    else:
        how = f"template {name.template} on the {name.source} name ({name.reason})"
    rows: list[tuple[str, str]] = [
        ("Preset", job.preset_name or NONE),
        ("Output", display_path(job.output.path) if job.output.path is not None else NONE),
        ("Name", how),
    ]
    rows += [("Note", note) for note in [*draft.notes, *name.notes]]
    rows += [
        ("Audio" if i == 0 else "", f"#{d.source_stream}  {d.reason}")
        for i, d in enumerate(draft.decisions)
    ]
    for key, value in rows:
        _indented(console, Text(printable(value)), _INDENT + 9, first=f"{'':{_INDENT}}{key:<8} ")


def render_plan(console: Console, draft: JobDraft, plan: EncodePlan | None, source: str) -> None:
    """The human output of ``reframe plan``: the draft, the issues, then the command."""
    _draft_header(console, draft, source)
    _section(console, f"Issues ({issue_counts(draft.issues)})")
    render_issues(console, draft.issues)
    if plan is None:
        console.print()
        console.print(Text("No command: the job has errors.", style="bold red"), soft_wrap=True)
        return
    _section(console, f"Command ({plan.job_type}, {_plural(len(plan.steps), 'step')})")
    # One line, not wrapped, so that it can be copied into a terminal.
    console.print(Text(printable(plan.display)), soft_wrap=True)


#: The note of ``reframe plan`` when the dry run found nothing wrong.
DRY_RUN_NOTE = "The custom encoder parameters were checked by encoding one frame (dry run)."


def needs_dry_run(job: JobSettings, preset: Preset | None = None) -> bool:
    """``reframe plan`` runs the one-frame dry run (C-6) when the job has custom encoder
    parameters that are used (not with video passthrough): validation cannot check them.

    Not for the unchanged parameters of a built-in preset (decision 0038): Reframe's own
    tests check those against the pinned FFmpeg build, and most built-in x265 / SVT-AV1
    presets have some, so every ``reframe plan`` would encode a frame."""
    video = job.video
    if video.passthrough or not video.custom_params.strip():
        return False
    if preset is not None and preset.built_in:
        unchanged = (preset.video.encoder, preset.video.custom_params)
        return unchanged != (video.encoder, video.custom_params)
    return True


async def run_plan(file: Path, *, preset: str | None, output: Path | None, as_json: bool) -> int:
    """``reframe plan``: draft, validate and plan one file. Returns the exit code."""
    async with open_reframe() as app:
        chosen = find_preset(app, preset)
        if isinstance(chosen, str):
            _error(chosen)
            return EXIT_USAGE
        source = await app.sources.probe(file)
        if isinstance(source, ProbeError):
            return await _probe_failed(app, source)
        draft = await app.jobs.draft(source, chosen, output=output)
        if isinstance(draft, ProbeError):  # pragma: no cover - the source is already probed
            return await _probe_failed(app, draft)
        plan: EncodePlan | None = None
        if not has_errors(draft.issues):
            dry_run = needs_dry_run(draft.job, chosen)
            planned = await app.jobs.plan(draft.job, source, dry_run=dry_run)
            if isinstance(planned, EncodePlan):
                plan = planned
                if dry_run:
                    draft = draft.model_copy(update={"notes": [*draft.notes, DRY_RUN_NOTE]})
            else:  # validation agreed before: these are the dry run's errors (or a bug's)
                draft = draft.model_copy(update={"issues": planned})
    if as_json:
        _write_model_json({"draft": draft, "plan": plan})
    else:
        render_plan(make_console(), draft, plan, source.ref.path.name)
    return EXIT_OK if plan is not None else EXIT_FAILED


async def _probe_failed(app: Reframe, error: ProbeError) -> int:
    ffprobe = None
    if error.kind is ProbeErrorKind.TOOL_FAILED:
        ffprobe = (await app.tools.status()).ffprobe
    print(error_message(error, ffprobe), file=sys.stderr)
    return _EXIT_BY_KIND.get(error.kind, EXIT_PROBE_FAILED)


# --------------------------------------------------------------------------- the queue


class QueueLike(Protocol):
    """The part of C-11's ``QueueService`` (``reframe.queue``, decision 0016) that
    ``reframe encode`` uses; the tests give it a fake with the same contract."""

    async def add(self, job: JobSettings, *, position: int | None = None) -> QueueJob: ...

    def get(self, job_id: str) -> QueueJob | None: ...

    def start(self, *, job_ids: Sequence[str] | None = None) -> None: ...

    async def stop(self) -> None: ...

    async def cancel(self, job_id: str | None = None) -> None: ...

    async def wait(self, job_ids: Sequence[str] | None = None) -> list[QueueJob]: ...

    def log_path(self, job_id: str) -> Path: ...


def get_queue(app: Reframe) -> QueueLike:
    """The queue of ``app`` (``Reframe.queue``, C-11): the one place where the CLI gets it.
    Tests of the CLI's own logic replace it with a fake that follows the same contract."""
    return app.queue


#: States after which a job does not change by itself.
FINAL_STATES = frozenset({JobState.DONE, JobState.FAILED, JobState.CANCELLED, JobState.INTERRUPTED})
#: Seconds ``reframe encode`` waits for its jobs to end after Ctrl+C cancelled them.
CANCEL_WAIT = 30.0
#: Lines mode: a progress line every this many percent of a job …
PROGRESS_STEP = 10.0
#: … or after this many seconds without one.
PROGRESS_INTERVAL = 30.0


def progress_text(progress: JobProgress) -> str:
    """``42.0% · 87.3 fps · 3.64x · ETA 0:01:23 · 12.3 MiB``."""
    parts = [f"{progress.percent:.1f}%"]
    if progress.fps is not None:
        parts.append(f"{progress.fps:.1f} fps")
    if progress.speed is not None:
        parts.append(f"{progress.speed:.2f}x")
    parts.append(f"ETA {fmt_clock(progress.eta)}")
    if progress.output_size is not None:
        parts.append(fmt_bytes(progress.output_size))
    if progress.step_count > 1 and progress.step_kind is not None:
        parts.append(f"step {progress.step + 1}/{progress.step_count} {progress.step_kind}")
    return " · ".join(parts)


class EncodeView:
    """What ``reframe encode`` prints while the jobs run.

    On a terminal: one rich progress bar per running job (percent, fps, speed, ETA, size)
    and a line for each state change. Otherwise (a pipe, a log file): plain lines, a
    progress line every :data:`PROGRESS_STEP` percent or :data:`PROGRESS_INTERVAL` seconds.
    """

    def __init__(
        self, console: Console, labels: dict[str, str], *, live: bool | None = None
    ) -> None:
        self.console = console
        self.labels = labels
        self.live = console.is_terminal if live is None else live
        self._started: dict[str, float] = {}
        self._last: dict[str, tuple[float, float]] = {}
        self._progress: Progress | None = None
        self._tasks: dict[str, TaskID] = {}
        if self.live:
            self._progress = Progress(
                TextColumn("{task.description}"),
                BarColumn(),
                TextColumn("{task.fields[detail]}"),
                console=console,
                transient=True,
            )
            self._progress.start()

    def line(self, text: str, style: str = "") -> None:
        target = self._progress.console if self._progress is not None else self.console
        target.print(Text(printable(text), style=style), soft_wrap=True)

    def state(
        self,
        job_id: str,
        state: JobState,
        *,
        error: str | None = None,
        output: Path | None = None,
        log: Path | None = None,
        previous: JobState | None = None,
    ) -> None:
        label = self.labels.get(job_id)
        if label is None:
            return
        if state is JobState.RUNNING:
            if previous is JobState.PAUSED:
                self.line(f"{label} resumed")
            else:
                self._started[job_id] = time.monotonic()
                self.line(f"{label} running")
            self._add_bar(job_id, label)
            return
        self._remove_bar(job_id)
        took = ""
        if job_id in self._started:
            took = f" in {fmt_clock(time.monotonic() - self._started[job_id])}"
        if state is JobState.DONE:
            where = f": {output}" if output is not None else ""
            self.line(f"{label} done{took}{where}", "green")
        elif state is JobState.FAILED:
            reason = f": {_one_line(error)}" if error else ""
            self.line(f"{label} failed{reason}", "bold red")
            if log is not None:
                self.line(f"{' ' * len(label)} log: {log}", "dim")
        elif state is JobState.CANCELLED:
            self.line(f"{label} cancelled", "yellow")
        elif state is JobState.INTERRUPTED:
            self.line(f"{label} interrupted", "yellow")
        elif state is JobState.PAUSED:
            self.line(f"{label} paused", "yellow")

    def progress(self, job_id: str, progress: JobProgress) -> None:
        label = self.labels.get(job_id)
        if label is None:
            return
        if self._progress is not None:
            task = self._tasks.get(job_id)
            if task is None:
                task = self._add_bar(job_id, label)
            self._progress.update(task, completed=progress.percent, detail=progress_text(progress))
            return
        now = time.monotonic()
        last = self._last.get(job_id)
        if last is not None:
            percent, when = last
            stepped = progress.percent // PROGRESS_STEP > percent // PROGRESS_STEP
            if not stepped and now - when < PROGRESS_INTERVAL:
                return
        self._last[job_id] = (progress.percent, now)
        self.line(f"{label} {progress_text(progress)}", "dim")

    def _add_bar(self, job_id: str, label: str) -> TaskID:
        if self._progress is None:
            return TaskID(-1)
        task = self._tasks.get(job_id)
        if task is None:
            task = self._progress.add_task(label, total=100.0, detail="")
            self._tasks[job_id] = task
        return task

    def _remove_bar(self, job_id: str) -> None:
        task = self._tasks.pop(job_id, None)
        if task is not None and self._progress is not None:
            self._progress.remove_task(task)

    def close(self) -> None:
        if self._progress is not None:
            self._progress.stop()
            self._progress = None


async def run_encode(
    paths: Sequence[Path],
    *,
    preset: str | None,
    output: Path | None,
    recursive: bool = False,
) -> int:
    """``reframe encode``: one job per media file, queued, run, followed. Returns the exit
    code; Ctrl+C (the task is cancelled) cancels the jobs and returns 130."""
    console = make_console()
    async with open_reframe() as app:
        found = await app.jobs.media_files(paths, recursive=recursive)
        for missing in found.missing:
            _error(f"{display_path(missing)}: the file or folder does not exist.")
        if found.missing:
            return EXIT_NOT_FOUND
        for folder in found.empty:
            print(_one_line(f"warning: {folder}: no media files in this folder."), file=sys.stderr)
        if not found.files:
            _error("no media files to encode.")
            return EXIT_NOT_FOUND
        if output is not None and len(found.files) > 1:
            _error(
                f"-o/--output needs a single file, but there are {len(found.files)} media "
                "files: without -o, each output is named by the naming template."
            )
            return EXIT_USAGE
        chosen = find_preset(app, preset)
        if isinstance(chosen, str):
            _error(chosen)
            return EXIT_USAGE
        queue = get_queue(app)
        return await _encode(app, queue, found.files, chosen, output, console)


async def _encode(
    app: Reframe,
    queue: QueueLike,
    files: Sequence[Path],
    preset: Preset,
    output: Path | None,
    console: Console,
) -> int:
    # Subscribed before the queue starts: the when-done countdown begins as the last job ends.
    countdown = app.events.subscribe(types={"power.countdown"})
    try:
        code = await _encode_jobs(app, queue, files, preset, output, console)
        if code == EXIT_INTERRUPTED:
            return code
        stopped = await follow_countdown(app, countdown, console)
        return code if stopped is None else stopped
    finally:
        countdown.close()


async def _encode_jobs(
    app: Reframe,
    queue: QueueLike,
    files: Sequence[Path],
    preset: Preset,
    output: Path | None,
    console: Console,
) -> int:
    subscription = app.events.subscribe(types={"job.state", "job.progress"})
    total = len(files)
    width = len(str(total))
    labels: dict[str, str] = {}
    ids: list[str] = []
    not_queued = 0
    view: EncodeView | None = None
    try:
        console.print(Text(f"Preset: {preset.name}"), soft_wrap=True)
        drafts: list[tuple[str, JobDraft]] = []
        for number, file in enumerate(files, start=1):
            label = f"[{number:>{width}}/{total}]"
            draft = await app.jobs.draft(file, preset, output=output)
            if isinstance(draft, ProbeError):
                not_queued += 1
                console.print(
                    Text(printable(f"{label} {file.name}: not queued"), style="bold red"),
                    soft_wrap=True,
                )
                _indented(
                    console,
                    Text(printable(draft.message + (f" ({draft.detail})" if draft.detail else ""))),
                    9,
                )
                continue
            target = draft.job.output.path
            console.print(
                Text(printable(f"{label} {file.name} → {target if target is not None else NONE}")),
                soft_wrap=True,
            )
            for note in draft.notes:
                _indented(console, Text(printable(f"note: {note}"), style="dim"), 9)
            if has_errors(draft.issues):
                not_queued += 1
                console.print(
                    Text(
                        f"{' ' * len(label)} not queued: {issue_counts(draft.issues)}",
                        style="bold red",
                    ),
                    soft_wrap=True,
                )
                render_issues(
                    console,
                    draft.issues,
                    severities=(Severity.ERROR, Severity.WARNING),
                    indent=len(label) + 1,
                )
                continue
            render_issues(
                console, draft.issues, severities=(Severity.WARNING,), indent=len(label) + 1
            )
            drafts.append((label, draft))
        for position, (label, draft) in enumerate(drafts):
            job = await queue.add(draft.job, position=position)
            ids.append(job.id)
            labels[job.id] = label
            if job.state is JobState.FAILED:
                console.print(
                    Text(f"{label} failed when it was queued:", style="bold red"), soft_wrap=True
                )
                render_issues(
                    console, job.issues, severities=(Severity.ERROR,), indent=len(label) + 1
                )
        if not ids:
            console.print(Text("Nothing to encode.", style="bold red"), soft_wrap=True)
            return EXIT_FAILED
        console.print(Text(f"Queued {_plural(len(ids), 'job')}."), soft_wrap=True)
        view = EncodeView(console, labels)
        # Only our jobs: the store is shared, and other front ends' waiting jobs stay as
        # they are (C-11 ``start(job_ids=…)``; the runner goes idle when ours have ended).
        queue.start(job_ids=ids)
        await _follow_jobs(queue, ids, subscription, view)
        # The queue decides on its when-done action before wait() returns for the last job.
        await queue.wait(ids)
    except asyncio.CancelledError:
        task = asyncio.current_task()
        if task is not None:
            task.uncancel()
        if view is not None:
            view.close()
            view = None
        print(
            "Interrupted: cancelling the jobs (their partial files are removed)…", file=sys.stderr
        )
        await _cancel_jobs(queue, ids)
        _summary(console, queue, ids, not_queued)
        return EXIT_INTERRUPTED
    finally:
        subscription.close()
        if view is not None:
            view.close()
    finals = _summary(console, queue, ids, not_queued)
    all_done = all(job.state is JobState.DONE for job in finals)
    return EXIT_OK if all_done and not not_queued else EXIT_FAILED


async def _follow_jobs(
    queue: QueueLike, ids: Sequence[str], subscription: Subscription, view: EncodeView
) -> None:
    """Show the events of ``ids`` until every one of them has ended."""
    ours = set(ids)
    states: dict[str, JobState] = {}

    def refresh() -> None:
        for job_id in ids:
            job = queue.get(job_id)
            if job is not None:
                states[job_id] = job.state

    refresh()
    for job_id in ids:
        if states.get(job_id) in FINAL_STATES:
            ours.discard(job_id)
    if not ours:
        return
    async for event in subscription:
        if isinstance(event, JobStateEvent) and event.job_id in states:
            states[event.job_id] = event.state
            job = queue.get(event.job_id)
            view.state(
                event.job_id,
                event.state,
                error=event.error,
                output=job.output_path if job is not None else None,
                log=queue.log_path(event.job_id) if event.state is JobState.FAILED else None,
                previous=event.previous,
            )
            if event.state in FINAL_STATES:
                ours.discard(event.job_id)
        elif isinstance(event, JobProgressEvent) and event.job_id in states:
            view.progress(event.job_id, event.progress)
        elif isinstance(event, ResyncEvent):
            refresh()
            ours = {j for j in ours if states.get(j) not in FINAL_STATES}
        if not ours:
            break
    # The subscription ended early (it fell too far behind): wait through the queue.
    await queue.wait(ids)


async def _cancel_jobs(queue: QueueLike, ids: Sequence[str]) -> None:
    """Ctrl+C: stop the queue, cancel our waiting jobs, then our running ones (each cancel
    kills the process tree and removes the partial file), and wait for them to end. Only
    ``cancel(job_id)`` for our own ids: ``cancel()`` without an id would also cancel other
    front ends' jobs in the shared store."""
    await queue.stop()
    jobs = [job for job in (queue.get(j) for j in ids) if job is not None]
    waiting = [job.id for job in jobs if job.state is JobState.WAITING]
    active = [job.id for job in jobs if job.state in (JobState.RUNNING, JobState.PAUSED)]
    for job_id in [*waiting, *active]:
        await queue.cancel(job_id)
    try:
        async with asyncio.timeout(CANCEL_WAIT):
            await queue.wait(ids)
    except TimeoutError:
        _error(f"the jobs did not end within {CANCEL_WAIT:g} s after they were cancelled.")


def _summary(
    console: Console, queue: QueueLike, ids: Sequence[str], not_queued: int
) -> list[QueueJob]:
    finals = [job for job in (queue.get(j) for j in ids) if job is not None]
    counts = {state: sum(1 for job in finals if job.state is state) for state in JobState}
    parts = [f"{counts[JobState.DONE]} done", f"{counts[JobState.FAILED]} failed"]
    parts.append(f"{counts[JobState.CANCELLED]} cancelled")
    if counts[JobState.INTERRUPTED]:
        parts.append(f"{counts[JobState.INTERRUPTED]} interrupted")
    others = len(finals) - sum(counts[s] for s in FINAL_STATES)
    if others:
        parts.append(f"{others} not finished")
    parts.append(f"{not_queued} not queued")
    console.print(Text("Summary: " + ", ".join(parts) + ".", style="bold"), soft_wrap=True)
    return finals


# --------------------------------------------------------------------------- when done


class PowerLike(Protocol):
    """The part of C-14's ``PowerService`` (``Reframe.power``) that ``reframe encode`` uses."""

    @property
    def pending(self) -> PowerCountdownEvent | None: ...

    def cancel(self, countdown_id: str | None = None) -> bool: ...


#: Seconds ``reframe encode`` waits for the when-done countdown to start after its last job
#: (the queue starts it as the job ends; this only covers a power service that needs a few
#: loop turns). Only when Settings → Queue → When done is ``sleep`` or ``shutdown``.
COUNTDOWN_START_WAIT = 2.0
#: Seconds to wait, after ``executing``, for the power service to finish the action.
COUNTDOWN_EXECUTE_WAIT = 30.0
#: Lines mode: a countdown line every this many seconds.
COUNTDOWN_LINE_STEP = 10
#: The when-done actions that ``reframe encode`` waits for. ``quit`` is not one: the command
#: ends by itself when its jobs end (decision 0038), and closing Reframe cancels it.
WAITED_ACTIONS = frozenset({"sleep", "shutdown"})

_COUNTDOWN_VERB = {"shutdown": "Shutting down", "sleep": "Going to sleep"}
_COUNTDOWN_KEPT = {"shutdown": "will not shut down", "sleep": "will not go to sleep"}
_FINAL_PHASES = frozenset({"executing", "cancelled"})


def countdown_text(event: PowerCountdownEvent) -> str:
    """``Shutting down in 60 s — press Ctrl+C to cancel``, ``Shutting down now.``, …"""
    verb = _COUNTDOWN_VERB.get(event.action, event.action)
    if event.phase == "executing":
        return f"{verb} now."
    if event.phase == "cancelled":
        return f"Cancelled: the computer {_COUNTDOWN_KEPT.get(event.action, 'stays on')}."
    return f"{verb} in {event.seconds_left} s — press Ctrl+C to cancel"


class CountdownView:
    """The countdown on a terminal: one line that counts down in place. Otherwise: the first
    line, then a line at every multiple of :data:`COUNTDOWN_LINE_STEP` seconds, and the end."""

    def __init__(self, console: Console, *, live: bool | None = None) -> None:
        self.console = console
        self._live: Live | None = None
        self._last: int | None = None
        if console.is_terminal if live is None else live:
            self._live = Live(Text(""), console=console, auto_refresh=False, transient=True)
            self._live.start()

    def show(self, event: PowerCountdownEvent) -> None:
        text = Text(printable(countdown_text(event)), style="bold yellow")
        if event.phase in _FINAL_PHASES:
            self.close()
            self.console.print(text, soft_wrap=True)
            return
        if self._live is not None:
            self._live.update(text, refresh=True)
            return
        left = event.seconds_left
        if self._last is None or (0 < left < self._last and left % COUNTDOWN_LINE_STEP == 0):
            self._last = left
            self.console.print(text, soft_wrap=True)

    def close(self) -> None:
        if self._live is not None:
            self._live.stop()
            self._live = None


async def follow_countdown(
    app: Reframe,
    subscription: Subscription,
    console: Console,
    *,
    power: PowerLike | None = None,
    start_wait: float | None = None,
) -> int | None:
    """After ``reframe encode``'s jobs: when the queue started a sleep or shutdown countdown
    (Settings → Queue → When done), show it until it ends. Ctrl+C cancels it
    (``power.cancel``) and gives :data:`EXIT_INTERRUPTED`; else ``None`` (the jobs' exit code
    stands). Nothing is waited for when the setting is another action."""
    if app.settings_snapshot().queue.when_done not in WAITED_ACTIONS:
        return None
    power = power if power is not None else app.power
    view: CountdownView | None = None
    current: PowerCountdownEvent | None = None
    try:
        wait = COUNTDOWN_START_WAIT if start_wait is None else start_wait
        event = power.pending or await _countdown_start(subscription, wait)
        if event is None or event.action not in WAITED_ACTIONS:
            return None
        current = event
        view = CountdownView(console)
        view.show(event)
        while event.phase not in _FINAL_PHASES:
            received = await _next_event(subscription)
            if received is None:  # the bus closed
                return None
            if isinstance(received, ResyncEvent):  # events were lost: read the state
                latest = power.pending
                if latest is None or latest.countdown_id != current.countdown_id:
                    return None
                received = latest
            if (
                not isinstance(received, PowerCountdownEvent)
                or received.countdown_id != current.countdown_id
            ):
                continue
            event = received
            view.show(event)
        if event.phase == "executing":
            await _executed(power, current.countdown_id)
        return None
    except asyncio.CancelledError:
        task = asyncio.current_task()
        if task is not None:
            task.uncancel()
        if view is not None:
            view.close()
        target = current if current is not None else power.pending
        if target is not None and power.cancel(target.countdown_id):
            kept = _COUNTDOWN_KEPT.get(target.action, "stays on")
            print(f"Interrupted: the countdown is cancelled, the computer {kept}.", file=sys.stderr)
        else:
            print("Interrupted.", file=sys.stderr)
        return EXIT_INTERRUPTED
    finally:
        if view is not None:
            view.close()


async def _next_event(subscription: Subscription) -> object | None:
    try:
        return await subscription.__anext__()
    except StopAsyncIteration:
        return None


async def _countdown_start(subscription: Subscription, wait: float) -> PowerCountdownEvent | None:
    """The first ``started`` / ``tick`` event within ``wait`` seconds, else ``None``."""
    try:
        async with asyncio.timeout(wait):
            async for event in subscription:
                if isinstance(event, PowerCountdownEvent) and event.phase in ("started", "tick"):
                    return event
    except TimeoutError:
        pass
    return None


async def _executed(power: PowerLike, countdown_id: str) -> None:
    """Give the power service a bounded time to run the action before Reframe closes (its
    ``close`` cancels a countdown that still runs)."""
    deadline = time.monotonic() + COUNTDOWN_EXECUTE_WAIT
    while time.monotonic() < deadline:
        pending = power.pending
        if pending is None or pending.countdown_id != countdown_id:
            return
        await asyncio.sleep(0.1)


# --------------------------------------------------------------------------- name

#: The parsed-name fields that ``reframe name`` prints, in this order, with their labels.
_NAME_FIELDS: tuple[tuple[str, str], ...] = (
    ("kind", "kind"),
    ("name", "name"),
    ("year", "year"),
    ("episode_code", "episode"),
    ("season", "season"),
    ("episodes", "episode numbers"),
    ("sub_title", "episode title"),
    ("edition", "edition"),
    ("resolution", "resolution"),
    ("source_type", "source"),
    ("release_group", "group"),
)


def parsed_fields(result: NameResult) -> str:
    """``kind movie · name Hacksaw.Ridge · year 2016 · resolution 2160p · …``."""
    parts = []
    for field, label in _NAME_FIELDS:
        value = getattr(result.fields, field)
        if value is None or value == [] or (field == "episodes" and len(value) < 2):
            continue
        if isinstance(value, list):
            value = ", ".join(str(v) for v in value)
        parts.append(f"{label} {value}")
    return " · ".join(parts)


def output_name(result: NameResult) -> str:
    """The rendered name without the extension: ``Hacksaw.Ridge``."""
    suffix = f".{result.extension}"
    rel = result.relative_path
    return rel[: -len(suffix)] if rel.endswith(suffix) else rel


def render_name(console: Console, file: Path, result: NameResult, *, exists: bool) -> None:
    console.print(Text(display_path(file.name), style="bold"), soft_wrap=True)
    rows: list[tuple[str, str]] = [
        ("Source", f"{result.source} ({result.reason})"),
        ("Parsed", parsed_fields(result) or NONE),
        ("Template", f"{result.template} ({result.template_kind})"),
        ("Name", output_name(result)),
        ("File", str(result.path) if result.path is not None else result.relative_path),
    ]
    if result.skipped_folders:
        rows.append(("Skipped", ", ".join(result.skipped_folders)))
    rows += [("Note", note) for note in result.notes]
    if not exists:
        rows.append(("Note", "The file does not exist: the name comes from the path alone."))
    for key, value in rows:
        _indented(console, Text(printable(value)), _INDENT + 9, first=f"{'':{_INDENT}}{key:<8} ")
    render_issues(console, result.issues)


def name_targets(paths: Sequence[Path]) -> list[tuple[Path, Path | None, bool]]:
    """``(file, root, exists)`` for each path of ``reframe name``: a folder gives its media
    files (with the folder as the root that generic-folder skipping stays in), anything else
    is named as a file, also when it does not exist."""
    targets: list[tuple[Path, Path | None, bool]] = []
    for raw in paths:
        path = Path(os.path.abspath(raw))
        if path.is_dir():
            found = find_media_files([path])
            if not found.files:
                print(
                    _one_line(f"warning: {path}: no media files in this folder."), file=sys.stderr
                )
            targets += [(file, path, True) for file in found.files]
        else:
            targets.append((path, None, path.exists()))
    return targets


async def run_name(
    paths: Sequence[Path], *, template: str | None, preset: str | None, as_json: bool
) -> int:
    """``reframe name``: the output name of each path (a folder: of its media files)."""
    console = make_console()
    async with open_reframe() as app:
        chosen = find_preset(app, preset)
        if isinstance(chosen, str):
            _error(chosen)
            return EXIT_USAGE
        named: list[tuple[Path, NameResult, bool]] = []
        for file, root, exists in await asyncio.to_thread(name_targets, paths):
            result = await app.jobs.name(file, preset=chosen, template=template, root=root)
            named.append((file, result, exists))
    if template is not None and named:
        bad = [
            issue
            for issue in named[0][1].issues
            if issue.severity is Severity.ERROR and issue.code.startswith("naming.")
        ]
        if bad:
            for issue in bad:
                _error(f"--template: {issue.message}")
            return EXIT_USAGE
    if as_json:
        _write_model_json([result for _, result, _ in named])
    else:
        for i, (file, result, exists) in enumerate(named):
            if i:
                console.print()
            render_name(console, file, result, exists=exists)
    has_error = any(has_errors(result.issues) for _, result, _ in named)
    return EXIT_FAILED if has_error or not named else EXIT_OK


# --------------------------------------------------------------------------- tools

_EXIT_HELP_TOOLS_STATUS = "Exit codes: 0 ffmpeg and ffprobe can be used; 4 one of them cannot."
_EXIT_HELP_TOOLS_FETCH = (
    "Exit codes: 0 installed, or already installed with every file intact; 1 the download, "
    "the size or SHA-256 check, the archive or the version check failed; 2 usage error or "
    "unknown build; 130 interrupted (Ctrl+C: nothing is installed)."
)
#: The tools without which Reframe cannot probe or encode.
REQUIRED_TOOLS: tuple[ToolName, ...] = ("ffmpeg", "ffprobe")


def tool_problem(info: ToolInfo) -> str:
    """``ffmpeg is not usable (missing, not found anywhere): …`` and, when an override does
    not decide the path, how to get the pinned build."""
    text = (
        f"{info.name} is not usable ({info.status.value}, {origin_text(info)}): "
        f"{info.reason or 'no reason given'}"
    )
    if info.origin not in (ToolOrigin.ENV, ToolOrigin.SETTINGS):
        text += ' "reframe tools fetch" installs the pinned FFmpeg build.'
    return text


def fetched_text(data_dir: Path) -> str:
    """The line about the build that ``reframe tools fetch`` installed (from its marker)."""
    host = host_platform()
    if host is None:
        return "Fetched build: no FFmpeg build is pinned for this computer."
    install_dir = install_dir_for(data_dir, host, host)
    marker = installed_build(install_dir)
    if marker is None:
        return f'Fetched build: none ("reframe tools fetch" installs it into {install_dir}).'
    return (
        f"Fetched build: {marker.get('version')} ({marker.get('build')}, "
        f"{marker.get('platform')}) in {install_dir}."
    )


def _print_tool_lines(console: Console, tools: ToolSet) -> None:
    for line in status_lines(tools):
        console.print(Text(printable(line)), soft_wrap=True)


async def run_tools_status(*, as_json: bool) -> int:
    """``reframe tools status``: the discovery result. Returns the exit code."""
    async with open_reframe() as app:
        tools = await app.tools.status()
        data_dir = app.data_dir
    if as_json:
        _write_model_json(tools)
    else:
        console = make_console()
        _print_tool_lines(console, tools)
        console.print(Text(printable(fetched_text(data_dir)), style="dim"), soft_wrap=True)
    problems = [tools.get(name) for name in REQUIRED_TOOLS if not tool_usable(tools.get(name))]
    for info in problems:
        _error(tool_problem(info))
    return EXIT_NO_TOOL if problems else EXIT_OK


#: Lines mode: a progress line every this many percent of the fetch.
FETCH_PROGRESS_STEP = 10.0


class FetchView:
    """The progress of ``reframe tools fetch``: a bar with the step on a terminal; otherwise
    one line per step and a line every :data:`FETCH_PROGRESS_STEP` percent."""

    def __init__(self, console: Console, *, live: bool | None = None) -> None:
        self.console = console
        self._message: str | None = None
        self._percent = -FETCH_PROGRESS_STEP
        self._progress: Progress | None = None
        self._task: TaskID | None = None
        if console.is_terminal if live is None else live:
            self._progress = Progress(
                TextColumn("{task.description}"),
                BarColumn(),
                TextColumn("{task.percentage:>5.1f}%"),
                console=console,
                transient=True,
            )
            self._progress.start()
            self._task = self._progress.add_task("Fetching", total=100.0)

    def update(self, task: TaskInfo) -> None:
        message = task.message or "Fetching"
        if self._progress is not None and self._task is not None:
            self._progress.update(
                self._task, description=printable(message), completed=task.progress or 0.0
            )
            return
        percent = task.progress
        if message != self._message:
            self._message = message
            if percent is not None:
                self._percent = percent
            suffix = f" ({percent:.0f}%)" if percent else ""
            self.console.print(Text(printable(message + suffix)), soft_wrap=True)
        elif percent is not None and percent - self._percent >= FETCH_PROGRESS_STEP:
            self._percent = percent - percent % FETCH_PROGRESS_STEP
            self.console.print(Text(f"  {percent:.0f}%", style="dim"), soft_wrap=True)

    def close(self) -> None:
        if self._progress is not None:
            self._progress.stop()
            self._progress = None


def task_error(task: TaskInfo) -> str:
    """The reason of a failed task, without the ``TaskFailed:`` prefix of an expected
    failure."""
    error = task.error or "no reason given"
    return error.removeprefix(f"{TaskFailed.__name__}: ")


async def _follow_task(
    app: Reframe, subscription: Subscription, task_id: str, view: FetchView
) -> TaskInfo:
    """Show the progress of ``task_id`` until it ends; its final info."""
    async for event in subscription:
        if isinstance(event, (TaskProgressEvent, TaskDoneEvent)) and event.task.id == task_id:
            view.update(event.task)
            if isinstance(event, TaskDoneEvent):
                break
        elif isinstance(event, ResyncEvent):
            info = app.tasks.get(task_id)
            if info is not None:
                view.update(info)
    return await app.tasks.wait(task_id)


async def run_tools_fetch(*, build: str, platform: str | None) -> int:
    """``reframe tools fetch``: the pinned build through the ``tools_fetch`` task (progress,
    then the tool lines). Returns the exit code; Ctrl+C stops the download (exit 130)."""
    try:
        builds = load_manifest()
    except FetchError as exc:  # pragma: no cover - the manifest ships with the package
        _error(f"the pinned-build manifest cannot be read: {exc}")
        return EXIT_FAILED
    chosen = builds.get(build)
    if chosen is None:
        names = ", ".join(f'"{name}"' for name in sorted(builds))
        _error(f'there is no build "{build}" in the manifest. Builds: {names}.')
        return EXIT_USAGE
    host = host_platform()
    target = platform or host
    if target is None:
        _error(
            "no FFmpeg build is pinned for this computer: --platform downloads one for "
            f"another computer ({', '.join(PLATFORMS)})."
        )
        return EXIT_FAILED
    archive = chosen.platforms.get(target)
    if archive is None:
        _error(f'the build "{build}" has no archive for {target}.')
        return EXIT_USAGE
    console = make_console()
    console.print(
        Text(printable(f"FFmpeg {chosen.version} ({chosen.name}, {target}): {archive.url}")),
        soft_wrap=True,
    )
    async with open_reframe() as app:
        subscription = app.events.subscribe(types={"task.progress", "task.done"})
        info = app.tools.fetch(build=build, platform=target)
        view = FetchView(console)
        try:
            final = await _follow_task(app, subscription, info.id, view)
        except asyncio.CancelledError:
            current = asyncio.current_task()
            if current is not None:
                current.uncancel()
            view.close()
            print("Interrupted: stopping the download…", file=sys.stderr)
            app.tasks.cancel(info.id, "interrupted")
            await app.tasks.wait(info.id)
            print("Nothing was installed.", file=sys.stderr)
            return EXIT_INTERRUPTED
        finally:
            subscription.close()
            view.close()
        if final.state is not TaskState.DONE:
            reason = task_error(final) if final.state is TaskState.FAILED else "it was cancelled"
            _error(f"the fetch failed: {reason}")
            return EXIT_FAILED
        result = app.tasks.value(info.id)
        assert isinstance(result, ToolFetchResult)
        tools = app.tools.current if target == host else None
    _fetch_report(console, result, tools)
    return EXIT_OK


def _fetch_report(console: Console, result: ToolFetchResult, tools: ToolSet | None) -> None:
    if result.downloaded:
        line = f"Installed FFmpeg {result.version} into {result.install_dir}."
    else:
        line = (
            f"FFmpeg {result.version} is already installed in {result.install_dir} and every "
            "file is intact: nothing was downloaded."
        )
    console.print(Text(printable(line), style="bold green"), soft_wrap=True)
    if tools is None:
        console.print(
            Text(
                printable(
                    f"This build is for {result.platform}: tool discovery on this computer "
                    f"does not use it. Copy {result.install_dir} to <data dir>/tools/ffmpeg "
                    "on that computer."
                )
            ),
            soft_wrap=True,
        )
        return
    _print_tool_lines(console, tools)
    for name in REQUIRED_TOOLS:
        info = tools.get(name)
        installed = result.ffmpeg if name == "ffmpeg" else result.ffprobe
        if info.path is not None and Path(info.path) == installed:
            continue
        print(
            _one_line(
                f"warning: {name} is not the fetched build: {origin_text(info)}. An "
                "environment variable or Settings > Tools takes precedence over the "
                "bundled build."
            ),
            file=sys.stderr,
        )


# --------------------------------------------------------------------------- presets

_EXIT_HELP_PRESETS_LIST = "Exit codes: 0 listed."
_EXIT_HELP_PRESETS_EXPORT = (
    "Exit codes: 0 exported; 1 FILE cannot be written; 2 usage error, an unknown preset, or "
    "FILE is a folder."
)
_EXIT_HELP_PRESETS_IMPORT = (
    "Exit codes: 0 imported (also when every preset was skipped); 1 the file is not a Reframe "
    "preset file, a preset was not imported, or presets.json cannot be written; 2 usage "
    "error; 3 FILE does not exist or cannot be read."
)


class ConflictChoice(StrEnum):
    """``--on-conflict`` of ``reframe presets import`` (C-9's ``ConflictPolicy``)."""

    RENAME = "rename"
    REPLACE = "replace"
    SKIP = "skip"


class PlatformChoice(StrEnum):
    """``--platform`` of ``reframe tools fetch`` (the manifest's platforms)."""

    LINUX_X64 = "linux-x64"
    WINDOWS_X64 = "windows-x64"


def preset_rows(presets: Sequence[Preset], default_id: str) -> list[str]:
    """The lines of ``reframe presets list``: a ``*`` for the default, then name, category,
    id and kind in columns, and a legend."""
    header = ("", "Name", "Category", "Id", "Kind")
    rows = [
        (
            "*" if p.id == default_id else "",
            printable(p.name),
            printable(p.category),
            printable(p.id),
            "built-in" if p.built_in else "user",
        )
        for p in presets
    ]
    widths = [max(len(row[i]) for row in [header, *rows]) for i in range(len(header))]
    lines = [
        "  ".join(cell.ljust(width) for cell, width in zip(row, widths, strict=True)).rstrip()
        for row in [header, *rows]
    ]
    users = sum(1 for p in presets if not p.built_in)
    lines.append("")
    lines.append(
        f"* default preset · {len(presets) - users} built-in, {_plural(users, 'user preset')}"
    )
    return lines


async def run_presets_list(*, as_json: bool) -> int:
    """``reframe presets list``: built-in, then user presets."""
    async with open_reframe() as app:
        presets = app.presets.list()
        default = app.presets.default()
    if as_json:
        _write_json_value(
            {
                "default_preset_id": default.id,
                "presets": [
                    {
                        "id": p.id,
                        "name": p.name,
                        "category": p.category,
                        "description": p.description,
                        "built_in": p.built_in,
                        "default": p.id == default.id,
                    }
                    for p in presets
                ],
            }
        )
        return EXIT_OK
    console = make_console()
    for line in preset_rows(presets, default.id):
        console.print(Text(line), soft_wrap=True)
    return EXIT_OK


def _write_json_value(data: object) -> None:
    """JSON on stdout (``\\uXXXX`` escapes when stdout is not UTF-8)."""
    encoding = (getattr(sys.stdout, "encoding", None) or "utf-8").lower().replace("_", "-")
    text = json.dumps(data, indent=2, ensure_ascii=encoding not in ("utf-8", "utf8"))
    try:
        text.encode("utf-8")
    except UnicodeEncodeError:  # a lone surrogate (a name from a non-UTF-8 file name)
        text = json.dumps(data, indent=2, ensure_ascii=True)
    sys.stdout.write(text + "\n")
    sys.stdout.flush()


def write_text_file(path: Path, text: str) -> None:
    """Write ``text`` (UTF-8) through a temporary file in the same folder and a rename, so a
    failed write never leaves half a file. :raises OSError:"""
    folder = path.parent if str(path.parent) else Path()
    fd, temp = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=folder)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
        os.replace(temp, path)
    except BaseException:
        Path(temp).unlink(missing_ok=True)
        raise


async def run_presets_export(names: Sequence[str], *, output: Path | None) -> int:
    """``reframe presets export``: the named presets (none named: every user preset) as the
    export file (decision 0028: presets of a newer Reframe are kept), on stdout or in FILE."""
    to_stdout = output is None or str(output) == "-"
    if output is not None and not to_stdout and await asyncio.to_thread(output.is_dir):
        _error(f"{display_path(output)} is a folder: -o needs a file name.")
        return EXIT_USAGE
    async with open_reframe() as app:
        ids: list[str] | None = None
        if names:
            ids = []
            for name in names:
                found = find_preset(app, name)
                if isinstance(found, str):
                    _error(found)
                    return EXIT_USAGE
                ids.append(found.id)
        export = app.presets.export(ids)
    document = export.document()
    for issue in export.issues:
        print(_one_line(f"warning: {issue.message}"), file=sys.stderr)
    count = len(document.get("presets") or [])
    if not count:
        print(
            "warning: there are no user presets to export (name presets to export them, "
            "built-in ones too).",
            file=sys.stderr,
        )
    if to_stdout:
        _write_json_value(document)
        return EXIT_OK
    assert output is not None
    text = json.dumps(document, indent=2, ensure_ascii=False) + "\n"
    try:
        await asyncio.to_thread(write_text_file, output, text)
    except UnicodeEncodeError:  # a lone surrogate: write it escaped
        text = json.dumps(document, indent=2, ensure_ascii=True) + "\n"
        await asyncio.to_thread(write_text_file, output, text)
    except OSError as exc:
        _error(f"{display_path(output)} cannot be written: {exc.strerror or exc}.")
        return EXIT_FAILED
    make_console().print(
        Text(printable(f"Exported {_plural(count, 'preset')} to {output}.")), soft_wrap=True
    )
    return EXIT_OK


def read_preset_file(path: Path) -> dict[str, Any] | tuple[int, str]:
    """The JSON object of an export file (``-``: stdin), else ``(exit code, message)``."""
    name = "stdin" if str(path) == "-" else display_path(path)
    try:
        raw = sys.stdin.buffer.read() if str(path) == "-" else path.read_bytes()
    except FileNotFoundError:
        return EXIT_NOT_FOUND, f"{name}: the file does not exist."
    except IsADirectoryError:
        return EXIT_NOT_FOUND, f"{name} is a folder, not a preset file."
    except OSError as exc:
        return EXIT_NOT_FOUND, f"{name} cannot be read: {exc.strerror or exc}."
    try:
        data = json.loads(raw.decode("utf-8-sig"))
    except UnicodeDecodeError:
        return EXIT_FAILED, f"{name} is not a Reframe preset file: it is not UTF-8 text."
    except RecursionError:
        return EXIT_FAILED, f"{name} is not a Reframe preset file: it is nested too deeply."
    except ValueError as exc:
        return EXIT_FAILED, f"{name} is not a Reframe preset file: it is not JSON ({exc})."
    if not isinstance(data, dict):
        return EXIT_FAILED, f"{name} is not a Reframe preset file: it is not a JSON object."
    return data


def render_import(console: Console, result: ImportResult, source: str, policy: str) -> None:
    """``Imported 2 presets from FILE (on a conflict: rename):``, then each preset, the
    replaced and skipped ones, and the issues."""
    if result.imported:
        console.print(
            Text(
                printable(
                    f"Imported {_plural(len(result.imported), 'preset')} from {source} "
                    f"(on a conflict: {policy}):"
                ),
                style="bold",
            ),
            soft_wrap=True,
        )
    else:
        console.print(
            Text(printable(f"Nothing was imported from {source}."), style="bold"), soft_wrap=True
        )
    renamed = {new: old for old, new in result.renamed}
    for preset in result.imported:
        line = f"{preset.name}  ({preset.id})"
        if preset.name in renamed:
            line += f", renamed from “{renamed[preset.name]}”"
        _indented(console, Text(printable(line)))
    if result.replaced:
        _indented(console, Text(printable("Replaced: " + ", ".join(result.replaced))))
    if result.skipped:
        _indented(console, Text(printable("Skipped: " + ", ".join(result.skipped))))
    if result.issues:
        _section(console, f"Issues ({issue_counts(result.issues)})")
        render_issues(console, result.issues)


async def run_presets_import(file: Path, *, on_conflict: ConflictPolicy) -> int:
    """``reframe presets import``: the presets of an export file, with the conflict policy."""
    data = await asyncio.to_thread(read_preset_file, file)
    if isinstance(data, tuple):
        code, message = data
        _error(message)
        return code
    async with open_reframe() as app:
        result = await app.presets.import_(data, on_conflict)
    source = "stdin" if str(file) == "-" else display_path(file)
    render_import(make_console(), result, source, on_conflict)
    # Every warning or error of an import is a preset (or the whole file) left out: a failure
    # for a script. A preset skipped by ``--on-conflict skip`` has no issue.
    left_out = any(issue.severity is not Severity.INFO for issue in result.issues)
    return EXIT_FAILED if left_out else EXIT_OK


def build_app() -> typer.Typer:
    """The typer application (imports typer, so only with the ``[cli]`` extra)."""
    app = typer.Typer(
        add_completion=False,
        no_args_is_help=True,
        help="Reframe video transcoder",
        pretty_exceptions_show_locals=False,
    )

    @app.callback()
    def _root() -> None:
        """Reframe video transcoder."""

    @app.command()
    def version() -> None:
        """Print the Reframe version."""
        typer.echo(__version__)

    @app.command(epilog=_EXIT_HELP)
    def probe(
        # readable=False: the facade reports an unreadable file (exit 3, one line), not
        # click (exit 2 with a usage box).
        file: Annotated[
            Path,
            typer.Argument(help="The media file to probe.", metavar="FILE", readable=False),
        ],
        as_json: Annotated[
            bool, typer.Option("--json", help="Print the MediaSource model as JSON.")
        ] = False,
    ) -> None:
        """Print every track of FILE: codec, channels, bitrate and its source, language,
        title, role badges and flags."""
        _run(run_probe(file, as_json=as_json))

    @app.command(epilog=_EXIT_HELP_ENCODERS)
    def encoders(
        as_json: Annotated[
            bool,
            typer.Option("--json", help="Wait for detection, then print the snapshot as JSON."),
        ] = False,
    ) -> None:
        """Show which encoders this FFmpeg build and this computer can use.

        The cached result is printed at once (or "checking…" when there is none), then every
        status that the running detection changes, one line per encoder, for example
        "hevc_nvenc — unavailable: NVIDIA driver not found"."""
        _run(run_encoders(as_json=as_json))

    @app.command(epilog=_EXIT_HELP_PLAN)
    def plan(
        file: Annotated[
            Path, typer.Argument(help="The source file.", metavar="FILE", readable=False)
        ],
        preset: _PresetOption = None,
        output: _OutputOption = None,
        as_json: Annotated[
            bool, typer.Option("--json", help="Print the draft and the plan as JSON.")
        ] = False,
    ) -> None:
        """Print the issues of FILE encoded with a preset, then the FFmpeg command.

        The job is drafted as "reframe encode" drafts it: every audio track through the
        preset's codec rules, every subtitle copied, the output named by the naming template
        (or -o). Issues are listed with their fixes: errors, then warnings, then info."""
        _run(run_plan(file, preset=preset, output=output, as_json=as_json))

    @app.command(epilog=_EXIT_HELP_ENCODE)
    def encode(
        paths: Annotated[
            list[Path],
            typer.Argument(
                help="Media files, and folders whose media files are encoded.",
                metavar="FILE|DIR…",
                readable=False,
            ),
        ],
        preset: _PresetOption = None,
        output: _OutputOption = None,
        recursive: Annotated[
            bool,
            typer.Option("--recursive", "-r", help="Also search the subfolders of folders."),
        ] = False,
    ) -> None:
        """Encode media files: one job per file, through the queue, with progress and ETA.

        Each job is drafted from the preset and validated; a file whose job has errors is
        reported and not queued, the others are encoded. Outputs are named by the naming
        template (-o only with a single file). Ctrl+C cancels the running and waiting jobs
        and removes their partial files."""
        _run(run_encode(paths, preset=preset, output=output, recursive=recursive))

    @app.command(epilog=_EXIT_HELP_NAME)
    def name(
        paths: Annotated[
            list[Path],
            typer.Argument(
                help="Files (they need not exist) or folders (their media files).",
                metavar="PATH…",
                readable=False,
            ),
        ],
        template: Annotated[
            str | None,
            typer.Option(
                "--template",
                "-t",
                help="Naming template for movies and episodes, for example "
                "'{name}< ({year})>< - S{season:02}E{episode:02}>'.",
            ),
        ] = None,
        preset: _PresetOption = None,
        as_json: Annotated[
            bool, typer.Option("--json", help="Print the naming results as JSON.")
        ] = False,
    ) -> None:
        """Show the output name of each path: the name source and why, the parsed fields,
        the template and the name.

        Works from the path alone (no probe): variables of the output media, such as
        {resolution}, are empty here; "reframe plan" shows the full name."""
        _run(run_name(paths, template=template, preset=preset, as_json=as_json))

    tools_app = typer.Typer(
        no_args_is_help=True,
        help="Which FFmpeg, ffprobe, mkvpropedit and MediaInfo Reframe uses; fetch the pinned "
        "FFmpeg build.",
    )
    app.add_typer(tools_app, name="tools")

    @tools_app.command("status", epilog=_EXIT_HELP_TOOLS_STATUS)
    def tools_status(
        as_json: Annotated[
            bool, typer.Option("--json", help="Print the ToolSet model as JSON.")
        ] = False,
    ) -> None:
        """Show each tool: status, origin (env, settings, bundled, path), path, version and
        the reason when it cannot be used, then the build that "reframe tools fetch"
        installed.

        The order of the search: the REFRAME_FFMPEG / REFRAME_FFPROBE / REFRAME_MKVPROPEDIT /
        REFRAME_MEDIAINFO variables, Settings > Tools, the bundled build (also the fetched
        one in <data dir>/tools/ffmpeg), then PATH (only without a bundled build)."""
        _run(run_tools_status(as_json=as_json))

    @tools_app.command("fetch", epilog=_EXIT_HELP_TOOLS_FETCH)
    def tools_fetch(
        build: Annotated[
            str,
            typer.Option(
                "--build", metavar="NAME", help="The build of the manifest: default, override-test."
            ),
        ] = "default",
        target: Annotated[
            PlatformChoice | None,
            typer.Option(
                "--platform",
                help="Another computer's platform: the build goes to <data dir>/tools/"
                "ffmpeg-<platform>, which this computer does not use. Default: this computer.",
            ),
        ] = None,
    ) -> None:
        """Download the pinned FFmpeg build and install it as the bundled build in
        <data dir>/tools/ffmpeg, where tool discovery finds it.

        The size and SHA-256 of the archive are checked before anything is extracted;
        ffmpeg -version and ffprobe -version must print the pinned version before the build
        replaces the one installed before. A build that is installed and intact is not
        downloaded again."""
        _run(run_tools_fetch(build=build, platform=target.value if target else None))

    presets_app = typer.Typer(
        no_args_is_help=True, help="List, export and import presets (built-in and user)."
    )
    app.add_typer(presets_app, name="presets")

    @presets_app.command("list", epilog=_EXIT_HELP_PRESETS_LIST)
    def presets_list(
        as_json: Annotated[
            bool,
            typer.Option(
                "--json", help="Print id, name, category, description, built-in and default."
            ),
        ] = False,
    ) -> None:
        """List the presets: the built-in ones in their order, then the user presets, with
        their category and id; * marks the default preset."""
        _run(run_presets_list(as_json=as_json))

    @presets_app.command("export", epilog=_EXIT_HELP_PRESETS_EXPORT)
    def presets_export(
        names: Annotated[
            list[str] | None,
            typer.Argument(
                help="Presets by name (without case) or id. Default: every user preset.",
                metavar="[NAME_OR_ID…]",
                show_default=False,
            ),
        ] = None,
        output: Annotated[
            Path | None,
            typer.Option("--output", "-o", metavar="FILE", help="Write to FILE instead of stdout."),
        ] = None,
    ) -> None:
        """Export presets as a Reframe preset file (JSON, versioned). Presets that a newer
        Reframe wrote are exported unchanged, with a warning."""
        _run(run_presets_export(names or [], output=output))

    @presets_app.command("import", epilog=_EXIT_HELP_PRESETS_IMPORT)
    def presets_import(
        file: Annotated[
            Path,
            typer.Argument(
                help="A Reframe preset file (from export); - reads stdin.",
                metavar="FILE",
                readable=False,
            ),
        ],
        on_conflict: Annotated[
            ConflictChoice,
            typer.Option(
                "--on-conflict",
                help="When a preset has the name or id of an existing one: rename (a new id "
                "and the next free name, 'Name (2)'), replace (overwrite the user preset; a "
                "built-in is never replaced, the import is renamed) or skip.",
            ),
        ] = ConflictChoice.RENAME,
    ) -> None:
        """Import the presets of a Reframe preset file as user presets."""
        _run(run_presets_import(file, on_conflict=on_conflict.value))

    return app


class _ExpectedTaskFailure(logging.Filter):
    """Drops the task manager's log record (with a traceback) of a task that ended with
    :class:`~reframe.mediatask.TaskFailed`: an expected failure that the command reports as
    one ``error:`` line (decision 0017 item 23)."""

    def filter(self, record: logging.LogRecord) -> bool:
        error = record.exc_info[1] if record.exc_info else None
        return not isinstance(error, TaskFailed)


def _quiet_expected_failures() -> None:
    logger = logging.getLogger("reframe.tasks")
    if not any(isinstance(f, _ExpectedTaskFailure) for f in logger.filters):
        logger.addFilter(_ExpectedTaskFailure())


def _run(work: Coroutine[object, object, int]) -> None:
    """Run a command's coroutine; a non-zero code exits with it. Ctrl+C exits with 130 (the
    commands that start jobs cancel them first)."""
    _quiet_expected_failures()
    try:
        code = asyncio.run(work)
    except KeyboardInterrupt:
        print("Interrupted.", file=sys.stderr)
        code = EXIT_INTERRUPTED
    except Exception as exc:  # a bug: one line, never a traceback (unless asked for)
        if os.environ.get(TRACEBACK_ENV, "").strip().lower() not in ("", "0", "false", "no"):
            raise
        _error(
            f"unexpected error ({type(exc).__name__}: {exc}). Please report this; "
            f"{TRACEBACK_ENV}=1 shows the traceback."
        )
        code = EXIT_FAILED
    if code:
        raise typer.Exit(code)


def _replace_unencodable(stream: object) -> None:
    """Make a text stream replace characters it cannot encode instead of raising."""
    if isinstance(stream, io.TextIOWrapper):
        stream.reconfigure(errors="replace")


def main() -> None:
    if not _CLI_EXTRA:  # pragma: no cover - depends on the installed extras
        print("The reframe CLI needs the [cli] extra: pip install 'reframe[cli]'", file=sys.stderr)
        raise SystemExit(2) from None
    _replace_unencodable(sys.stdout)
    build_app()()


if __name__ == "__main__":
    main()
