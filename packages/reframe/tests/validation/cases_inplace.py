"""Rule cases of remux-only and in-place metadata-edit jobs."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from reframe.metadata import remux_job


def in_place(s: Any) -> None:
    s.job = remux_job(s.job, s.source, edit_in_place=True)


def encode_first_audio(s: Any) -> None:
    s.job.audio[0].action = "encode"


def read_only_source(s: Any) -> None:
    s.fs.writable_file = lambda path: False


def writable_source(s: Any) -> None:
    s.fs.writable_file = lambda path: True


def other_output(s: Any) -> None:
    s.job.output.path = Path("/out/Movie (2019).mkv")


def default_audio(*indexes: int) -> Any:
    def mod(s: Any) -> None:
        for index in indexes:
            s.job.audio[index].metadata.default = True

    return mod


def cases(h: Any) -> list[Any]:
    case, both, err, warn = h.Case, h.both, h.ERR, h.WARN
    return [
        case(
            "inplace_encoded_track", "inplace.not_possible", "output.edit_in_place", err,
            both(in_place, encode_first_audio), in_place,
        ),
        case(
            "inplace_mp4_output", "inplace.not_possible", "output.edit_in_place", err,
            both(in_place, h.container("mp4")), both(in_place, h.video(passthrough=True)),
        ),
        case(
            "inplace_read_only_source", "inplace.source_not_writable", "output.edit_in_place",
            err, both(in_place, read_only_source), both(in_place, writable_source),
        ),
        case(
            "inplace_mkvpropedit_missing", "tool.mkvpropedit_missing", "output.edit_in_place",
            err, both(in_place, h.mkvpropedit(h.ToolStatus.MISSING)), in_place,
        ),
        case(
            "inplace_output_ignored", "inplace.output_ignored", "output.path", warn,
            both(in_place, other_output), in_place,
        ),
        case(
            "inplace_two_default_audio_tracks", "metadata.several_defaults",
            "audio[1].metadata.default", warn,
            both(in_place, default_audio(0, 1)), both(in_place, default_audio(1)),
        ),
    ]  # fmt: skip
