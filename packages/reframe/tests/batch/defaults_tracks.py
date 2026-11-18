"""Hand-built source tracks for the batch default tests.

Streams are built without the prober, so they have only the roles and disposition flags that
a test gives them.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from reframe.models import (
    AudioCodecRule,
    AudioStream,
    BitrateInfo,
    BitrateSource,
    Disposition,
    MediaSource,
    RoleEvidence,
    SourceFingerprint,
    SourceRef,
    SubtitleStream,
    TrackRole,
    TrackRoleInfo,
)

_LAYOUTS = {1: "mono", 2: "stereo", 6: "5.1(side)", 8: "7.1"}


def role(kind: TrackRole, evidence: str = "title", detail: str | None = None) -> TrackRoleInfo:
    return TrackRoleInfo(role=kind, evidence=RoleEvidence(evidence), detail=detail)


def audio(
    index: int,
    language: str | None,
    codec: str = "ac3",
    channels: int = 6,
    kbps: float | None = None,
    *,
    lossless: bool = False,
    title: str | None = None,
    roles: list[TrackRoleInfo] | None = None,
    ietf: str | None = None,
    **flags: bool,
) -> AudioStream:
    """An audio track; ``kbps`` ``None`` = unknown bit rate; ``flags`` are dispositions."""
    bitrate = (
        BitrateInfo(value=round(kbps * 1000), source=BitrateSource.STREAM)
        if kbps is not None
        else BitrateInfo()
    )
    fields: dict[str, Any] = {}
    if codec == "dts" and lossless:
        fields |= {"profile": "DTS-HD MA", "display_codec": "DTS-HD MA"}
    if codec == "truehd":
        fields |= {"profile": "Dolby TrueHD + Dolby Atmos", "display_codec": "TrueHD Atmos"}
    return AudioStream(
        index=index,
        codec=codec,
        channels=channels,
        channel_layout=_LAYOUTS.get(channels),
        sample_rate=48000,
        language=language,
        language_ietf=ietf,
        title=title,
        lossless=lossless,
        bitrate=bitrate,
        disposition=Disposition(**flags),
        roles=roles or [],
        **fields,
    )


def subtitle(
    index: int,
    language: str | None,
    codec: str = "subrip",
    *,
    title: str | None = None,
    events: int | None = None,
    forced_events: int | None = None,
    roles: list[TrackRoleInfo] | None = None,
    ietf: str | None = None,
    **flags: bool,
) -> SubtitleStream:
    bitmap = codec in ("hdmv_pgs_subtitle", "dvd_subtitle")
    return SubtitleStream(
        index=index,
        codec=codec,
        subtitle_kind="bitmap" if bitmap else "text",
        language=language,
        language_ietf=ietf,
        title=title,
        event_count=events,
        event_count_source="stats_tag" if events is not None else None,
        forced_event_count=forced_events,
        disposition=Disposition(**flags),
        roles=roles or [],
    )


def source(
    audio_tracks: list[AudioStream] | None = None,
    subtitles: list[SubtitleStream] | None = None,
    name: str = "movie.mkv",
) -> MediaSource:
    return MediaSource(
        ref=SourceRef(path=Path("/media") / name, fingerprint=SourceFingerprint(size=0, mtime=0)),
        audio=audio_tracks or [],
        subtitles=subtitles or [],
    )


#: The four codec rules of the audio-defaults example: Hungarian and English 5.1 AC-3, stereo
#: AAC, and an Opus catch-all that re-encodes.
EXAMPLE_CODEC_RULES = [
    AudioCodecRule(
        languages=["hu"], source_channels="5.1_or_more", codec="ac3", mixdown="5.1",
        max_bitrate=320, if_fits="passthru",
    ),
    AudioCodecRule(
        languages=["en"], source_channels="5.1_or_more", codec="ac3", mixdown="5.1",
        max_bitrate=384, if_fits="passthru",
    ),
    AudioCodecRule(
        languages=None, source_channels="stereo_or_less", codec="aac", mixdown="stereo",
        max_bitrate=160, if_fits="passthru",
    ),
    AudioCodecRule(
        languages=None, source_channels="any", codec="libopus", mixdown="up_to_5.1",
        max_bitrate=256, if_fits="reencode",
    ),
]  # fmt: skip
