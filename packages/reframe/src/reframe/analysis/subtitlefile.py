"""An external subtitle file, read before it is added to a job: its format, its event count and
its character encoding. ffprobe runs through :func:`reframe.tools.run`; a file it cannot read,
or of a type a job cannot take, is a :class:`~reframe.probe.ProbeError`."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import Any

from reframe.analysis.subtitles import PGS, SupError, read_display_sets
from reframe.command.subtitles import EXTERNAL_FORMATS
from reframe.models.issues import Severity, ValidationIssue
from reframe.models.media import SubtitleFileInfo
from reframe.probe.ffprobe import PROBE_TIMEOUT, ProbeError, ProbeErrorKind, ProbeTool, run_json
from reframe.probe.names import BITMAP_SUBTITLE_CODECS
from reframe.textfile import ENCODING_SAMPLE, open_regular, read_charset
from reframe.tools import CancelToken

__all__ = ["ENCODING_SAMPLE", "inspect_subtitle_file"]


def _display_sets(path: Path) -> int | None:
    try:
        with open_regular(path) as file:
            return read_display_sets(file).count
    except (OSError, SupError):
        return None


def _warning(code: str, path: str, message: str) -> ValidationIssue:
    return ValidationIssue(severity=Severity.WARNING, code=code, path=path, message=message)


def _subtitle_stream(data: dict[str, Any]) -> dict[str, Any] | None:
    streams = data.get("streams")
    if not isinstance(streams, list):
        return None
    for stream in streams:
        if isinstance(stream, dict) and stream.get("codec_type") == "subtitle":
            return stream
    return None


def _count(value: object) -> int | None:
    # With -count_packets, ffprobe leaves nb_read_packets out when it read no packet.
    if value is None:
        return 0
    try:
        count = int(str(value))
    except ValueError:
        return None
    return count if count >= 0 else None


async def inspect_subtitle_file(
    path: str | os.PathLike[str], tool: ProbeTool, *, cancel: CancelToken | None = None
) -> SubtitleFileInfo | ProbeError:
    """The format, events and character encoding of the subtitle file ``path`` (an existing,
    readable file). A file whose type a job cannot take (by its name), or that ffprobe finds no
    subtitles in, is a ``FAILED`` :class:`~reframe.probe.ProbeError`."""
    file = Path(path)
    suffix = file.suffix.lower()
    if suffix not in EXTERNAL_FORMATS:
        known = ", ".join(sorted(EXTERNAL_FORMATS))
        return ProbeError(
            file,
            ProbeErrorKind.FAILED,
            f"{file.name} is not a subtitle file that a job can take: use a {known} file.",
        )
    argv = [tool.path, "-v", "error", "-of", "json", "-show_streams", "-count_packets"]
    data = await run_json(
        [*argv, "-i", str(file)], file, tool=tool, timeout=PROBE_TIMEOUT, cancel=cancel
    )
    if isinstance(data, ProbeError):
        return data
    stream = _subtitle_stream(data)
    if stream is None or not isinstance(stream.get("codec_name"), str):
        return ProbeError(file, ProbeErrorKind.FAILED, f"FFmpeg finds no subtitles in {file.name}.")
    codec: str = stream["codec_name"]
    expected = EXTERNAL_FORMATS[suffix][0]
    bitmap = codec in BITMAP_SUBTITLE_CODECS
    issues: list[ValidationIssue] = []
    if codec != expected:
        issues.append(
            _warning(
                "subtitle.format_mismatch",
                "path",
                f"{file.name} holds {codec} subtitles, not the {expected} that its name says: "
                f"give it the name ending of its format.",
            )
        )
    if codec == PGS:
        # A packet of the sup demuxer is a segment; the subtitle scan counts display sets.
        events = await asyncio.to_thread(_display_sets, file)
    else:
        events = _count(stream.get("nb_read_packets"))
    charset: str | None = None
    if not bitmap:
        try:
            charset = (await asyncio.to_thread(read_charset, file)).name
        except OSError as exc:
            return ProbeError(file, ProbeErrorKind.UNREADABLE, "The file cannot be read.", str(exc))
        if charset is None:
            issues.append(
                _warning(
                    "subtitle.charset_unknown",
                    "charset",
                    f"The character encoding of {file.name} was not detected (it is not "
                    "UTF-8): choose the one it was saved in.",
                )
            )
        elif charset.startswith("UTF-16"):
            issues.append(
                _warning(
                    "subtitle.utf16",
                    "charset",
                    f"{file.name} is UTF-16, which FFmpeg reads wrongly: an event whose text "
                    "starts with a letter that is not ASCII loses that letter. Save the file as "
                    "UTF-8 first.",
                )
            )
    if events == 0:
        issues.append(_warning("subtitle.no_events", "path", f"{file.name} has no subtitles."))
    return SubtitleFileInfo(
        path=file, format=codec, bitmap=bitmap, charset=charset, events=events, issues=issues
    )
