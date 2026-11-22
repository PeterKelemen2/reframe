"""Commercial display names for codecs, profiles and containers, from the names ffprobe prints.

Profile strings are those of the pinned FFmpeg build; ``tests/probe/test_names.py`` checks them.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import PurePath

__all__ = [
    "BITMAP_SUBTITLE_CODECS",
    "FORCED_ONLY_SUBTITLE_CODECS",
    "LOSSLESS_AUDIO_CODECS",
    "LOSSLESS_DTS_PROFILES",
    "audio_display_name",
    "codec_name",
    "container_display_name",
    "is_lossless_audio",
    "subtitle_display_name",
    "video_display_name",
]

#: ffprobe's placeholder when a codec has profiles but the stream's is not known.
_NO_PROFILE = frozenset({"", "unknown"})

_VIDEO_BASE: Mapping[str, str] = {
    "h264": "H.264",
    "hevc": "HEVC",
    "av1": "AV1",
    "vp9": "VP9",
    "vp8": "VP8",
    "vvc": "VVC",
    "mpeg2video": "MPEG-2",
    "mpeg1video": "MPEG-1",
    "mpeg4": "MPEG-4 Visual",
    "msmpeg4v3": "MS MPEG-4 v3",
    "vc1": "VC-1",
    "wmv3": "WMV9",
    "prores": "ProRes",
    "dnxhd": "DNxHD",
    "mjpeg": "MJPEG",
    "theora": "Theora",
    "ffv1": "FFV1",
    "h263": "H.263",
}

#: Profiles that are the codec's default and add nothing to the name.
_DEFAULT_VIDEO_PROFILE: Mapping[str, str] = {"av1": "Main", "vp9": "Profile 0"}


def video_display_name(codec: str | None, profile: str | None) -> str | None:
    """The display name of a video codec and profile; ``None`` without a codec."""
    if not codec:
        return None
    base = _VIDEO_BASE.get(codec, codec)
    if profile is None or profile in _NO_PROFILE or _DEFAULT_VIDEO_PROFILE.get(codec) == profile:
        return base
    return f"{base} {profile}"


_AAC_PROFILES: Mapping[str, str] = {
    "LC": "AAC-LC",
    "HE-AAC": "HE-AAC",
    "HE-AACv2": "HE-AACv2",
    "LD": "AAC-LD",
    "ELD": "AAC-ELD",
    "Main": "AAC Main",
    "SSR": "AAC SSR",
    "LTP": "AAC LTP",
    "xHE-AAC": "xHE-AAC",
}

_DTS_PROFILES: Mapping[str, str] = {
    "DTS": "DTS",
    "DTS-ES": "DTS-ES",
    "DTS 96/24": "DTS 96/24",
    "DTS-HD HRA": "DTS-HD HRA",
    "DTS-HD MA": "DTS-HD MA",
    "DTS-HD MA + DTS:X": "DTS:X",
    "DTS-HD MA + DTS:X IMAX": "DTS:X IMAX",
    "DTS Express": "DTS Express",
}

#: DTS profiles with a lossless (XLL) extension.
LOSSLESS_DTS_PROFILES = frozenset({"DTS-HD MA", "DTS-HD MA + DTS:X", "DTS-HD MA + DTS:X IMAX"})

#: ``codec_name`` → ``{profile: name}``; a profile not in the table gets the base name.
_AUDIO_PROFILES: Mapping[str, Mapping[str, str]] = {
    "aac": _AAC_PROFILES,
    "aac_latm": _AAC_PROFILES,
    "dts": _DTS_PROFILES,
    "eac3": {"Dolby Digital Plus + Dolby Atmos": "E-AC-3 Atmos"},
    "truehd": {"Dolby TrueHD + Dolby Atmos": "TrueHD Atmos"},
}

_AUDIO_BASE: Mapping[str, str] = {
    "aac": "AAC",
    "aac_latm": "AAC",
    "ac3": "AC-3",
    "eac3": "E-AC-3",
    "ac4": "AC-4",
    "truehd": "TrueHD",
    "mlp": "MLP",
    "dts": "DTS",
    "flac": "FLAC",
    "alac": "ALAC",
    "opus": "Opus",
    "vorbis": "Vorbis",
    "mp3": "MP3",
    "mp2": "MP2",
    "mp1": "MP1",
    "wavpack": "WavPack",
    "tta": "TTA",
    "ape": "Monkey's Audio",
    "wmav2": "WMA",
    "wmapro": "WMA Pro",
    "wmalossless": "WMA Lossless",
    "amr_nb": "AMR-NB",
    "amr_wb": "AMR-WB",
}

#: Always lossless (PCM is matched by prefix, DTS by profile).
LOSSLESS_AUDIO_CODECS = frozenset(
    {"truehd", "mlp", "flac", "alac", "wavpack", "tta", "ape", "wmalossless"}
)


def audio_display_name(codec: str | None, profile: str | None) -> str | None:
    """The display name of an audio codec and profile; ``None`` without a codec."""
    if not codec:
        return None
    if codec.startswith("pcm_"):
        return "PCM"
    if profile and profile not in _NO_PROFILE:
        name = _AUDIO_PROFILES.get(codec, {}).get(profile)
        if name is not None:
            return name
    return _AUDIO_BASE.get(codec, codec)


def is_lossless_audio(codec: str | None, profile: str | None) -> bool:
    """Whether an audio codec and profile are lossless (PCM, and DTS with a lossless profile)."""
    if not codec:
        return False
    if codec.startswith("pcm_") or codec in LOSSLESS_AUDIO_CODECS:
        return True
    return codec == "dts" and profile in LOSSLESS_DTS_PROFILES


_SUBTITLE_NAMES: Mapping[str, str] = {
    "subrip": "SRT",
    "srt": "SRT",
    "ass": "ASS",
    "ssa": "SSA",
    "webvtt": "WebVTT",
    "mov_text": "mov_text",
    "text": "Text",
    "microdvd": "MicroDVD",
    "ttml": "TTML",
    "hdmv_pgs_subtitle": "PGS",
    "dvd_subtitle": "VobSub",
    "dvb_subtitle": "DVB",
    "dvb_teletext": "Teletext",
    "xsub": "XSUB",
    "eia_608": "CEA-608",
    "hdmv_text_subtitle": "HDMV Text",
    "arib_caption": "ARIB",
}

#: Subtitle codecs whose events are pictures, not text.
BITMAP_SUBTITLE_CODECS = frozenset({"hdmv_pgs_subtitle", "dvd_subtitle", "dvb_subtitle", "xsub"})
#: Subtitle codecs whose FFmpeg decoder has ``forced_subs_only`` (PGS, VobSub).
FORCED_ONLY_SUBTITLE_CODECS = frozenset({"hdmv_pgs_subtitle", "dvd_subtitle"})


def subtitle_display_name(codec: str | None) -> str | None:
    """The display name of a subtitle codec; the codec name itself when it is not known."""
    if not codec:
        return None
    return _SUBTITLE_NAMES.get(codec, codec)


def codec_name(codec: str) -> str:
    """The short display name of a video, audio or subtitle codec without its profile; the codec
    name itself when it is not known."""
    for table in (_VIDEO_BASE, _AUDIO_BASE, _SUBTITLE_NAMES):
        if codec in table:
            return table[codec]
    return codec


#: ``format_name`` → ``{file extension: name}``; ``""`` is the default for the format.
_CONTAINERS: Mapping[str, Mapping[str, str]] = {
    "matroska,webm": {"": "MKV", ".webm": "WebM", ".mka": "MKA", ".mks": "MKS"},
    "mov,mp4,m4a,3gp,3g2,mj2": {
        "": "MP4",
        ".mov": "MOV",
        ".m4v": "M4V",
        ".m4a": "M4A",
        ".3gp": "3GP",
        ".3g2": "3G2",
    },
    "mpegts": {"": "TS", ".m2ts": "M2TS", ".mts": "M2TS"},
    "mpeg": {"": "MPEG-PS", ".vob": "VOB"},
    "avi": {"": "AVI"},
    "asf": {"": "ASF", ".wmv": "WMV", ".wma": "WMA"},
    "flv": {"": "FLV"},
    "ogg": {"": "Ogg"},
    "mxf": {"": "MXF"},
    "srt": {"": "SRT"},
    "ass": {"": "ASS"},
    "webvtt": {"": "WebVTT"},
    "vobsub": {"": "VobSub"},
    "sup": {"": "SUP"},
}


def container_display_name(format_name: str | None, filename: str | PurePath | None) -> str | None:
    """The display name of a container, from ``format_name`` and the file extension. An unknown
    format gives its first name, upper-cased."""
    if not format_name:
        return None
    names = _CONTAINERS.get(format_name)
    if names is None:
        return format_name.split(",")[0].upper()
    ext = PurePath(filename).suffix.lower() if filename else ""
    return names.get(ext, names[""])
