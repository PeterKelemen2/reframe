"""05 §C-16 "Done when": every HandBrake variable has a test. And the Reframe variables
(03 §Variables): name parts, output media."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from reframe.models import (
    AudioOutputTrack,
    AudioStream,
    AverageBitrate,
    Chapter,
    ChapterRange,
    ConstantQuality,
    ContainerInfo,
    ExternalSubtitle,
    FilterConfig,
    FilterSettings,
    HdrFormat,
    HdrInfo,
    JobSettings,
    MediaSource,
    NamingOptions,
    OutputSettings,
    SourceRef,
    SubtitleOutputTrack,
    SubtitleStream,
    TimeRange,
    TrackMetadata,
    VideoSettings,
    VideoStream,
)
from reframe.naming import VARIABLES, FileTimes, resolve_output_name
from reframe.naming.context import audio_channels_label, hdr_label, resolution_label
from reframe.naming.variables import HANDBRAKE_VARIABLES

FILE = Path("/media/Hacksaw.Ridge.2016.2160p.UHD.BluRay.HEVC-GRP/hacksawridge.mkv")
NOW = datetime(2026, 10, 11, 14, 30, 5).astimezone()


class _Fs:
    def __init__(self, times: FileTimes | None = None) -> None:
        self.times = times

    def list_files(self, folder: Path) -> list[str] | None:
        return None

    def file_times(self, file: Path) -> FileTimes | None:
        return self.times


def _job(**kwargs: Any) -> JobSettings:
    return JobSettings(source=SourceRef(path=FILE), **kwargs)


def _source(**kwargs: Any) -> MediaSource:
    video = VideoStream(index=0, codec="hevc", width=3840, height=2160, bit_depth=10)
    return MediaSource(ref=SourceRef(path=FILE), **{"video": [video], **kwargs})


def render(template: str, *, fs: _Fs | None = None, **kwargs: Any) -> str:
    """The rendered name of ``FILE`` for ``template`` (without ``.mkv``)."""
    options = NamingOptions(movie_template=template, episode_template=template)
    result = resolve_output_name(FILE, options, fs=fs or _Fs(), now=NOW, **kwargs)
    assert not result.issues, result.issues
    assert result.extension in ("mkv", "mp4", "m4v", "webm")
    return result.relative_path.removesuffix("." + result.extension)


# --------------------------------------------------------------------------- HandBrake parity


def test_there_are_17_handbrake_variables() -> None:
    assert HANDBRAKE_VARIABLES == (
        "source",
        "title",
        "chapters",
        "date",
        "time",
        "creation-date",
        "creation-time",
        "modification-date",
        "modification-time",
        "preset",
        "width",
        "height",
        "codec",
        "encoder",
        "encoder_bit_depth",
        "quality_bitrate",
        "quality_type",
    )


def test_hb_source_is_the_chosen_name_source() -> None:
    assert render("{source}") == "Hacksaw.Ridge.2016.2160p.UHD.BluRay.HEVC-GRP"
    assert render("{source}", root=None) == render("{source}")
    file_only = resolve_output_name(
        Path("/Movie.2016.1080p.mkv"), NamingOptions(movie_template="{source}"), fs=_Fs()
    )
    assert file_only.relative_path == "Movie.2016.1080p.mkv"


def test_hb_title_is_the_file_index() -> None:
    assert render("{source}-{title}").endswith("-1")
    assert render("{title:02}", title_index=3) == "03"


def test_hb_chapters() -> None:
    chapters = [Chapter(index=i, start=i * 60.0, end=(i + 1) * 60.0) for i in range(12)]
    assert render("x<{chapters}>", source=_source(chapters=chapters)) == "x1-12"
    assert render("x<{chapters}>", job=_job(range=ChapterRange(start=2, end=5))) == "x2-5"
    assert render("x<{chapters}>", job=_job(range=ChapterRange(start=3, end=3))) == "x3"
    assert (
        render(
            "x<{chapters}>", job=_job(range=TimeRange(start=10)), source=_source(chapters=chapters)
        )
        == "x"
    )
    assert render("x<{chapters}>") == "x"
    one = [Chapter(index=0, start=0, end=60)]
    assert render("x<{chapters}>", source=_source(chapters=one)) == "x1"


def test_hb_date_and_time() -> None:
    assert render("{date} {time}") == "2026-10-11 14-30"
    assert render("{date:%d.%m.%Y}") == "11.10.2026"
    assert render("{time:%H.%M.%S}") == "14.30.05"


def test_hb_creation_date_from_the_container() -> None:
    created = datetime(2020, 1, 2, 3, 4, 5, tzinfo=UTC)
    local = created.astimezone()
    source = _source(container=ContainerInfo(creation_time=created))
    assert render("{creation-date}", source=source) == local.strftime("%Y-%m-%d")
    assert render("{creation-time}", source=source) == local.strftime("%H-%M")
    assert render("{creation-date:%Y}", source=source) == local.strftime("%Y")


def test_hb_creation_date_falls_back_to_the_file_system() -> None:
    times = FileTimes(modified=NOW, created=datetime(2019, 5, 6, 7, 8).astimezone())
    assert render("{creation-date} {creation-time}", fs=_Fs(times)) == "2019-05-06 07-08"
    # Linux reports no creation time: the variable is empty.
    assert render("x<{creation-date}>", fs=_Fs(FileTimes(modified=NOW))) == "x"


def test_hb_modification_date_and_time() -> None:
    times = FileTimes(modified=datetime(2021, 12, 24, 18, 0).astimezone())
    assert render("{modification-date} {modification-time}", fs=_Fs(times)) == "2021-12-24 18-00"
    assert render("x<{modification-date}>") == "x"  # the file does not exist


def test_hb_preset() -> None:
    assert render("{preset}", job=_job(preset_name="H.265 MKV 1080p")) == "H.265 MKV 1080p"
    assert render("x<{preset}>") == "x"


def test_hb_width_and_height() -> None:
    assert render("{width}x{height}", output_size=(1920, 800)) == "1920x800"
    passthrough = _job(video=VideoSettings(passthrough=True))
    assert render("{width}x{height}", job=passthrough, source=_source()) == "3840x2160"
    assert render("x<{width}>", job=_job(), source=_source()) == "x"  # C-5 not asked


def test_hb_codec() -> None:
    assert render("{codec}", job=_job()) == "H.265"  # libx265, the default encoder
    assert render("{codec}", job=_job(video=VideoSettings(encoder="libsvtav1"))) == "AV1"
    assert render("{codec}", job=_job(video=VideoSettings(encoder="h264_nvenc"))) == "H.264"
    passthrough = _job(video=VideoSettings(passthrough=True))
    assert render("{codec}", job=passthrough, source=_source()) == "H.265"


@pytest.mark.parametrize(
    ("encoder", "key"),
    [
        ("libx265", "x265"),
        ("libx264", "x264"),
        ("libsvtav1", "svt_av1"),
        ("hevc_nvenc", "nvenc_h265"),
        ("av1_qsv", "qsv_av1"),
        ("hevc_vaapi", "vaapi_h265"),
        ("my_encoder", "my_encoder"),
    ],
)
def test_hb_encoder(encoder: str, key: str) -> None:
    assert render("{encoder}", job=_job(video=VideoSettings(encoder=encoder))) == key


def test_hb_encoder_bit_depth() -> None:
    assert render("{encoder_bit_depth}", job=_job(video=VideoSettings(bit_depth=10))) == "10"
    assert render("{encoder_bit_depth}", job=_job()) == "8"


def test_hb_quality_bitrate_and_type() -> None:
    crf = _job(video=VideoSettings(rate_control=ConstantQuality(value=22)))
    assert render("{quality_type}{quality_bitrate}", job=crf) == "Q22"
    crf = _job(video=VideoSettings(rate_control=ConstantQuality(value=18.5)))
    assert render("{quality_bitrate}", job=crf) == "18.5"
    abr = _job(video=VideoSettings(rate_control=AverageBitrate(kbps=6000)))
    assert render("{quality_bitrate}{quality_type}", job=abr) == "6000kbps"


def test_hb_video_variables_are_empty_without_a_job() -> None:
    template = "x<{codec}><{encoder}><{encoder_bit_depth}><{quality_bitrate}><{quality_type}>"
    assert render(template) == "x"


# --------------------------------------------------------------------------- name parts


def test_name_parts() -> None:
    episode = Path("/tv/The.Sopranos.S03E02.Proshai.Livushka.1080p.BluRay.REMUX-Kataklysm.mkv")
    template = (
        "{name}|{main_title}|{sub_title}|{season:02}|{episode:02}|{episode_code}|{source_type}|"
        "{release_group}|{file_name}|{folder_name}"
    )
    result = resolve_output_name(episode, NamingOptions(episode_template=template), fs=_Fs())
    assert result.variables["name"] == "The.Sopranos"
    assert result.variables["main_title"] == "The.Sopranos.S03E02.Proshai.Livushka"
    assert result.variables["sub_title"] == "Proshai.Livushka"
    assert result.variables["season"] == "3"
    assert result.variables["episode"] == "2"
    assert result.variables["episode_code"] == "S03E02"
    assert result.variables["source_type"] == "BluRay"
    assert result.variables["release_group"] == "Kataklysm"
    assert result.variables["file_name"] == episode.stem
    assert result.variables["folder_name"] == "tv"
    assert result.relative_path == (
        "The.Sopranos-The.Sopranos.S03E02.Proshai.Livushka-Proshai.Livushka-03-02-S03E02-"
        "BluRay-Kataklysm-The.Sopranos.S03E02.Proshai.Livushka.1080p.BluRay.REMUX-Kataklysm-tv.mkv"
    )


def test_year_and_edition() -> None:
    movie = Path("/m/Blade.Runner.1982.The.Final.Cut.REMASTERED.1080p.BluRay.x265-RARBG.mp4")
    result = resolve_output_name(
        movie, NamingOptions(movie_template="{name} ({year}) {edition}"), fs=_Fs()
    )
    assert result.relative_path == "Blade.Runner (1982) REMASTERED.mkv"


def test_container_title() -> None:
    source = _source(container=ContainerInfo(title="Hacksaw Ridge"))
    assert render("{container_title}", source=source) == "Hacksaw Ridge"
    assert render("x<{container_title}>") == "x"


def test_word_separator_applies_to_text_from_the_name_only() -> None:
    options = NamingOptions(
        movie_template="{name} {source_type} {release_group} {file_name}", word_separator="space"
    )
    result = resolve_output_name(FILE, options, fs=_Fs())
    assert result.relative_path == "Hacksaw Ridge UHD BluRay GRP hacksawridge.mkv"


def test_handbrake_clean_up_applies_to_source() -> None:
    options = NamingOptions(movie_template="{source}", title_case=True, remove_punctuation=True)
    result = resolve_output_name(Path("/hacksaw_ridge-2016.mkv"), options, fs=_Fs())
    assert result.relative_path == "Hacksaw_Ridge2016.mkv"


# --------------------------------------------------------------------------- output media


@pytest.mark.parametrize(
    ("size", "label"),
    [
        ((3840, 2160), "2160p"),
        ((4096, 2160), "2160p"),
        ((1920, 1080), "1080p"),
        ((1920, 800), "1080p"),
        ((1440, 1080), "1080p"),
        ((1916, 1036), "1080p"),
        ((1280, 720), "720p"),
        ((720, 576), "576p"),
        ((1024, 576), "576p"),
        ((640, 480), "480p"),
        ((854, 480), "480p"),
        ((640, 360), "640x360"),
        ((960, 540), "960x540"),
        ((720, 432), "720x432"),
        ((7680, 4320), "7680x4320"),
    ],
)
def test_resolution(size: tuple[int, int], label: str) -> None:
    assert resolution_label(*size) == label
    assert render("{resolution}", output_size=size) == label


def test_hdr() -> None:
    hdr = HdrInfo(formats=[HdrFormat.HDR10, HdrFormat.DOLBY_VISION])
    source = _source(video=[VideoStream(index=0, width=3840, height=2160, codec="hevc", hdr=hdr)])
    ten_bit = _job(video=VideoSettings(bit_depth=10))
    assert render("{hdr}", job=ten_bit, source=source) == "DV"
    assert render("x<{hdr}>", job=_job(), source=source) == "x"  # 8-bit output: SDR
    tonemap = _job(
        video=VideoSettings(bit_depth=10), filters=FilterSettings({"tonemap": FilterConfig()})
    )
    assert render("x<{hdr}>", job=tonemap, source=source) == "x"
    passthrough = _job(video=VideoSettings(passthrough=True))
    assert render("{hdr}", job=passthrough, source=source) == "DV"
    assert render("x<{hdr}>", job=passthrough, source=_source()) == "x"  # SDR source
    assert hdr_label([HdrFormat.HDR10_PLUS, HdrFormat.HDR10]) == "HDR10+"
    assert hdr_label([HdrFormat.HLG]) == "HLG"
    assert hdr_label([HdrFormat.HDR10]) == "HDR10"
    assert hdr_label([]) is None


def _media_source() -> MediaSource:
    return _source(
        audio=[
            AudioStream(
                index=1,
                codec="truehd",
                display_codec="TrueHD Atmos",
                channels=8,
                channel_layout="7.1",
                language="hun",
            ),
            AudioStream(
                index=2,
                codec="ac3",
                display_codec="AC-3",
                channels=6,
                channel_layout="5.1(side)",
                language="eng",
            ),
            AudioStream(index=3, codec="aac", channels=2, language="und"),
        ],
        subtitles=[
            SubtitleStream(index=4, codec="subrip", language="hun"),
            SubtitleStream(
                index=5, codec="hdmv_pgs_subtitle", language="eng", language_ietf="en-US"
            ),
        ],
    )


def test_acodec_and_audio_channels() -> None:
    source = _media_source()
    encode = _job(audio=[AudioOutputTrack(source_stream=2, encoder="ac3", mixdown="5.1")])
    assert render("{acodec} {audio_channels}", job=encode, source=source) == "AC-3 5.1"
    keep_layout = _job(audio=[AudioOutputTrack(source_stream=1, encoder="libopus")])
    assert render("{acodec} {audio_channels}", job=keep_layout, source=source) == "Opus 7.1"
    stereo = _job(audio=[AudioOutputTrack(source_stream=1, encoder="aac", mixdown="stereo")])
    assert render("{acodec} {audio_channels}", job=stereo, source=source) == "AAC 2.0"
    passthru = _job(audio=[AudioOutputTrack(source_stream=1, action="passthru")])
    assert render("{acodec} {audio_channels}", job=passthru, source=source) == "TrueHD Atmos 7.1"
    assert render("x<{acodec}><{audio_channels}>", job=passthru) == "x"  # no source
    assert render("x<{acodec}>", job=_job()) == "x"  # no audio track


@pytest.mark.parametrize(
    ("channels", "layout", "label"),
    [
        (1, "mono", "1.0"),
        (6, "5.1(side)", "5.1"),
        (6, None, "5.1"),
        (3, None, "2.1"),
        (12, None, "12"),
        (4, "quad", "4.0"),
    ],
)
def test_audio_channels_label(channels: int, layout: str | None, label: str) -> None:
    assert audio_channels_label(channels, layout) == label


def test_audio_and_subtitle_languages() -> None:
    source = _media_source()
    job = _job(
        audio=[
            AudioOutputTrack(source_stream=1),
            AudioOutputTrack(source_stream=2),
            AudioOutputTrack(source_stream=3),  # und: left out
            AudioOutputTrack(source_stream=2, metadata=TrackMetadata(language="de")),
        ],
        subtitles=[
            SubtitleOutputTrack(source=5),
            SubtitleOutputTrack(source=4, action="burn"),  # burned in: not a track
            SubtitleOutputTrack(source=ExternalSubtitle(path=Path("/s.srt"), language="fr")),
        ],
    )
    assert render("{audio_langs} {sub_langs}", job=job, source=source) == "HUN-ENG-GER ENG-FRE"
    assert render("x<{audio_langs}><{sub_langs}>", job=_job(), source=source) == "x"


def test_container() -> None:
    assert render("{container}") == "MKV"
    assert render("{container}", container="mp4") == "MP4"
    assert render("{container}", container="webm") == "WebM"
    assert render("{container}", job=_job(output=OutputSettings(container="mp4"))) == "MP4"


def test_every_variable_is_in_the_result() -> None:
    result = resolve_output_name(FILE, NamingOptions(), fs=_Fs(), now=NOW)
    assert list(result.variables) == [v.name for v in VARIABLES]
    assert len({v.name for v in VARIABLES}) == len(VARIABLES)


def test_subtitle_languages_from_the_track_metadata() -> None:
    job = _job(
        subtitles=[
            SubtitleOutputTrack(source=4, metadata=TrackMetadata(language="pt-BR")),
            SubtitleOutputTrack(source=5),  # no source: unknown language
        ]
    )
    assert render("{sub_langs}", job=job) == "POR"
