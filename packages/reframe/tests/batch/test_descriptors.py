"""Track descriptors and fingerprints."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

from reframe.batch import describe_tracks, fingerprint
from reframe.batch.descriptors import (
    MATCH_LEVELS,
    codec_family,
    codec_label,
    hdr_type,
    language_code,
    stream_roles,
    track_label,
)
from reframe.models import (
    AudioStream,
    BitrateInfo,
    BitrateSource,
    Disposition,
    HdrFormat,
    HdrInfo,
    MediaSource,
    SourceRef,
    SubtitleStream,
    TrackRole,
    VideoStream,
)


def _load(name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        f"_reframe_batch_{name}", Path(__file__).with_name(f"{name}.py")
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


A = _load("anime")


def video(index: int = 0, width: int = 1920, height: int = 1080, **kw: object) -> VideoStream:
    return VideoStream.model_validate(
        {"index": index, "codec": "hevc", "width": width, "height": height, **kw}
    )


def audio(index: int, codec: str = "ac3", **kw: object) -> AudioStream:
    return AudioStream.model_validate({"index": index, "codec": codec, "channels": 6, **kw})


def subtitle(index: int, codec: str = "ass", **kw: object) -> SubtitleStream:
    return SubtitleStream.model_validate({"index": index, "codec": codec, **kw})


def source(*streams: VideoStream | AudioStream | SubtitleStream) -> MediaSource:
    return MediaSource(
        ref=SourceRef(path=Path("/m/x.mkv")),
        video=[s for s in streams if isinstance(s, VideoStream)],
        audio=[s for s in streams if isinstance(s, AudioStream)],
        subtitles=[s for s in streams if isinstance(s, SubtitleStream)],
    )


def test_descriptors_of_the_example_episode_with_the_commentary() -> None:
    e05 = A.recorded(1, 5)
    tracks = describe_tracks(e05)
    assert [(d.kind, d.index, d.position) for d in tracks] == [
        ("video", 0, 0),
        ("audio", 1, 0),
        ("audio", 2, 1),
        ("audio", 3, 2),
        ("subtitle", 4, 0),
        ("subtitle", 5, 1),
    ]
    assert [d.label for d in tracks] == [
        "H.264 Constrained Baseline 320x180",
        'jpn TrueHD 5.1 "Japanese"',
        'eng DTS-HD MA 5.1 "English Dub"',
        'eng AC-3 2.0 "Commentary"',
        'eng ASS "Signs & Songs"',
        'eng ASS "Full"',
    ]
    v, jpn, dub, commentary, signs, full = tracks
    assert (v.codec, v.codec_family, v.roles, v.channels) == ("h264", "h264", [], None)
    assert (jpn.codec, jpn.codec_family, jpn.profile, jpn.channels) == (
        "truehd",
        "truehd",
        "TrueHD",
        6,
    )
    assert (dub.codec, dub.codec_family, dub.profile) == ("dts", "dts", "DTS-HD MA")
    assert (jpn.language, dub.language) == ("ja", "en")
    assert jpn.flags.default
    assert not dub.flags.default
    assert jpn.roles == dub.roles == full.roles == [TrackRole.MAIN]
    assert commentary.roles == [TrackRole.COMMENTARY]
    assert commentary.flags.commentary
    assert commentary.bitrate == 96_000
    assert jpn.bitrate is None
    assert set(signs.roles) == {TrackRole.FORCED, TrackRole.SIGNS}
    assert (signs.codec_family, signs.title) == ("text", "Signs & Songs")


@pytest.mark.parametrize(
    ("stream", "family"),
    [
        (audio(1, "dts"), "dts"),
        (audio(1, "truehd"), "truehd"),
        (audio(1, "mlp"), "truehd"),
        (audio(1, "ac3"), "ac3"),
        (audio(1, "eac3"), "ac3"),
        (audio(1, "aac"), "aac"),
        (audio(1, "aac_latm"), "aac"),
        (audio(1, "mp2"), "mpeg_audio"),
        (audio(1, "mp3"), "mpeg_audio"),
        (audio(1, "pcm_s24le"), "pcm"),
        (audio(1, "flac"), "flac"),
        (audio(1, "opus"), "opus"),
        (audio(1, codec=None), None),  # type: ignore[arg-type]
        (subtitle(1, "subrip"), "text"),
        (subtitle(1, "ass"), "text"),
        (subtitle(1, "mov_text"), "text"),
        (subtitle(1, "hdmv_pgs_subtitle"), "bitmap"),
        (subtitle(1, "dvd_subtitle"), "bitmap"),
        (subtitle(1, "arib_caption"), "arib_caption"),
        (subtitle(1, codec=None), None),  # type: ignore[arg-type]
        (video(0, codec="hevc"), "hevc"),
    ],
)
def test_codec_family(
    stream: AudioStream | SubtitleStream | VideoStream, family: str | None
) -> None:
    assert codec_family(stream) == family


def test_codec_label() -> None:
    assert codec_label(audio(1, "dts", display_codec="DTS-HD MA")) == "DTS-HD MA"
    assert codec_label(audio(1, "eac3")) == "E-AC-3"
    assert codec_label(subtitle(1, "hdmv_pgs_subtitle")) == "PGS"
    assert codec_label(audio(1, "nellymoser")) == "nellymoser"
    assert codec_label(audio(1, codec=None)) == "unknown codec"  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("disposition", "roles"),
    [
        ({}, [TrackRole.MAIN]),
        ({"comment": True}, [TrackRole.COMMENTARY]),
        ({"visual_impaired": True}, [TrackRole.DESCRIPTION]),
        ({"clean_effects": True}, [TrackRole.MUSIC]),
    ],
)
def test_audio_roles_without_the_prober(
    disposition: dict[str, bool], roles: list[TrackRole]
) -> None:
    """Without the prober a source has no roles, so the disposition flags give them."""
    assert stream_roles(audio(1, disposition=Disposition(**disposition))) == roles


@pytest.mark.parametrize(
    ("disposition", "roles"),
    [
        ({}, [TrackRole.MAIN]),
        ({"forced": True}, [TrackRole.FORCED]),
        ({"hearing_impaired": True}, [TrackRole.SDH]),
        ({"captions": True}, [TrackRole.SDH]),
        ({"comment": True}, [TrackRole.COMMENTARY]),
        ({"forced": True, "hearing_impaired": True}, [TrackRole.FORCED, TrackRole.SDH]),
    ],
)
def test_subtitle_roles_without_the_prober(
    disposition: dict[str, bool], roles: list[TrackRole]
) -> None:
    assert stream_roles(subtitle(1, disposition=Disposition(**disposition))) == roles


def test_roles_of_the_prober_come_first_and_main_goes() -> None:
    track = subtitle(1, roles=[{"role": "main", "evidence": "flag"}], disposition={"forced": True})
    assert stream_roles(track) == [TrackRole.FORCED]
    signs = subtitle(
        1, roles=[{"role": "signs", "evidence": "title"}], disposition={"forced": True}
    )
    assert stream_roles(signs) == [TrackRole.SIGNS, TrackRole.FORCED]


def test_labels() -> None:
    (d,) = describe_tracks(source(audio(1, "eac3", language="hun", channels=2)))
    assert d.label == "hun E-AC-3 2.0"
    (d,) = describe_tracks(source(subtitle(3, "subrip", title="Full")))
    assert d.label == 'und SRT "Full"'
    assert track_label(d.model_copy(update={"codec": None, "title": None})) == "und unknown codec"
    (v,) = describe_tracks(source(video(0, display_codec="HEVC Main 10", language="eng")))
    assert v.label == "HEVC Main 10 1920x1080"
    assert v.language == "en"
    assert language_code(None) == "und"


def test_undetermined_languages_are_none() -> None:
    tracks = describe_tracks(
        source(audio(1, language="und"), audio(2), subtitle(3, language="qaa"))
    )
    assert [d.language for d in tracks] == [None, None, "qaa"]


def base() -> list[VideoStream | AudioStream | SubtitleStream]:
    return [
        video(0),
        audio(1, "truehd", language="jpn", title="Japanese", disposition={"default": True}),
        audio(2, "dts", language="eng", profile="DTS-HD MA", title="Dub"),
        subtitle(3, language="eng", title="Signs", disposition={"forced": True}),
        subtitle(4, language="eng", title="Full"),
    ]


def changed(position: int, **update: object) -> MediaSource:
    streams = base()
    streams[position] = streams[position].model_copy(update=update)
    return source(*streams)


def digests(media: MediaSource) -> dict[str, str]:
    return {level: fingerprint(media, level).digest for level in MATCH_LEVELS}


#: What each change does at each level: ``True`` = still the same group.
CASES = [
    ("nothing", source(*base()), (True, True, True)),
    ("a title", changed(2, title="English"), (False, True, True)),
    ("a flag", changed(1, disposition=Disposition()), (False, True, True)),
    ("a profile", changed(2, profile="DTS"), (False, True, True)),
    (
        "a bit rate",
        changed(2, bitrate=BitrateInfo(value=1_500_000, source=BitrateSource.STREAM)),
        (True, True, True),
    ),
    ("the channels", changed(2, channels=8), (False, False, True)),
    ("the codec in its family", changed(2, codec="dts", profile=None), (False, True, True)),
    (
        "DTS to E-AC-3",
        source(*base()[:2], audio(2, "eac3", language="eng", title="Dub"), *base()[3:]),
        (False, False, False),
    ),
    ("a language", changed(2, language="hun"), (False, False, False)),
    (
        "the order",
        source(
            base()[0],
            base()[2].model_copy(update={"index": 1}),
            base()[1].model_copy(update={"index": 2}),
            *base()[3:],
        ),
        (False, False, True),
    ),
    ("a role", changed(3, disposition=Disposition()), (False, False, False)),
    ("1080p to cropped scope", changed(0, height=800), (False, False, True)),
    ("1080p to 720p", changed(0, width=1280, height=720), (False, False, False)),
    ("HDR10", changed(0, hdr=HdrInfo(formats=[HdrFormat.HDR10])), (False, False, False)),
]


@pytest.mark.parametrize(("change", "media", "same"), CASES, ids=[c[0] for c in CASES])
def test_what_each_level_compares(change: str, media: MediaSource, same: tuple[bool, ...]) -> None:
    reference = digests(source(*base()))
    got = digests(media)
    assert tuple(got[level] == reference[level] for level in MATCH_LEVELS) == same, change


def test_ac3_and_eac3_are_one_family() -> None:
    ac3 = source(video(0), audio(1, "ac3", language="eng"))
    eac3 = source(video(0), audio(1, "eac3", language="eng"))
    same = [fingerprint(ac3, lv).digest == fingerprint(eac3, lv).digest for lv in MATCH_LEVELS]
    assert same == [False, False, True]


def test_fingerprint_fields() -> None:
    hdr = changed(0, hdr=HdrInfo(formats=[HdrFormat.HDR10, HdrFormat.DOLBY_VISION]))
    fp = fingerprint(hdr, "standard")
    assert (fp.level, fp.width, fp.height, fp.hdr) == (
        "standard",
        1920,
        1080,
        HdrFormat.DOLBY_VISION,
    )
    assert len(fp.tracks) == 5
    assert len(fp.digest) == 16
    empty = MediaSource(ref=SourceRef(path=Path("/m/a.mka")))
    assert (fingerprint(empty, "loose").width, hdr_type(empty)) == (None, None)


def test_the_example_episodes_share_a_fingerprint() -> None:
    e01, e02, e05, e11 = (A.recorded(1, n) for n in (1, 2, 5, 11))
    for level in MATCH_LEVELS:
        assert fingerprint(e01, level).digest == fingerprint(e02, level).digest
        assert fingerprint(e01, level).digest != fingerprint(e05, level).digest
        assert fingerprint(e01, level).digest != fingerprint(e11, level).digest
    # Season 2 of the same release: the same structure.
    assert fingerprint(A.recorded(2, 1), "strict").digest == fingerprint(e01, "strict").digest
