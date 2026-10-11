"""Command-line entry point (``reframe``, C-15). Needs the ``[cli]`` extra (typer; rich comes
with it).

Commands (M1): ``reframe probe FILE [--json]`` and ``reframe version``. The other C-15 commands
come in M2.

Exit codes of ``reframe probe``:

- ``0``: the file was probed.
- ``1``: ffprobe could not read the file (not a media file, damaged, timed out).
- ``2``: wrong command-line usage (typer/click).
- ``3``: the file does not exist, is not a file, or cannot be read.
- ``4``: no usable ffprobe (missing, broken, too old, or cannot be started).

Errors are one line on stderr, never a traceback. ``--json`` prints only the ``MediaSource``
model on stdout. The human output uses rich: no colour when stdout is not a terminal or
``NO_COLOR`` is set, ASCII table borders when stdout cannot encode box-drawing characters, and
characters that stdout cannot encode are replaced (never a ``UnicodeEncodeError``).
"""

from __future__ import annotations

import asyncio
import io
import json
import os
import sys
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Annotated

from reframe import __version__, languages
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
from reframe.models.tools import ToolInfo, ToolOrigin
from reframe.service import ProbeError, ProbeErrorKind, Reframe, tool_usable

try:  # the [cli] extra; main() says so when it is missing
    import typer
    from rich import box
    from rich.console import Console
    from rich.table import Table
    from rich.text import Text
except ImportError:  # pragma: no cover - depends on the installed extras
    _CLI_EXTRA = False
else:
    _CLI_EXTRA = True

__all__ = [
    "EXIT_NOT_FOUND",
    "EXIT_NO_FFPROBE",
    "EXIT_OK",
    "EXIT_PROBE_FAILED",
    "EXIT_USAGE",
    "build_app",
    "main",
]

EXIT_OK = 0
EXIT_PROBE_FAILED = 1
EXIT_USAGE = 2
EXIT_NOT_FOUND = 3
EXIT_NO_FFPROBE = 4

_EXIT_HELP = (
    "Exit codes: 0 probed; 1 ffprobe could not read the file; 2 usage error; "
    "3 file missing or unreadable; 4 no usable ffprobe."
)

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


def _one_line(text: str) -> str:
    return " ".join(text.split())


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
        delay = [f"delay {round(s.start_time * 1000):+d} ms"] if s.start_time else []
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
    console.print(Text(source.ref.path.name, style="bold"))
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
    async with await Reframe.create() as app:
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
        code = asyncio.run(run_probe(file, as_json=as_json))
        if code:
            raise typer.Exit(code)

    return app


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
