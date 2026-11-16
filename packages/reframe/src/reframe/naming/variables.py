"""The template variables. The HandBrake variables keep HandBrake's names and meanings; the name
parts come from the parsed name, and the media variables from the job settings.
"""

from __future__ import annotations

from reframe.models.naming import NamingVariable, VariableGroup, VariableKind

__all__ = [
    "DATE_FORMATS",
    "VARIABLES",
    "VARIABLE_KINDS",
]


def _var(name: str, group: VariableGroup, kind: VariableKind, description: str) -> NamingVariable:
    return NamingVariable(name=name, group=group, kind=kind, description=description)


VARIABLES: tuple[NamingVariable, ...] = (
    # HandBrake parity.
    _var("source", "handbrake", "text", "The source name: the chosen name source (file or folder)"),
    _var("title", "handbrake", "number", "Title number: the file's index, as in HandBrake"),
    _var("chapters", "handbrake", "text", "Selected chapter range, for example 1-12"),
    _var("date", "handbrake", "date", "Current date (default 2026-10-11)"),
    _var("time", "handbrake", "date", "Current time (default 14-30)"),
    _var(
        "creation-date",
        "handbrake",
        "date",
        "Creation date from the source metadata (container creation_time, else the file system)",
    ),
    _var("creation-time", "handbrake", "date", "Creation time (as creation-date)"),
    _var("modification-date", "handbrake", "date", "The source file's modification date"),
    _var("modification-time", "handbrake", "date", "The source file's modification time"),
    _var("preset", "handbrake", "text", "Preset name"),
    _var("width", "handbrake", "number", "Output storage width"),
    _var("height", "handbrake", "number", "Output storage height"),
    _var("codec", "handbrake", "text", "Video format, for example H.265"),
    _var("encoder", "handbrake", "text", "Short encoder key: x265, svt_av1, nvenc_h265"),
    _var("encoder_bit_depth", "handbrake", "number", "Encoder bit depth: 8 or 10"),
    _var("quality_bitrate", "handbrake", "number", "Quality value (CRF/CQ) or the bitrate"),
    _var("quality_type", "handbrake", "text", "Q for constant quality, kbps for bitrate"),
    # Name parts.
    _var(
        "main_title",
        "name",
        "text",
        "The name cut at the first release tag (episodes keep the code and episode title)",
    ),
    _var("name", "name", "text", "Movie title or show name only"),
    _var("sub_title", "name", "text", "Episode title"),
    _var("season", "name", "number", "Season number ({season:02} gives 03)"),
    _var("episode", "name", "number", "Episode number"),
    _var("episode_code", "name", "text", "The episode code as written: S03E02, S03E02E03"),
    _var("year", "name", "number", "Release year"),
    _var("edition", "name", "text", "Director's Cut, Extended, IMAX…"),
    _var("source_type", "name", "text", "BluRay, UHD.BluRay, WEB-DL…"),
    _var("release_group", "name", "text", "Release group"),
    _var("file_name", "name", "text", "The raw file name, without extension"),
    _var("folder_name", "name", "text", "The raw name of the file's folder"),
    _var("container_title", "name", "text", "Title tag stored in the source container"),
    # Output media.
    _var("resolution", "media", "text", "2160p, 1080p, 720p, 576p, 480p, or WxH"),
    _var("hdr", "media", "text", "HDR10, HDR10+, DV, HLG; empty for SDR"),
    _var("acodec", "media", "text", "First output audio track's codec: AC-3"),
    _var("audio_channels", "media", "text", "First output audio track's channels: 5.1"),
    _var("audio_langs", "media", "text", "Output audio languages: HUN-ENG"),
    _var("sub_langs", "media", "text", "Output subtitle languages: HUN-ENG"),
    _var("container", "media", "text", "MKV, MP4, WebM"),
)

VARIABLE_KINDS: dict[str, VariableKind] = {v.name: v.kind for v in VARIABLES}

#: Default formats of the date variables: ISO dates and ``14-30`` times, because a system
#: short date can contain ``/`` and ``:``.
DATE_FORMATS = {
    "date": "%Y-%m-%d",
    "time": "%H-%M",
    "creation-date": "%Y-%m-%d",
    "creation-time": "%H-%M",
    "modification-date": "%Y-%m-%d",
    "modification-time": "%H-%M",
}
