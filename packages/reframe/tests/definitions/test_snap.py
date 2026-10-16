"""The audio snapping helpers (decision 0024): the command builder (C-7), validation (C-8) and
the codec rules (C-12) compute the same mixdown, sample rate and bitrate through them."""

from __future__ import annotations

import pytest

from reframe.definitions import channels_mixdown, load_definitions
from reframe.models.job import Mixdown


@pytest.mark.parametrize(
    ("encoder", "requested", "source_channels", "expected"),
    [
        # A layout the encoder makes, from a source with at least as many channels.
        ("aac", "5.1", 8, "5.1"),
        ("aac", "stereo", 2, "stereo"),
        ("ac3", "5.1", 6, "5.1"),
        ("libopus", "7.1", 8, "7.1"),
        # A layout the encoder cannot make: its largest layout below.
        ("ac3", "7.1", 8, "5.1"),
        ("eac3", "7.1", 8, "5.1"),
        ("libmp3lame", "5.1", 6, "stereo"),
        # Never an upmix: a smaller known source keeps its layout.
        ("aac", "5.1", 2, None),
        ("ac3", "7.1", 6, None),
        ("libmp3lame", "stereo", 1, None),
        # Dolby Pro Logic II needs more than two channels to encode.
        ("aac", "dpl2", 6, "dpl2"),
        ("aac", "dpl2", 2, None),
        # Unknown source channels: the request stands (snapped to the encoder).
        ("aac", "5.1", 0, "5.1"),
        ("ac3", "7.1", 0, "5.1"),
        # Keep the source layout: kept when the encoder takes it, else snapped down.
        ("aac", None, 8, None),
        ("ac3", None, 6, None),
        ("ac3", None, 8, "5.1"),
        ("eac3", None, 7, "5.1"),
        ("libmp3lame", None, 6, "stereo"),
        ("libmp3lame", None, 2, None),
        ("libmp3lame", None, 0, None),
    ],
)
def test_snap_mixdown(
    encoder: str, requested: Mixdown | None, source_channels: int, expected: Mixdown | None
) -> None:
    defs = load_definitions()
    got = defs.audio_encoders[encoder].snap_mixdown(requested, source_channels, defs.mixdowns)
    assert got == expected


def test_snap_mixdown_edge_cases() -> None:
    defs = load_definitions()
    aac = defs.audio_encoders["aac"]
    no_mono = aac.model_copy(update={"mixdowns": ["stereo", "5.1"]})
    # Nothing small enough: the encoder's smallest layout.
    assert no_mono.snap_mixdown("mono", 0, defs.mixdowns) == "stereo"
    # ... but never an upmix: a mono source keeps its layout.
    assert no_mono.snap_mixdown("mono", 1, defs.mixdowns) is None
    only_dpl2 = aac.model_copy(update={"mixdowns": ["dpl2"], "max_channels": 2})
    assert only_dpl2.snap_mixdown(None, 6, defs.mixdowns) is None
    unrestricted = aac.model_copy(update={"mixdowns": []})
    assert unrestricted.snap_mixdown("7.1", 8, defs.mixdowns) == "7.1"


@pytest.mark.parametrize(
    ("encoder", "rate", "source_rate", "expected"),
    [
        ("libopus", 48000, None, 48000),
        ("libopus", 44100, None, 48000),
        ("libopus", None, 44100, 48000),  # same as source, but the source rate is not supported
        ("libopus", 16000, 44100, 16000),  # a requested rate wins over the source rate
        ("libopus", None, None, None),
        ("ac3", 96000, 44100, 48000),
        ("ac3", None, 22050, 32000),
        ("libopus", 20000, None, 24000),  # halfway between 16 000 and 24 000: the higher one
        ("aac", None, 44100, 44100),
    ],
)
def test_snap_samplerate(
    encoder: str, rate: int | None, source_rate: int | None, expected: int | None
) -> None:
    enc = load_definitions().audio_encoders[encoder]
    assert enc.snap_samplerate(rate, source_rate) == expected


def test_snap_samplerate_without_a_list() -> None:
    aac = load_definitions().audio_encoders["aac"].model_copy(update={"samplerates": []})
    assert aac.snap_samplerate(12345) == 12345


@pytest.mark.parametrize(
    ("channels", "expected"),
    [(0, "stereo"), (1, "mono"), (2, "stereo"), (3, "5.1"), (6, "5.1"), (7, "7.1")],
)
def test_channels_mixdown(channels: int, expected: Mixdown) -> None:
    assert channels_mixdown(channels) == expected
