"""Command-line entry point (needs the ``[cli]`` extra: typer, with rich). Each command runs
the core and prints its result for people, or as JSON with ``--json`` (JSON only on stdout).
A command's error is one ``error:`` line on stderr, never a traceback;
``REFRAME_TRACEBACK=1`` shows the traceback of an unexpected error.
"""

from __future__ import annotations

import asyncio
import contextlib
import dataclasses
import difflib
import io
import json
import logging
import os
import stat
import sys
import tempfile
import time
from collections.abc import AsyncIterator, Awaitable, Callable, Coroutine, Iterable, Sequence
from contextlib import asynccontextmanager
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Any, Protocol

from pydantic import BaseModel

from reframe import __version__, languages, paths
from reframe.batch.grouping import episode_labels
from reframe.batch.report import ROW_ASCII, ROW_MARKS, matrix_lines
from reframe.batch.service import BatchService
from reframe.events import EventBus, Subscription
from reframe.jobs import OutputClaims, draft_from_preset, find_media_files, has_errors
from reframe.mediatask import TaskFailed
from reframe.models.batch import BatchGroup, BatchResolution, MatchLevel
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
from reframe.models.naming import NameResult, NamingOptions
from reframe.models.plan import EncodePlan
from reframe.models.preset import Preset
from reframe.models.queue import JobProgress, JobState, QueueJob
from reframe.models.tasks import TaskInfo, TaskState
from reframe.models.text import json_text
from reframe.models.tools import ToolFetchResult, ToolInfo, ToolName, ToolOrigin, ToolSet
from reframe.presets import ConflictPolicy, ImportResult
from reframe.queue import ENDED, QueueError, QueueLike, UnknownJobError, read_saved_queue
from reframe.queue.logs import log_file
from reframe.service import ProbeError, ProbeErrorKind, Reframe, tool_usable
from reframe.tools.__main__ import status_lines
from reframe.tools.fetch import (
    MARKER_NAME,
    PLATFORMS,
    FetchError,
    host_platform,
    install_dir_for,
    installed_build,
    load_manifest,
)

if TYPE_CHECKING:
    from reframe.remote import RemoteQueue

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
    #: The job arguments of ``reframe queue``.
    _JobRefs = Annotated[
        list[str] | None,
        typer.Argument(help="Job ids, or the start of each.", metavar="[ID…]", show_default=False),
    ]
    _JobRef = Annotated[str, typer.Argument(help="A job id, or its start.", metavar="ID")]
    _All = Annotated[bool, typer.Option("--all", help="Every job (instead of IDs).")]

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
#: What a command returns when something failed (its epilog lists the codes).
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
_EXIT_HELP_NAME = (
    "Exit codes: 0 named; 1 a name has errors; 2 usage error or a bad template; 3 no media files."
)
_EXIT_HELP_BATCH = (
    "Exit codes: 0 every file resolved without errors (--dry-run) or every job done; 1 a file "
    "has errors, cannot be read, or a job failed, was cancelled or was not queued; 2 usage "
    "error or unknown preset; 3 a path does not exist, or no media files; 130 interrupted "
    "(Ctrl+C: the jobs are cancelled first)."
)

_EXIT_BY_KIND = {
    ProbeErrorKind.NOT_FOUND: EXIT_NOT_FOUND,
    ProbeErrorKind.NOT_A_FILE: EXIT_NOT_FOUND,
    ProbeErrorKind.UNREADABLE: EXIT_NOT_FOUND,
    ProbeErrorKind.TOOL_FAILED: EXIT_NO_FFPROBE,
}


#: The dash for "no value".
NONE = "—"
#: Between width and height.
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
    """``3912345`` → ``3 912 345`` (space as the thousands separator)."""
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
    """The stream as one line: ``HEVC Main 10 · 3840×2160 · 23.976 fps · HDR10 · BT.2020 PQ``."""  # noqa: RUF002
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
    keyword or the track layout suggests it."""
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


#: C0 and C1 control characters and DEL, each shown as U+FFFD by :func:`printable`.
_CONTROLS = dict.fromkeys([*range(0x20), *range(0x7F, 0xA0)], "\ufffd")


def printable(text: str) -> str:
    """``text`` for the terminal: the bytes of a file name that is not valid UTF-8
    (``os.fsdecode`` keeps them as lone surrogates, U+DCFF) and every control character (C0
    with the line break and the tab, DEL, C1) shown as U+FFFD. A UTF-8 stream cannot take a
    lone surrogate, and a control character from a file or a name (``ESC [31m``, ``ESC ]0;``,
    a line break in a preset name) would change the terminal or the layout."""
    try:
        text = text.encode("utf-8", "surrogateescape").decode("utf-8", "replace")
    except UnicodeEncodeError:  # other lone surrogates (a broken UTF-16 name on Windows)
        text = text.encode("utf-8", "replace").decode("utf-8")
    return text.translate(_CONTROLS)


def display_path(path: Path | str) -> str:
    """A path for the human output (:func:`printable`)."""
    return printable(str(path))


def _one_line(text: str) -> str:
    """``text`` as one line: runs of white space (line breaks, tabs) become one space, then
    :func:`printable`."""
    return printable(" ".join(text.split()))


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


#: Indent of the lines under a section title.
_INDENT = 2


def _text(value: str | None, style: str = "") -> Text:
    """A table cell (:func:`printable`: track titles come from the file)."""
    return Text(printable(value) if value else NONE, style=style)


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
    """``#3  [Commentary]  disposition comment``: the tooltip of each badge."""
    lines = []
    for s in streams:
        for role in s.roles:
            line = Text(f"#{s.index}  ")
            line.append_text(_badges([role]))
            line.append(printable(f"  {role.detail or role.evidence.value}"), style="dim")
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
            _indented(console, Text(printable(value)), first=f"{'':{_INDENT}}{key:<10} ")

    _section(console, f"Video ({len(source.video)})")
    if not source.video:
        _indented(console, Text(NONE))
    for v in source.video:
        _indented(console, Text.assemble(f"#{v.index}  ", (printable(video_line(v)), "bold")))
        _indented(console, Text(printable(video_details(v)), style="dim"), _INDENT + 4)

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
        _indented(console, Text(printable(item), style=style))
    if len(items) > len(shown):
        _indented(console, Text(f"… and {len(items) - len(shown)} more", style="dim"))


def _write_json(source: MediaSource) -> None:
    _write_json_value(source.model_dump(mode="json"))


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
        """After ``Reframe.close()``: print the warnings published while it closed, then stop."""
        try:
            async with asyncio.timeout(5):
                await asyncio.shield(self._task)
        except TimeoutError:  # pragma: no cover - the bus was not closed
            self._subscription.close()
            self._task.cancel()


@asynccontextmanager
async def open_reframe(*, detect: bool = True) -> AsyncIterator[Reframe]:
    """``Reframe.create()`` for a command, with its warnings printed (:class:`WarningPrinter`)
    also those published while it closes. ``detect=False``: encoder detection does not start
    (the command starts it, or uses the queue owner's)."""
    if detect:
        app = await Reframe.create()
    else:
        app = Reframe(
            config_dir=paths.config_dir(), data_dir=paths.data_dir(), cache_dir=paths.cache_dir()
        )
        app.tools.start()
    printer = WarningPrinter(app)
    try:
        yield app
    finally:
        try:
            await app.close()
        finally:
            await printer.finish()


def _write_model_json(value: BaseModel | Sequence[BaseModel] | dict[str, BaseModel | None]) -> None:
    """Models as JSON on stdout (:func:`_write_json_value`)."""
    if isinstance(value, BaseModel):
        data: object = value.model_dump(mode="json")
    elif isinstance(value, dict):
        data = {k: None if v is None else v.model_dump(mode="json") for k, v in value.items()}
    else:
        data = [item.model_dump(mode="json") for item in value]
    _write_json_value(data)


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
    fix, errors first."""
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


def encoder_text(status: EncoderStatus) -> str:
    """``hevc_nvenc — unavailable: NVIDIA driver not found``."""
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
            console.print(Text(printable(encoder_text(status))), soft_wrap=True)

    async with subscription:
        async for event in subscription:
            if not isinstance(event, CapabilitiesChangedEvent):
                continue  # a resync marker: the snapshot below is read again anyway
            snapshot = capabilities.snapshot
            if first:
                first = False
                checking = all(s.state is EncoderState.CHECKING for s in event.encoders)
                if not snapshot.detecting:
                    console.print(
                        Text(printable(f"Encoders of {_ffmpeg_text(snapshot)}:")), soft_wrap=True
                    )
                elif checking:
                    console.print(
                        Text(
                            printable(
                                "No cached result: checking the encoders of "
                                f"{_ffmpeg_text(snapshot)}…"
                            )
                        ),
                        soft_wrap=True,
                    )
                else:
                    when = snapshot.checked_at
                    at = f" of {when.astimezone():%Y-%m-%d %H:%M}" if when is not None else ""
                    console.print(
                        Text(
                            printable(f"Encoders of {_ffmpeg_text(snapshot)} (cached result{at}):")
                        ),
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
    for key, decisions in (("Audio", draft.decisions), ("Subtitle", draft.subtitle_decisions)):
        for i, d in enumerate(decisions):
            number = f"#{d.source_stream}"
            rows.append((key if i == 0 else "", f"{number}  {d.reason}"))
            if d.selected and d.selection:
                # Why the track was taken: the selection stage or the track rule.
                rows.append(("", f"{'':{len(number)}}  selected: {d.selection}"))
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


#: The note of ``reframe plan`` when the dry run ran and found no error (its warnings are
#: issues).
DRY_RUN_NOTE = "The custom encoder parameters were checked by encoding one frame (dry run)."
#: The dry run's warning when the test encode did not run (no FFmpeg, a timeout): no note.
DRY_RUN_SKIPPED = "encoder.dry_run_skipped"


def needs_dry_run(job: JobSettings, preset: Preset | None = None) -> bool:
    """``reframe plan`` runs the one-frame dry run when the job has custom encoder parameters
    that are used (not with video passthrough): validation cannot check them.

    Not for the unchanged parameters of a built-in preset: Reframe's own tests check those
    against the pinned FFmpeg build, and most built-in x265 / SVT-AV1 presets have some, so
    every ``reframe plan`` would encode a frame."""
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
            # The dry run is run here, not by plan(dry_run=True): plan() returns only the plan
            # when the dry run has no error, and its warnings (a setting the encoder changed, a
            # test encode that did not run) belong with the other issues.
            dry_run = needs_dry_run(draft.job, chosen)
            checked = await app.jobs.dry_run(draft.job, source) if dry_run else []
            if checked:
                draft = draft.model_copy(update={"issues": [*draft.issues, *checked]})
            planned = None if has_errors(checked) else await app.jobs.plan(draft.job, source)
            if isinstance(planned, EncodePlan):
                plan = planned
                # The note only when the test encode ran (not "did not run": no FFmpeg, a
                # timeout).
                if dry_run and not any(issue.code == DRY_RUN_SKIPPED for issue in checked):
                    draft = draft.model_copy(update={"notes": [*draft.notes, DRY_RUN_NOTE]})
            elif planned is not None:  # validation agreed before: a bug's (or a race's) issues
                new = [issue for issue in planned if issue not in draft.issues]
                draft = draft.model_copy(update={"issues": [*draft.issues, *new]})
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


def get_queue(app: Reframe) -> QueueLike:
    """The in-process queue of ``app`` (``Reframe.queue``): the one place where the CLI gets
    it. Tests of the CLI's own logic replace it with a fake that follows the same contract."""
    return app.queue


#: Set to ``1`` to run the jobs of ``encode`` and ``batch`` in the command's own process, as
#: ``--in-process`` does.
IN_PROCESS_ENV = "REFRAME_IN_PROCESS"
#: How often a command looks for the queue's owner when the one it found was stopping.
OWNER_ATTEMPTS = 3


def in_process_default() -> bool:
    """:data:`IN_PROCESS_ENV` is set to something other than empty, ``0``, ``false``, ``no``."""
    return os.environ.get(IN_PROCESS_ENV, "").strip().lower() not in ("", "0", "false", "no")


class _Drafts(Protocol):
    async def draft(
        self,
        source: str | os.PathLike[str] | MediaSource,
        preset: Preset | str | None = None,
        *,
        output: Path | None = None,
    ) -> JobDraft | ProbeError: ...


class PowerLike(Protocol):
    """The when-done countdown that ``reframe encode`` follows: the in-process
    ``PowerService`` or the queue owner's."""

    @property
    def pending(self) -> PowerCountdownEvent | None: ...

    async def cancel(self, countdown_id: str | None = None) -> bool: ...


class _LocalPower:
    def __init__(self, app: Reframe) -> None:
        self._app = app

    @property
    def pending(self) -> PowerCountdownEvent | None:
        return self._app.power.pending

    async def cancel(self, countdown_id: str | None = None) -> bool:
        return self._app.power.cancel(countdown_id)


class OwnerJobs:
    """Jobs drafted and named in this process, as ``Reframe.jobs`` drafts them, and validated
    by the queue's owner: its tools and encoder statuses decide, and no encoder detection runs
    here next to the owner's encodes."""

    def __init__(
        self, app: Reframe, validate: Callable[[JobSettings], Awaitable[list[ValidationIssue]]]
    ) -> None:
        self._app = app
        self._validate = validate

    async def draft(
        self,
        source: str | os.PathLike[str] | MediaSource,
        preset: Preset | str | None = None,
        *,
        output: Path | None = None,
    ) -> JobDraft | ProbeError:
        app = self._app
        media = source if isinstance(source, MediaSource) else await app.sources.probe(source)
        if isinstance(media, ProbeError):
            return media
        chosen = preset if isinstance(preset, Preset) else find_preset(app, preset)
        if isinstance(chosen, str):
            raise ValueError(chosen)
        settings = app.settings_snapshot()
        naming = chosen.naming if chosen.naming is not None else settings.output.naming
        job, tracks, notes = await asyncio.to_thread(
            draft_from_preset,
            media,
            chosen,
            definitions=app.jobs.definitions,
            languages=settings.languages,
            container_codecs=False,
        )
        job, name, more = await app.jobs.name_job(job, media, naming=naming, output=output)
        track_issues = [
            i for i in tracks.issues if i.severity is Severity.ERROR or i.code.startswith("batch.")
        ]
        return JobDraft(
            job=job,
            decisions=tracks.decisions,
            subtitle_decisions=tracks.subtitle_decisions,
            naming=name,
            issues=[*track_issues, *await self._validate(job)],
            notes=[*notes, *more],
        )

    async def name_job(
        self,
        job: JobSettings,
        source: MediaSource,
        *,
        naming: NamingOptions | None = None,
        output: Path | None = None,
    ) -> tuple[JobSettings, NameResult, list[str]]:
        return await self._app.jobs.name_job(job, source, naming=naming, output=output)

    async def validate(
        self,
        job: JobSettings,
        source: MediaSource | None = None,
        *,
        naming: NamingOptions | None = None,
    ) -> list[ValidationIssue]:
        return await self._validate(job)


@dataclasses.dataclass
class QueueSession:
    """Where a command's jobs go: the in-process queue, or the owner's (``remote``), with the
    events, the countdown and the drafting that belong to it."""

    queue: QueueLike
    events: EventBus
    power: PowerLike
    jobs: _Drafts
    batch: BatchService
    settings: Callable[[], Awaitable[str]]
    """The when-done setting that applies to the jobs."""
    remote: RemoteQueue | None = None

    @property
    def lost(self) -> str | None:
        """Why the connection to the owner ended while the command ran."""
        return None if self.remote is None else self.remote.lost


class _CommandEnds(Exception):
    def __init__(self, code: int) -> None:
        super().__init__(code)
        self.code = code


async def connect_owner(
    data_dir: Path, *, config_dir: Path, cache_dir: Path, start: bool = True
) -> RemoteQueue | str:
    """The queue of the owner of ``data_dir`` (started for this command when none runs and
    ``start``), or why none can be used."""
    from reframe.remote import NoOwner, OwnerStopping, RemoteError, RemoteQueue, find_owner

    reason = "no Reframe server answered"
    for _ in range(OWNER_ATTEMPTS):
        found = await find_owner(data_dir, start=start)
        if isinstance(found, NoOwner):
            return found.reason
        try:
            return await RemoteQueue.connect(
                found, data_dir=data_dir, config_dir=config_dir, cache_dir=cache_dir
            )
        except OwnerStopping as exc:
            reason = str(exc)
        except RemoteError as exc:
            reason = str(exc)
            if exc.code != "connection.failed":  # a server that stopped after its health check
                break
    return reason


@asynccontextmanager
async def open_queue(
    app: Reframe, console: Console, *, in_process: bool, detach: bool = False
) -> AsyncIterator[QueueSession]:
    """The queue of ``encode`` and ``batch``: the owner's, else the in-process queue with a
    warning that says why (with ``detach`` there is no else: the command ends with 1)."""
    remote: RemoteQueue | None = None
    if not in_process:
        found = await connect_owner(
            app.data_dir, config_dir=app.config_dir, cache_dir=app.cache_dir
        )
        if isinstance(found, str):
            if detach:
                _error(f"--detach needs the Reframe server that owns the queue: {found}.")
                raise _CommandEnds(EXIT_FAILED)
            print(
                _one_line(
                    f"warning: no Reframe server can take the jobs ({found}): they run in this "
                    "process."
                ),
                file=sys.stderr,
            )
        else:
            remote = found
    if remote is None:
        app.capabilities.start()
        queue = get_queue(app)

        async def when_done() -> str:
            return app.settings_snapshot().queue.when_done

        yield QueueSession(
            queue=queue,
            events=app.events,
            power=_LocalPower(app),
            jobs=app.jobs,
            batch=app.batch,
            settings=when_done,
        )
        return
    endpoint = remote.owner.endpoint
    console.print(
        Text(
            printable(
                f"Queue: Reframe {remote.owner.version} (pid {endpoint.pid}), shared with the "
                "other Reframe programs of this data folder."
            ),
            style="dim",
        ),
        soft_wrap=True,
    )
    jobs = OwnerJobs(app, remote.validate)
    batch = BatchService(
        sources=app.sources, presets=app.presets, jobs=jobs, settings=app.settings_snapshot
    )
    try:
        yield QueueSession(
            queue=remote,
            events=remote.events,
            power=remote.power,
            jobs=jobs,
            batch=batch,
            settings=remote.when_done,
            remote=remote,
        )
    finally:
        await remote.close(detach=detach)


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
    detach: bool = False,
    in_process: bool | None = None,
) -> int:
    """``reframe encode``: one job per media file, queued, run, followed. Returns the exit
    code; Ctrl+C (the task is cancelled) cancels the jobs and returns 130. ``detach``: the
    jobs are queued and started in the owner, and the command ends."""
    in_process = in_process_default() if in_process is None else in_process
    if detach and in_process:
        _error("--detach needs the Reframe server: it cannot be used with --in-process.")
        return EXIT_USAGE
    console = make_console()
    async with open_reframe(detect=False) as app:
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
        try:
            async with open_queue(app, console, in_process=in_process, detach=detach) as session:
                return await _encode(session, found.files, chosen, output, console, detach)
        except _CommandEnds as end:
            return end.code


@dataclasses.dataclass
class Prepared:
    """What a command lines up for the queue (``reframe encode`` drafts, ``reframe batch``
    resolutions): the jobs with their labels, in queue order, and the files not queued. Filled
    while it is made, so a Ctrl+C in between still counts what was refused."""

    jobs: list[tuple[str, JobSettings]] = dataclasses.field(default_factory=list)
    not_queued: int = 0


async def _encode(
    session: QueueSession,
    files: Sequence[Path],
    preset: Preset,
    output: Path | None,
    console: Console,
    detach: bool,
) -> int:
    async def prepare(prepared: Prepared) -> None:
        await _draft_files(session.jobs, files, preset, output, console, prepared)

    return await _run_jobs(session, prepare, console, detach=detach)


async def _run_jobs(
    session: QueueSession,
    prepare: Callable[[Prepared], Awaitable[None]],
    console: Console,
    *,
    detach: bool = False,
) -> int:
    """Queue what ``prepare`` lines up, run it, follow it (progress, Ctrl+C, the summary) and
    wait for a when-done countdown that its jobs started; return the exit code. ``detach``:
    queue and start the jobs, print their ids and return."""
    # Subscribed before the queue starts: the when-done countdown begins as the last job ends.
    countdown = session.events.subscribe(types={"power.countdown"})
    try:
        code, queued = await _queue_jobs(session, prepare, console, detach=detach)
        if code == EXIT_INTERRUPTED or not queued or detach or session.lost is not None:
            return code
        try:
            when_done = await session.settings()
        except QueueError:
            return code
        stopped = await follow_countdown(when_done, session.power, countdown, console)
        return code if stopped is None else stopped
    finally:
        countdown.close()


async def _draft_files(
    jobs: _Drafts,
    files: Sequence[Path],
    preset: Preset,
    output: Path | None,
    console: Console,
    prepared: Prepared,
) -> None:
    """``reframe encode``: draft every file; the files with errors are listed, not queued.
    No job writes another file of the command or the output of an earlier job
    (:class:`~reframe.jobs.OutputClaims`): such a file is not queued either."""
    total = len(files)
    width = len(str(total))
    console.print(Text(printable(f"Preset: {preset.name}")), soft_wrap=True)
    labels = [f"[{number:>{width}}/{total}]" for number in range(1, total + 1)]
    # OutputClaims stats the files (links, hard links): in a worker thread.
    claims = await asyncio.to_thread(
        OutputClaims,
        {file: f"{label} {file.name}" for file, label in zip(files, labels, strict=True)},
    )
    for label, file in zip(labels, files, strict=True):
        draft = await jobs.draft(file, preset, output=output)
        if isinstance(draft, ProbeError):
            prepared.not_queued += 1
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
        if not has_errors(draft.issues):
            conflicts = await asyncio.to_thread(claims.check, draft.job, f"{label} {file.name}")
            if conflicts:
                draft = draft.model_copy(update={"issues": _with_claims(draft.issues, conflicts)})
        if has_errors(draft.issues):
            prepared.not_queued += 1
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
        render_issues(console, draft.issues, severities=(Severity.WARNING,), indent=len(label) + 1)
        prepared.jobs.append((label, draft.job))


def _with_claims(
    issues: Sequence[ValidationIssue], conflicts: Sequence[ValidationIssue]
) -> list[ValidationIssue]:
    """A draft's issues with :class:`~reframe.jobs.OutputClaims`' errors. An output that is a
    source of the command is never overwritten: the ``output.overwrite`` warning ("will be
    replaced") would say the opposite and is left out, as ``reframe batch`` does."""
    if any(conflict.code == "batch.output_is_source" for conflict in conflicts):
        issues = [issue for issue in issues if issue.code != "output.overwrite"]
    return [*issues, *conflicts]


async def _queue_jobs(
    session: QueueSession,
    prepare: Callable[[Prepared], Awaitable[None]],
    console: Console,
    *,
    detach: bool = False,
) -> tuple[int, bool]:
    queue = session.queue
    subscription = session.events.subscribe(types={"job.state", "job.progress"})
    labels: dict[str, str] = {}
    ids: list[str] = []
    prepared = Prepared()
    view: EncodeView | None = None
    failed = 0
    try:
        await prepare(prepared)
        for label, settings in prepared.jobs:
            # At the end: with several clients, "at the front" would let each command pass
            # the ones before it.
            job = await queue.add(settings)
            ids.append(job.id)
            labels[job.id] = label
            if job.state is JobState.FAILED:
                failed += 1
                console.print(
                    Text(f"{label} failed when it was queued:", style="bold red"), soft_wrap=True
                )
                render_issues(
                    console, job.issues, severities=(Severity.ERROR,), indent=len(label) + 1
                )
        if not ids:
            console.print(Text("Nothing to encode.", style="bold red"), soft_wrap=True)
            return EXIT_FAILED, False
        console.print(Text(f"Queued {_plural(len(ids), 'job')}."), soft_wrap=True)
        # Only our jobs: the store is shared, and other front ends' waiting jobs stay as
        # they are (``start(job_ids=…)``; the runner goes idle when ours have ended).
        queue.start(job_ids=ids)
        if detach:
            for job_id in ids:
                console.print(Text(f"{labels[job_id]} job {job_id}"), soft_wrap=True)
            console.print(
                Text(
                    "Detached: the jobs run on in the Reframe server (reframe queue list).",
                    style="bold",
                ),
                soft_wrap=True,
            )
            return (EXIT_OK if not failed and not prepared.not_queued else EXIT_FAILED), True
        view = EncodeView(console, labels)
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
        _summary(console, queue, ids, prepared.not_queued)
        return EXIT_INTERRUPTED, True
    except QueueError as exc:  # the owner refused a job or went away while they were added
        if view is not None:
            view.close()
            view = None
        _error(f"the jobs cannot be queued: {exc}")
        _summary(console, queue, ids, prepared.not_queued)
        return EXIT_FAILED, bool(ids)
    finally:
        subscription.close()
        if view is not None:
            view.close()
    finals = _summary(console, queue, ids, prepared.not_queued)
    if session.lost is not None:
        waiting = [job.id[:SHORT_ID] for job in finals if job.state is JobState.WAITING]
        left = (
            f" The waiting jobs stay in the queue, not started: reframe queue retry ID starts "
            f"one, reframe queue cancel ID cancels it ({', '.join(waiting)})."
            if waiting
            else ""
        )
        _error(f"{session.lost}: its running jobs were interrupted.{left}")
    all_done = all(job.state is JobState.DONE for job in finals)
    return (EXIT_OK if all_done and not prepared.not_queued else EXIT_FAILED), True


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
    """Ctrl+C: cancel our waiting jobs, then our running ones (each cancel kills the process
    tree and removes the partial file), and wait for them to end. Only ``cancel(job_id)`` for
    our own ids: ``cancel()`` without an id, or ``stop()``, would also reach other front ends'
    jobs in the shared queue. Waiting jobs first: a cancelled running job frees a slot that
    one of them would take."""
    jobs = [job for job in (queue.get(j) for j in ids) if job is not None]
    waiting = [job.id for job in jobs if job.state is JobState.WAITING]
    active = [job.id for job in jobs if job.state in (JobState.RUNNING, JobState.PAUSED)]
    try:
        for job_id in [*waiting, *active]:
            with contextlib.suppress(UnknownJobError):  # removed meanwhile
                await queue.cancel(job_id)
        async with asyncio.timeout(CANCEL_WAIT):
            await queue.wait(ids)
    except TimeoutError:
        _error(f"the jobs did not end within {CANCEL_WAIT:g} s after they were cancelled.")
    except QueueError as exc:
        _error(f"the jobs cannot be cancelled: {exc}")


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


def _unicode(console: Console) -> bool:
    return (console.encoding or "").lower().replace("_", "-").startswith("utf")


def _counts(issues: Sequence[ValidationIssue]) -> str:
    """``1 error, 2 warnings`` (only the severities that occur)."""
    parts = []
    for severity, word in ((Severity.ERROR, "error"), (Severity.WARNING, "warning")):
        count = sum(1 for issue in issues if issue.severity is severity)
        if count:
            parts.append(_plural(count, word))
    return ", ".join(parts)


def render_group(console: Console, group: BatchGroup, number: int, total: int) -> None:
    """``Group 1 of 1: Anime Show S01 · 12 files · standard match``, then each file with its
    episode and, for a near member, how it differs."""
    files = _plural(len(group.members), "file")
    head = f"Group {number} of {total}: {group.name} · {files} · {group.level} match"
    console.print(Text(printable(head), style="bold"), soft_wrap=True)
    warn = ROW_MARKS["warning"] if _unicode(console) else ROW_ASCII["warning"]
    # A member labelled by its file name (no episode, two releases of one episode) shows the
    # name once, without a label column.
    labels = [
        None if label == member.path.name else printable(label)
        for label, member in zip(
            episode_labels([member.path for member in group.members]), group.members, strict=True
        )
    ]
    width = max((len(label) for label in labels if label is not None), default=0)
    for label, member in zip(labels, group.members, strict=True):
        line = Text(printable(member.path.name))
        if member.path == group.representative:
            line.append(" (representative)", style="dim")
        if member.match == "near":
            # The differences name track titles from the file.
            line.append(printable(f"  {warn} {'; '.join(member.differences)}"), style="yellow")
        if label is None:
            _indented(console, line)
            continue
        first = f"{'':{_INDENT}}{label:<{width}}  "
        _indented(console, line, len(first), first=first)


def render_matrix(console: Console, resolution: BatchResolution) -> None:
    """The column legend, the matrix (:func:`matrix_lines`), then each file's errors and
    warnings and the batch's issues."""
    unicode = _unicode(console)
    _section(console, "Columns")
    for column in resolution.columns:
        if column.kind not in ("audio", "subtitle"):
            continue
        short, _, rest = column.label.partition(" ")
        _indented(console, Text(printable(rest)), _INDENT + 4, first=f"{'':{_INDENT}}{short:<3} ")
    console.print()
    # Row labels and output names come from file names; printable keeps the columns: each
    # control character becomes one U+FFFD.
    for line in matrix_lines(resolution, unicode=unicode):
        console.print(Text(printable(line)), soft_wrap=True, crop=False)
    # The matrix's row labels (with the season when the rows span seasons).
    labels = episode_labels([row.path for row in resolution.rows])
    problems = [
        (label, row)
        for label, row in zip(labels, resolution.rows, strict=True)
        if any(i.severity is not Severity.INFO for i in row.issues)
    ]
    if problems or resolution.issues:
        _section(console, "Problems")
    for label, row in problems:
        shown = [i for i in row.issues if i.severity is not Severity.INFO]
        head = f"{'':{_INDENT}}{label}: {_counts(shown)}"
        console.print(Text(printable(head), style="bold"), soft_wrap=True)
        render_issues(console, shown, severities=(Severity.ERROR, Severity.WARNING), indent=4)
    render_issues(console, resolution.issues)


def _batch_summary(resolutions: Sequence[BatchResolution], unreadable: int) -> tuple[int, int]:
    """(files that can be queued, files that cannot)."""
    rows = [row for resolution in resolutions for row in resolution.rows]
    good = sum(1 for row in rows if row.status != "error" and row.job is not None)
    return good, len(rows) - good + unreadable


def _dry_run_line(good: int, bad: int, left_out: int) -> str:
    """``Dry run: 10 of 12 files can be queued; 2 cannot (errors); 2 left out (already
    encoded).``"""
    line = f"Dry run: {good} of {_plural(good + bad, 'file')} can be queued"
    if bad:
        line += f"; {bad} cannot (errors)"
    if left_out:
        line += f"; {left_out} left out (already encoded)"
    return line + "."


async def run_batch(
    paths: Sequence[Path],
    *,
    preset: str | None,
    level: MatchLevel = "standard",
    dry_run: bool = False,
    recursive: bool = False,
    as_json: bool = False,
    detach: bool = False,
    in_process: bool | None = None,
) -> int:
    """``reframe batch``: group the media files, resolve the preset in every file of every
    group and print the groups and the resolution matrix; without ``--dry-run``, queue the
    files without errors in episode order and encode them as ``reframe encode`` does.
    The batch is resolved as a whole (``Reframe.batch.resolve_batch``): the name checks
    cover every group, and the outputs of an earlier run are left out. A dry run validates
    in this process, as ``reframe plan`` does. Returns the exit code."""
    if as_json and not dry_run:
        _error("--json needs --dry-run: the encode prints progress, not JSON.")
        return EXIT_USAGE
    in_process = in_process_default() if in_process is None else in_process
    if detach and (in_process or dry_run):
        option = "--in-process" if in_process else "--dry-run"
        _error(f"--detach needs the Reframe server: it cannot be used with {option}.")
        return EXIT_USAGE
    console = make_console()
    async with open_reframe(detect=False) as app:
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
        chosen = find_preset(app, preset)
        if isinstance(chosen, str):
            _error(chosen)
            return EXIT_USAGE
        if dry_run:
            app.capabilities.start()
            return await _batch(app.batch, None, chosen, found.files, level, console, as_json)
        try:
            async with open_queue(app, console, in_process=in_process, detach=detach) as session:
                return await _batch(
                    session.batch, session, chosen, found.files, level, console, as_json, detach
                )
        except _CommandEnds as end:
            return end.code


async def _batch(
    service: BatchService,
    session: QueueSession | None,
    chosen: Preset,
    files: Sequence[Path],
    level: MatchLevel,
    console: Console,
    as_json: bool,
    detach: bool = False,
) -> int:
    """The batch after its files and preset are known: resolve, print, and (with a
    ``session``) queue and follow the jobs."""
    grouping, resolutions = await service.resolve_batch(chosen, files, level=level)
    unreadable = [i for i in grouping.issues if i.severity is Severity.ERROR]
    left_out = [i for i in grouping.issues if i.severity is not Severity.ERROR]
    good, bad = _batch_summary(resolutions, len(unreadable))
    if as_json:
        _write_json_value(
            {
                "grouping": grouping.model_dump(mode="json"),
                "resolutions": [r.model_dump(mode="json") for r in resolutions],
            }
        )
        return EXIT_OK if not bad else EXIT_FAILED
    console.print(Text(printable(f"Preset: {chosen.name}")), soft_wrap=True)
    if unreadable:
        _section(console, "Files that cannot be read")
        render_issues(console, unreadable)
    if left_out:
        _section(console, "Already encoded (left out of the batch)")
        render_issues(console, left_out)
    for number, (group, resolution) in enumerate(
        zip(grouping.groups, resolutions, strict=True), start=1
    ):
        console.print()
        render_group(console, group, number, len(grouping.groups))
        render_matrix(console, resolution)
    console.print()
    if session is None:
        line = _dry_run_line(good, bad, len(left_out))
        console.print(Text(line, style="bold"), soft_wrap=True)
        return EXIT_OK if not bad else EXIT_FAILED

    async def prepare(prepared: Prepared) -> None:
        prepared.not_queued += len(unreadable)
        rows = [row for resolution in resolutions for row in resolution.rows]
        width = len(str(len(rows)))
        for number, row in enumerate(rows, start=1):
            label = f"[{number:>{width}}/{len(rows)}]"
            target = row.job.output.path if row.job is not None else None
            console.print(
                Text(printable(f"{label} {row.path.name} → {target or NONE}")),
                soft_wrap=True,
            )
            if row.job is None or row.status == "error":
                prepared.not_queued += 1
                console.print(
                    Text(
                        f"{' ' * len(label)} not queued: {issue_counts(row.issues)} (see Problems)",
                        style="bold red",
                    ),
                    soft_wrap=True,
                )
                continue
            prepared.jobs.append((label, row.job))

    return await _run_jobs(session, prepare, console, detach=detach)


#: Seconds ``reframe encode`` waits for the when-done countdown to start after its last job
#: (the queue starts it as the job ends; this only covers a power service that needs a few
#: loop turns). Only when Settings → Queue → When done is ``sleep`` or ``shutdown``.
COUNTDOWN_START_WAIT = 2.0
#: Seconds to wait, after ``executing``, for the power service to finish the action.
COUNTDOWN_EXECUTE_WAIT = 30.0
#: Lines mode: a countdown line every this many seconds.
COUNTDOWN_LINE_STEP = 10
#: The when-done actions that ``reframe encode`` waits for. ``quit`` is not one: the command
#: ends by itself when its jobs end, and closing Reframe cancels it.
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
    when_done: str,
    power: PowerLike,
    subscription: Subscription,
    console: Console,
    *,
    start_wait: float | None = None,
) -> int | None:
    """After ``reframe encode``'s jobs: when the queue started a sleep or shutdown countdown
    (``when_done``, Settings → Queue → When done), show it until it ends. Ctrl+C cancels it
    (``power.cancel``) and gives :data:`EXIT_INTERRUPTED`; else ``None`` (the jobs' exit code
    stands). Nothing is waited for when the setting is another action."""
    if when_done not in WAITED_ACTIONS:
        return None
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
        try:
            cancelled = target is not None and await power.cancel(target.countdown_id)
        except QueueError as exc:
            _error(f"the countdown cannot be cancelled: {exc}")
            cancelled = False
        if target is not None and cancelled:
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
    if not named:
        _error("no media files to name.")
        return EXIT_NOT_FOUND
    if template is not None:
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
    return EXIT_FAILED if has_error else EXIT_OK


_EXIT_HELP_QUEUE_READ = (
    "Exit codes: 0 done; 1 there is no such job, or the saved queue cannot be read; 2 usage error."
)
_EXIT_HELP_QUEUE_ACTION = (
    "Exit codes: 0 done; 1 there is no such job, its state does not allow the action, or no "
    "Reframe server can be reached; 2 usage error."
)
#: Characters of a job id that ``reframe queue list`` shows. Every command takes any start of
#: an id that names one job.
SHORT_ID = 8
#: Seconds between two reads of a followed log.
LOG_POLL = 0.5
_ACTIVE_STATES = frozenset({JobState.RUNNING, JobState.PAUSED})


def find_job(jobs: Sequence[QueueJob], ref: str) -> QueueJob | str:
    """The job whose id is ``ref`` or starts with it, else the error message."""
    for job in jobs:
        if job.id == ref:
            return job
    matches = [job for job in jobs if ref and job.id.startswith(ref)]
    if len(matches) == 1:
        return matches[0]
    if not matches:
        return f"there is no job {ref} in the queue."
    return f"{ref} is the start of {len(matches)} job ids: give more of it."


def _job_name(job: QueueJob) -> str:
    return f"{job.id[:SHORT_ID]} {Path(job.settings.source.path).name}"


def queue_rows(jobs: Sequence[QueueJob]) -> list[str]:
    """The lines of ``reframe queue list``: position, id, state, progress, the source and the
    output, the error of a job that failed, then the counts."""
    header = ("#", "Id", "State", "Done", "Source → Output")
    rows = []
    for number, job in enumerate(jobs, start=1):
        progress = job.progress
        done = (
            f"{progress.percent:.1f}%"
            if progress is not None and job.state in _ACTIVE_STATES
            else ""
        )
        output = job.output_path or job.settings.output.path
        target = output if output is not None else NONE
        rows.append(
            (
                str(number),
                job.id[:SHORT_ID],
                job.state.value,
                done,
                printable(f"{Path(job.settings.source.path).name} → {target}"),
            )
        )
    widths = [max(len(row[i]) for row in [header, *rows]) for i in range(len(header) - 1)]

    def line(row: tuple[str, ...]) -> str:
        cells = [
            cell.rjust(width) if index in (0, 3) else cell.ljust(width)
            for index, (cell, width) in enumerate(zip(row, widths, strict=False))
        ]
        return "  ".join([*cells, row[-1]]).rstrip()

    lines = [line(header)]
    lead = " " * (sum(widths[:2]) + 4)
    for row, job in zip(rows, jobs, strict=True):
        lines.append(line(row))
        if job.error and job.state is not JobState.DONE:
            lines.append(printable(f"{lead}{job.state.value}: {_one_line(job.error)}"))
    counts = [
        f"{sum(1 for job in jobs if job.state is state)} {state.value}"
        for state in JobState
        if any(job.state is state for job in jobs)
    ]
    lines.append("")
    lines.append(f"{_plural(len(jobs), 'job')}: {', '.join(counts)}.")
    return lines


@asynccontextmanager
async def _owner_or_saved() -> AsyncIterator[tuple[RemoteQueue | None, list[QueueJob]]]:
    """The owner's queue when a server runs for this data folder (none is started), else the
    saved queue as the file holds it: no lock is taken and nothing is restored."""
    data_dir = paths.data_dir()
    found = await connect_owner(
        data_dir, config_dir=paths.config_dir(), cache_dir=paths.cache_dir(), start=False
    )
    if not isinstance(found, str):
        try:
            yield found, found.list()
        finally:
            await found.close(detach=True)
        return
    saved = await asyncio.to_thread(read_saved_queue, data_dir)
    if saved.problem is not None:
        print(_one_line(f"warning: the saved queue: {saved.problem}"), file=sys.stderr)
    yield None, saved.jobs


async def run_queue_list(*, as_json: bool) -> int:
    """``reframe queue list``: every job of the shared queue."""
    async with _owner_or_saved() as (remote, jobs):
        pass
    if as_json:
        _write_json_value([job.model_dump(mode="json") for job in jobs])
        return EXIT_OK
    console = make_console()
    if remote is None:
        console.print(
            Text("No Reframe server runs for this data folder: the saved queue.", style="dim"),
            soft_wrap=True,
        )
    if not jobs:
        console.print(Text("The queue is empty."), soft_wrap=True)
        return EXIT_OK
    for line in queue_rows(jobs):
        console.print(Text(line), soft_wrap=True, crop=False)
    return EXIT_OK


class _LogPrinter:
    """Prints a log file from where it stopped, whole lines only until :meth:`rest`."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.offset = 0
        self.held = b""

    def more(self) -> None:
        try:
            with self.path.open("rb") as file:
                file.seek(self.offset)
                data = file.read()
        except FileNotFoundError:
            return
        self.offset += len(data)
        *lines, self.held = (self.held + data).split(b"\n")
        for line in lines:
            self._write(line)

    def rest(self) -> None:
        self.more()
        if self.held:
            self._write(self.held)
            self.held = b""

    def _write(self, line: bytes) -> None:
        text = line.decode("utf-8", errors="replace").rstrip("\r")
        sys.stdout.write(printable(text) + "\n")
        sys.stdout.flush()


async def run_queue_log(ref: str, *, follow: bool) -> int:
    """``reframe queue log``: the job's log file; ``follow``: and what is written to it until
    the job ends."""
    data_dir = paths.data_dir()
    async with _owner_or_saved() as (remote, jobs):
        job = find_job(jobs, ref)
        if isinstance(job, str):
            _error(job)
            return EXIT_FAILED
        printer = _LogPrinter(job.log_path or log_file(data_dir, job.id))
        await asyncio.to_thread(printer.more)
        job_id = job.id

        def ended() -> bool:
            if remote is not None:
                current = remote.get(job_id)
                return remote.lost is not None or current is None or current.state in ENDED
            saved = read_saved_queue(data_dir)
            states = [j.state for j in saved.jobs if j.id == job_id]
            return not states or states[0] in ENDED

        while follow and not await asyncio.to_thread(ended):
            await asyncio.sleep(LOG_POLL)
            await asyncio.to_thread(printer.more)
        await asyncio.to_thread(printer.rest)
    return EXIT_OK


async def _owner_for(action: str) -> RemoteQueue | None:
    found = await connect_owner(
        paths.data_dir(), config_dir=paths.config_dir(), cache_dir=paths.cache_dir()
    )
    if isinstance(found, str):
        _error(f"{action} needs the Reframe server that owns the queue: {found}.")
        return None
    return found


_ALL_DONE = {
    "pause": "Paused every running job.",
    "resume": "Resumed every paused job.",
    "cancel": "Cancelled every job that had not ended.",
}


async def run_queue_action(action: str, refs: Sequence[str], *, every: bool) -> int:
    """``reframe queue pause|resume|cancel``: the named jobs, or ``every`` one."""
    if every == bool(refs):
        _error("name the jobs (an id or the start of one), or give --all.")
        return EXIT_USAGE
    remote = await _owner_for(f"reframe queue {action}")
    if remote is None:
        return EXIT_FAILED
    console = make_console()
    try:
        call = {"pause": remote.pause, "resume": remote.resume, "cancel": remote.cancel}[action]
        if every:
            await call()
            console.print(Text(_ALL_DONE[action]), soft_wrap=True)
            return EXIT_OK
        code = EXIT_OK
        for ref in refs:
            job = find_job(remote.list(), ref)
            if isinstance(job, str):
                _error(job)
                code = EXIT_FAILED
                continue
            try:
                await call(job.id)
            except QueueError as exc:
                _error(f"{_job_name(job)}: {exc}")
                code = EXIT_FAILED
                continue
            after = remote.get(job.id)
            state = after.state.value if after is not None else "removed"
            console.print(Text(printable(f"{_job_name(job)}: {state}")), soft_wrap=True)
        return code
    finally:
        await remote.close(detach=True)


async def run_queue_retry(ref: str) -> int:
    """``reframe queue retry``: a failed, cancelled or interrupted job waits again, and a
    waiting job is started (it runs in the server, as a detached job)."""
    remote = await _owner_for("reframe queue retry")
    if remote is None:
        return EXIT_FAILED
    console = make_console()
    try:
        job = find_job(remote.list(), ref)
        if isinstance(job, str):
            _error(job)
            return EXIT_FAILED
        try:
            retried = await remote.retry(job.id)
        except QueueError as exc:
            _error(f"{_job_name(job)}: {exc}")
            return EXIT_FAILED
        if retried.state is not JobState.WAITING:
            console.print(
                Text(printable(f"{_job_name(job)}: {retried.state.value}"), style="bold red"),
                soft_wrap=True,
            )
            render_issues(console, retried.issues, severities=(Severity.ERROR,))
            return EXIT_FAILED
        remote.start(job_ids=[job.id])
        console.print(
            Text(printable(f"{_job_name(job)}: waiting; it starts when a slot is free.")),
            soft_wrap=True,
        )
        return EXIT_OK
    finally:
        await remote.close(detach=True)


async def run_queue_remove(ref: str) -> int:
    """``reframe queue remove``: a job that does not run, with its log."""
    remote = await _owner_for("reframe queue remove")
    if remote is None:
        return EXIT_FAILED
    try:
        job = find_job(remote.list(), ref)
        if isinstance(job, str):
            _error(job)
            return EXIT_FAILED
        try:
            await remote.remove(job.id)
        except QueueError as exc:
            _error(f"{_job_name(job)}: {exc}")
            return EXIT_FAILED
        make_console().print(Text(printable(f"Removed {_job_name(job)}.")), soft_wrap=True)
        return EXIT_OK
    finally:
        await remote.close(detach=True)


_EXIT_HELP_TOOLS_STATUS = "Exit codes: 0 ffmpeg and ffprobe can be used; 4 one of them cannot."
_EXIT_HELP_TOOLS_FETCH = (
    "Exit codes: 0 installed, or already installed with every file intact; 1 the download, "
    "the size or SHA-256 check, the archive or the version check failed, or no build is "
    "pinned for this computer; 2 usage error, unknown build, or no archive for the platform; "
    "130 interrupted (Ctrl+C: the download stops, and the last line says whether the build "
    "was installed before the interrupt)."
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
        install_dir = install_dir_for(app.data_dir, target, host)
        before = _marker_identity(install_dir)
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
            ended = await app.tasks.wait(info.id)
            marker = installed_build(install_dir)
            replaced = _marker_identity(install_dir) != before
            if ended.state is TaskState.DONE or (
                # The interrupt came after the swap (tool discovery, the clean-up): the new
                # build is in place.
                replaced and marker is not None and marker.get("sha256") == archive.sha256
            ):
                print(
                    printable(
                        f"FFmpeg {chosen.version} was installed into {install_dir} before the "
                        "interrupt."
                    ),
                    file=sys.stderr,
                )
            else:
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


def _marker_identity(install_dir: Path) -> tuple[int, int, int] | None:
    """The install marker's file (device, inode, modification time): a fetch writes a new
    one, so a change says that the build was replaced."""
    try:
        info = (install_dir / MARKER_NAME).stat()
    except OSError:
        return None
    return info.st_dev, info.st_ino, info.st_mtime_ns


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


class LevelChoice(StrEnum):
    """The ``--level`` choices of ``reframe batch``."""

    STRICT = "strict"
    STANDARD = "standard"
    LOOSE = "loose"


class ConflictChoice(StrEnum):
    """``--on-conflict`` of ``reframe presets import``."""

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
    """JSON on stdout: ``\\uXXXX`` escapes for a byte of a file name that is not UTF-8, and
    for every character that is not ASCII when stdout is not UTF-8."""
    encoding = (getattr(sys.stdout, "encoding", None) or "utf-8").lower().replace("_", "-")
    text = json_text(data, ensure_ascii=encoding not in ("utf-8", "utf8"), indent=2)
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
    export file, on stdout or in FILE."""
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
    text = json_text(document, ensure_ascii=False, indent=2) + "\n"
    try:
        await asyncio.to_thread(write_text_file, output, text)
    except OSError as exc:
        _error(f"{display_path(output)} cannot be written: {exc.strerror or exc}.")
        return EXIT_FAILED
    make_console().print(
        Text(printable(f"Exported {_plural(count, 'preset')} to {output}.")), soft_wrap=True
    )
    return EXIT_OK


#: The largest preset file ``reframe presets import`` reads (an export of every preset is a
#: few hundred KiB at most).
MAX_PRESET_FILE = 16 << 20


def _read_regular_file(path: Path, limit: int) -> bytes | str:
    """At most ``limit + 1`` bytes of the regular file ``path``, else why it is not read. The
    file is opened without blocking (a FIFO would wait for a writer) and checked after it is
    opened (``/dev/zero`` never ends)."""
    if path.is_dir():
        return "is a folder, not a preset file."
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NONBLOCK", 0)
    with os.fdopen(os.open(path, flags), "rb") as f:
        info = os.fstat(f.fileno())
        if stat.S_ISDIR(info.st_mode):
            return "is a folder, not a preset file."
        if not stat.S_ISREG(info.st_mode):
            return "is not a regular file (a device, a pipe or a socket): it is not read."
        return f.read(limit + 1)


def read_preset_file(path: Path) -> dict[str, Any] | tuple[int, str]:
    """The JSON object of an export file (``-``: stdin), else ``(exit code, message)``. At most
    :data:`MAX_PRESET_FILE` bytes are read; a device or a FIFO is never read."""
    name = "stdin" if str(path) == "-" else display_path(path)
    try:
        if str(path) == "-":
            raw: bytes | str = sys.stdin.buffer.read(MAX_PRESET_FILE + 1)
        else:
            raw = _read_regular_file(path, MAX_PRESET_FILE)
    except FileNotFoundError:
        return EXIT_NOT_FOUND, f"{name}: the file does not exist."
    except IsADirectoryError:
        return EXIT_NOT_FOUND, f"{name} is a folder, not a preset file."
    except OSError as exc:
        return EXIT_NOT_FOUND, f"{name} cannot be read: {exc.strerror or exc}."
    if isinstance(raw, str):
        return EXIT_NOT_FOUND, f"{name} {raw}"
    if len(raw) > MAX_PRESET_FILE:
        return (
            EXIT_FAILED,
            f"{name} is not a Reframe preset file: it is larger than {MAX_PRESET_FILE} bytes.",
        )
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
        detach: Annotated[
            bool,
            typer.Option(
                "--detach",
                help="Queue the jobs in the Reframe server, start them, print their ids and "
                "end: they run on without this command (reframe queue list follows them).",
            ),
        ] = False,
        in_process: Annotated[
            bool,
            typer.Option(
                "--in-process",
                envvar=IN_PROCESS_ENV,
                help="Run the jobs in this process instead of the Reframe server that every "
                "Reframe program of this data folder shares. They are saved only when no other "
                "process owns the queue, and the queue's parallel limit counts them apart.",
            ),
        ] = False,
    ) -> None:
        """Encode media files: one job per file, through the queue, with progress and ETA.

        The jobs go to the Reframe server that owns the queue of this data folder (one is
        started when none runs), at the end of the queue, and its parallel limit holds for
        every program. Each job is drafted from the preset and validated; a file whose job has
        errors is reported and not queued, the others are encoded. Outputs are named by the
        naming template (-o only with a single file); a job never writes another file of the
        command, an earlier job's output, or the output of another waiting or running job
        (that file is not queued). Ctrl+C cancels the running and waiting jobs of this command
        and removes their partial files; so does the end of this command in any other way,
        unless --detach."""
        _run(
            run_encode(
                paths,
                preset=preset,
                output=output,
                recursive=recursive,
                detach=detach,
                in_process=in_process,
            )
        )

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

    @app.command(epilog=_EXIT_HELP_BATCH)
    def batch(
        paths: Annotated[
            list[Path],
            typer.Argument(
                help="Season folders (their media files) and media files.",
                metavar="DIR…",
                readable=False,
            ),
        ],
        preset: _PresetOption = None,
        level: Annotated[
            LevelChoice,
            typer.Option(
                "--level",
                help="How alike files must be to form a group: strict (titles and order "
                "too), standard (codec, channels, language, role, order) or loose (codec "
                "family, language, role; any order).",
            ),
        ] = LevelChoice.STANDARD,
        dry_run: Annotated[
            bool,
            typer.Option("--dry-run", help="Print the groups and the matrix; encode nothing."),
        ] = False,
        recursive: Annotated[
            bool,
            typer.Option("--recursive", "-r", help="Also search the subfolders of folders."),
        ] = False,
        as_json: Annotated[
            bool,
            typer.Option(
                "--json", help="With --dry-run: print the groups and the matrices as JSON."
            ),
        ] = False,
        detach: Annotated[
            bool,
            typer.Option(
                "--detach",
                help="Queue the jobs in the Reframe server, start them, print their ids and "
                "end: they run on without this command (reframe queue list follows them).",
            ),
        ] = False,
        in_process: Annotated[
            bool,
            typer.Option(
                "--in-process",
                envvar=IN_PROCESS_ENV,
                help="Run the jobs in this process instead of the Reframe server that every "
                "Reframe program of this data folder shares. They are saved only when no other "
                "process owns the queue, and the queue's parallel limit counts them apart.",
            ),
        ] = False,
    ) -> None:
        """Season mode: group files with the same track layout, resolve the preset's track
        rules in every file, and encode the season.

        Prints each group (a file that differs a little is a near match, with how it
        differs) and its resolution matrix: one row per file in episode order, one column
        per track rule (✓ exact, ≈ matched after relaxing or one of several candidates,
        ✗ no match for a required rule, a dash: skipped), the output name, then each file's
        errors and warnings. A file of the batch is never overwritten, and a file that is
        the planned output of another file (an earlier run's output) is left out. Without
        --dry-run, the files without errors are queued in episode order and encoded as
        "reframe encode" does; the others are listed."""
        _run(
            run_batch(
                paths,
                preset=preset,
                level=level.value,
                dry_run=dry_run,
                recursive=recursive,
                as_json=as_json,
                detach=detach,
                in_process=in_process,
            )
        )

    queue_app = typer.Typer(
        no_args_is_help=True,
        help="The queue that the Reframe programs of this data folder share: list its jobs, "
        "read a log, pause, resume, cancel, retry or remove jobs. A job is named by its id or "
        "any start of it that names one job.",
    )
    app.add_typer(queue_app, name="queue")

    @queue_app.command("list", epilog=_EXIT_HELP_QUEUE_READ)
    def queue_list(
        as_json: Annotated[
            bool, typer.Option("--json", help="Print the jobs (QueueJob models) as JSON.")
        ] = False,
    ) -> None:
        """List the jobs in queue order: id, state, progress, source and output. With no
        Reframe server running, the saved queue is read as it is (nothing is started)."""
        _run(run_queue_list(as_json=as_json))

    @queue_app.command("log", epilog=_EXIT_HELP_QUEUE_READ)
    def queue_log(
        job: _JobRef,
        follow: Annotated[
            bool,
            typer.Option("--follow", "-f", help="Print what is written until the job ends."),
        ] = False,
    ) -> None:
        """Print a job's log: the command lines, the tool output and the timing of each run."""
        _run(run_queue_log(job, follow=follow))

    @queue_app.command("pause", epilog=_EXIT_HELP_QUEUE_ACTION)
    def queue_pause(jobs: _JobRefs = None, every: _All = False) -> None:
        """Pause running jobs (their processes are suspended)."""
        _run(run_queue_action("pause", jobs or [], every=every))

    @queue_app.command("resume", epilog=_EXIT_HELP_QUEUE_ACTION)
    def queue_resume(jobs: _JobRefs = None, every: _All = False) -> None:
        """Resume paused jobs."""
        _run(run_queue_action("resume", jobs or [], every=every))

    @queue_app.command("cancel", epilog=_EXIT_HELP_QUEUE_ACTION)
    def queue_cancel(jobs: _JobRefs = None, every: _All = False) -> None:
        """Cancel jobs: a waiting one is not run, a running one is stopped and its partial
        file removed. --all cancels every job that has not ended, of every program."""
        _run(run_queue_action("cancel", jobs or [], every=every))

    @queue_app.command("retry", epilog=_EXIT_HELP_QUEUE_ACTION)
    def queue_retry(job: _JobRef) -> None:
        """Run a failed, cancelled or interrupted job again, or start a waiting one: it waits
        at its place in the queue and starts when a slot is free, in the server, without this
        command."""
        _run(run_queue_retry(job))

    @queue_app.command("remove", epilog=_EXIT_HELP_QUEUE_ACTION)
    def queue_remove(job: _JobRef) -> None:
        """Remove a job that is not running or paused, with its log."""
        _run(run_queue_remove(job))

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
    one ``error:`` line."""

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
    except QueueError as exc:  # the queue's server refused a call or went away
        _error(str(exc))
        code = EXIT_FAILED
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
