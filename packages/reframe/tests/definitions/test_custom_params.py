"""Which custom encoder parameters Reframe passes to FFmpeg (C-6; decision 0035 "Follow-up
(core-complete review, 2026-10-16)", R5-1). Pure: no FFmpeg (the behaviour of the real
encoders is in ``tests/validation/test_custom_params_ffmpeg.py``)."""

from __future__ import annotations

from hypothesis import given
from hypothesis import strategies as st

from reframe.command.video import split_params
from reframe.definitions import load_definitions
from reframe.definitions.custom_params import (
    custom_param_rules,
    dict_pairs,
    file_key,
    library_key_forms,
    own_option_allowed,
    split_custom_params,
)


@given(st.text(alphabet=st.sampled_from(list("ab=:\\ -'\t")), max_size=24))
def test_the_split_is_the_command_builders(text: str) -> None:
    """Validation checks exactly the names the builder writes as ``-<name>:v:0``."""
    assert [(p.name, p.value) for p in split_custom_params(text)] == split_params(text)


def test_the_split_keeps_the_typed_text() -> None:
    params = split_custom_params(r"vs\tats_file=a\:b : :x")
    assert [(p.name, p.value, p.raw) for p in params] == [
        ("vstats_file", "a:b", r"vs\tats_file=a\:b "),
        ("x", "1", "x"),
    ]


def test_dict_pairs_split_like_ffmpeg() -> None:
    """``av_dict_parse_string(…, "=", ":")`` with ``av_get_token``: quotes and escapes."""
    assert dict_pairs("a=1:b=2") == [("a", "1"), ("b", "2")]
    assert dict_pairs("'csv'=/x:c\\sv=/y") == [("csv", "/x"), ("csv", "/y")]
    assert dict_pairs("x='1:csv=/p':y=2") == [("x", "1:csv=/p"), ("y", "2")]
    assert dict_pairs("  a = 1 :b=' 2 '") == [("a", "1"), ("b", " 2 ")]
    # A key runs to the next '=' (x265: "Unknown option: novalue:csv.", checked).
    assert dict_pairs("a=1:novalue:csv=/p") == [("a", "1"), ("novalue:csv", "/p")]
    assert dict_pairs("a=1:b=:c=2") == [("a", "1")]  # an empty value: FFmpeg applies nothing
    assert dict_pairs("") == []


def test_library_key_forms() -> None:
    assert library_key_forms("--Analysis_Save") == {"analysis-save"}
    assert library_key_forms("nocsv") == {"nocsv", "csv"}
    assert library_key_forms("no-csv") == {"no-csv", "csv"}
    assert library_key_forms("'c\\sv'") == {"csv"}


def test_file_keys() -> None:
    assert file_key("libx265", "csv") is not None
    assert file_key("libx265", "analysis_save") is not None
    assert file_key("libx265", "no-csv") is not None
    assert file_key("libx265", "aq-mode") is None
    assert file_key("libx265", "scaling-list", "default") is None
    assert file_key("libx265", "scaling-list", "/m/list.txt") is not None
    assert file_key("libx264", "dump-yuv") is not None
    assert file_key("libx264", "csv") is None  # an x265 key: x264 refuses it anyway
    assert file_key("libsvtav1", "fgs-table") is not None
    assert file_key("libvpx-vp9", "csv") is None


def test_own_options_are_an_allow_list() -> None:
    assert own_option_allowed("libvpx-vp9", "lag-in-frames")
    assert own_option_allowed("libvpx-vp9", "g")  # a generic encoder option
    assert own_option_allowed("hevc_nvenc", "init_qpB")
    assert not own_option_allowed("libvpx-vp9", "bogus")
    assert not own_option_allowed("libvpx-vp9", "vstats_file")
    assert not own_option_allowed("libvpx-vp9", "/filter")
    assert not own_option_allowed("libvpx-vp9", "g:v")
    assert not own_option_allowed("hevc_qsv", "qsv_params")
    # The build's list replaces the recorded one; FFmpeg's file options never pass.
    assert own_option_allowed("libvpx-vp9", "new-option", ["new-option"])
    assert not own_option_allowed("libvpx-vp9", "lag-in-frames", ["new-option"])
    assert not own_option_allowed("libvpx-vp9", "passlogfile", ["passlogfile"])


def test_the_rules_cover_every_encoder() -> None:
    rules = custom_param_rules()
    encoders = load_definitions().video_encoders.values()
    with_params = {e.id for e in encoders if e.params_arg is not None}
    assert set(rules.file_keys) == with_params
    assert set(rules.private_options) == {e.id for e in encoders if e.params_arg is None}
    assert not rules.codec_options & rules.file_options
    for names in rules.private_options.values():
        assert not names & rules.file_options
