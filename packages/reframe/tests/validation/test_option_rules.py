"""The advanced-option rules (C-6, M9) in detail: messages, fixes, the builder agreement, and
the encoder switch (pure; the rule cases are in ``cases_options.py``, the encoder evidence in
``test_options_ffmpeg.py``)."""

from __future__ import annotations

from pathlib import Path

from reframe.command.video import video_encoder_args
from reframe.definitions import load_definitions
from reframe.models import AverageBitrate, CapabilitySnapshot, VideoSettings, VideoStream
from reframe.validation import switch_video_encoder
from reframe.validation.video import video_option_rule_issues

DEFS = load_definitions()
CAPS = CapabilitySnapshot()
STREAM = VideoStream.model_validate({"index": 0, "width": 1920, "height": 1080})


def _written(video: VideoSettings) -> list[str]:
    encoder = DEFS.video_encoders[video.encoder]
    return video_encoder_args(
        encoder, video, STREAM, status=None, run=None, passlog=Path("/x"), hdr=False
    )


def test_an_inactive_option_is_not_written_and_says_why() -> None:
    video = VideoSettings(encoder="libx265", preset="medium", advanced={"amp": True})
    issues = video_option_rule_issues(video, CAPS, DEFS)
    assert [(i.code, i.path) for i in issues] == [("encoder.option_inactive", "video.advanced.amp")]
    assert issues[0].message == (
        "Asymmetric partitions (amp) is not written: it needs Rectangular partitions (rect) on."
    )
    assert [f.label for f in issues[0].fixes] == ["Remove amp", "Set Rectangular partitions to on"]
    assert "amp=1" not in " ".join(_written(video))
    active = video.model_copy(update={"advanced": {"amp": True, "rect": True}})
    assert video_option_rule_issues(active, CAPS, DEFS) == []
    assert "amp=1" in _written(active)[-1]


def test_every_inactive_option_is_left_out_by_the_builder() -> None:
    """For every option with ``requires`` of every encoder: validation calls it inactive
    exactly when the builder leaves it out (decision 0026)."""
    checked = 0
    for encoder in DEFS.video_encoders.values():
        for option in encoder.options:
            if not option.requires:
                continue
            value: bool | int | float | str
            if option.type == "bool":
                value = True
            elif option.type == "enum":
                value = (option.choices or [])[-1].value
            elif option.type == "string":
                value = "x"
            else:
                assert option.max is not None
                value = int(option.max) if option.type == "int" else option.max
            for rc in (None, AverageBitrate(kbps=3000)):
                video = VideoSettings(encoder=encoder.id, advanced={option.key: value})
                if rc is not None:
                    video.rate_control = rc
                inactive = any(
                    i.code == "encoder.option_inactive"
                    for i in video_option_rule_issues(video, CAPS, DEFS)
                )
                mapping = option.mapping
                args = _written(video)
                if mapping.kind == "x26x_param":
                    written = any(f"{mapping.name}=" in a for a in args)
                elif mapping.kind == "private_opt":
                    written = f"-{mapping.name}:v:0" in args
                else:
                    written = f"{mapping.arg}:v:0" in args
                assert inactive != written, (encoder.id, option.key, rc)
                checked += 1
    assert checked > 50


def test_the_rules_skip_passthrough_and_unknown_encoders() -> None:
    passthrough = VideoSettings(encoder="libx265", passthrough=True, advanced={"amp": True})
    assert video_option_rule_issues(passthrough, CAPS, DEFS) == []
    assert video_option_rule_issues(VideoSettings(encoder="nope"), CAPS, DEFS) == []
    # A bad value is option_invalid's (video_option_issues), not an inactive option.
    bad = VideoSettings(encoder="libx265", advanced={"amp": "yes"})
    assert video_option_rule_issues(bad, CAPS, DEFS) == []


def test_switching_encoders_drops_values_the_new_encoder_does_not_take() -> None:
    """x264's colour matrix ``GBR`` is ``gbr`` in x265: the switch drops it instead of leaving
    an ``encoder.option_invalid`` behind; a value both take is kept."""
    video = VideoSettings(
        encoder="libx264", advanced={"colormatrix": "GBR", "colorprim": "bt2020", "nr": 100}
    )
    ops, _note = switch_video_encoder(video, "libx265", DEFS)
    advanced = [op for op in ops if op.path == "/video/advanced"]
    assert advanced
    assert advanced[0].value == {"colorprim": "bt2020"}  # type: ignore[union-attr]
