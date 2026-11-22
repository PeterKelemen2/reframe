"""Parse the version output of FFmpeg and ffprobe.

A git master build has no release number, so its release series comes from its libavcodec and
libavformat major versions. A major version is bumped on master some time before the release
that carries it, so the minimum is checked against the library majors.
"""

from __future__ import annotations

import re
import shlex
from dataclasses import dataclass, field

__all__ = [
    "MIN_FFMPEG",
    "FfmpegVersion",
    "lib_major_to_series",
    "parse_ffmpeg_version",
]

#: The oldest FFmpeg release series that Reframe accepts.
MIN_FFMPEG: tuple[int, int] = (7, 0)

#: libavcodec / libavformat major version → FFmpeg release series, checked against real
#: builds (``tests/tools/data``). Older majors follow the same rule (series = major - 54) from
#: FFmpeg's release notes.
_VERIFIED_LIB_MAJORS = {60: 6, 61: 7, 62: 8, 63: 9}

_FIRST_LINE_RE = re.compile(
    r"^(?P<tool>ffmpeg|ffprobe) version (?P<version>.+?)(?:\s+Copyright\b.*)?$"
)
_RELEASE_RE = re.compile(r"^n?(?P<major>\d+)\.(?P<minor>\d+)(?:\.(?P<patch>\d+))?(?![\d.])")
_LIB_RE = re.compile(r"^(?P<name>lib\w+)\s+(?P<a>\d+)\.\s*(?P<b>\d+)\.\s*(?P<c>\d+)\s*/")


def lib_major_to_series(major: int) -> int:
    """The FFmpeg release series (major version) for a libavcodec/libavformat major."""
    return _VERIFIED_LIB_MAJORS.get(major, major - 54)


@dataclass(frozen=True)
class FfmpegVersion:
    """Parsed ``ffmpeg -version`` / ``ffprobe -version`` output."""

    tool: str
    """``ffmpeg`` or ``ffprobe`` (from the first line)."""
    version: str
    """The version token as printed."""
    release: tuple[int, int, int] | None
    """The release number; ``None`` for git master builds. A missing patch number is 0."""
    configuration: list[str] = field(default_factory=list)
    """The arguments of the ``configuration:`` line."""
    libraries: dict[str, tuple[int, int, int]] = field(default_factory=dict)
    """The library versions the binary runs with, by name."""

    @property
    def release_text(self) -> str | None:
        if self.release is None:
            return None
        return ".".join(map(str, self.release))

    @property
    def series(self) -> tuple[int, int] | None:
        """``(major, minor)`` of the release, or of the library versions for a master build."""
        if self.release is not None:
            return self.release[:2]
        majors = [
            lib_major_to_series(self.libraries[name][0])
            for name in ("libavcodec", "libavformat")
            if name in self.libraries
        ]
        if not majors:
            return None
        return (min(majors), 0)

    @property
    def build_flags(self) -> list[str]:
        """The ``--enable-*`` / ``--disable-*`` options of the configuration."""
        return [a for a in self.configuration if a.startswith(("--enable-", "--disable-"))]


def parse_ffmpeg_version(text: str) -> FfmpegVersion | None:
    """Parse ``ffmpeg -version`` (or ``ffprobe -version``) stdout. ``None`` if it is not one."""
    lines = [line.rstrip("\r") for line in text.splitlines()]
    first = next((line for line in lines if line.strip()), "")
    match = _FIRST_LINE_RE.match(first.strip())
    if match is None:
        return None
    version = match["version"].strip()
    release_match = _RELEASE_RE.match(version)
    release = None
    if release_match is not None:
        release = (
            int(release_match["major"]),
            int(release_match["minor"]),
            int(release_match["patch"] or 0),
        )
    configuration: list[str] = []
    libraries: dict[str, tuple[int, int, int]] = {}
    for line in lines[1:]:
        if line.startswith("configuration:"):
            raw = line.removeprefix("configuration:").strip()
            try:
                configuration = shlex.split(raw)
            except ValueError:  # unbalanced quotes: keep the words
                configuration = raw.split()
            continue
        lib = _LIB_RE.match(line)
        if lib is not None:
            libraries[lib["name"]] = (int(lib["a"]), int(lib["b"]), int(lib["c"]))
    return FfmpegVersion(
        tool=match["tool"],
        version=version,
        release=release,
        configuration=configuration,
        libraries=libraries,
    )
