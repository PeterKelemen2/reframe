"""Custom encoder parameters: how they are split, matched and allowed. Pure: no FFmpeg runs."""

from __future__ import annotations

import tomllib
from importlib import resources

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
    whole_param,
)


@given(st.text(alphabet=st.sampled_from(list("ab=:\\ -'\t")), max_size=24))
def test_the_split_is_the_command_builders(text: str) -> None:
    assert [(p.name, p.value) for p in split_custom_params(text)] == split_params(text)


def test_the_split_keeps_the_typed_text() -> None:
    params = split_custom_params(r"vs\tats_file=a\:b : :x")
    assert [(p.name, p.value, p.raw) for p in params] == [
        ("vstats_file", "a:b", r"vs\tats_file=a\:b "),
        ("x", "1", "x"),
    ]
    params = split_custom_params(" ref=4 :bogus:path=C\\:/x::")
    assert [(p.name, p.value) for p in params] == [("ref", "4"), ("bogus", "1"), ("path", "C:/x")]
    assert [p.raw for p in params] == ["ref=4 ", "bogus", "path=C\\:/x"]
    assert split_custom_params("") == []


def test_a_quoted_colon_or_a_drive_colon_continues_the_parameter() -> None:
    params = split_custom_params(r"a=3:csv=C:\u\x.csv:b='1:2:3':c=D:/y:d=C::\z:e=CC:\w")
    assert [(p.raw, p.continues) for p in params] == [
        ("a=3", False),
        ("csv=C", False),
        (r"\u\x.csv", True),
        ("b='1", False),
        ("2", True),
        ("3'", True),
        ("c=D", False),
        ("/y", True),
        ("d=C", False),
        (r"\z", False),
        ("e=CC", False),
        (r"\w", False),
    ]
    assert [p.raw for p in whole_param(params, params[1])] == ["csv=C", r"\u\x.csv"]
    assert [p.raw for p in whole_param(params, params[4])] == ["b='1", "2", "3'"]
    assert [p.raw for p in whole_param(params, params[0])] == ["a=3"]


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


def test_a_name_or_a_file_name_is_compared_as_the_library_compares_it() -> None:
    """x264 ``cqm`` reads every value as a file name unless it contains ``flat`` or ``jvt``;
    x265 ``scaling-list`` takes only the whole names ``default`` / ``off``."""
    file_named = [
        ("libx264", "cqm", "/home/u/secret.cfg"),
        ("libx264", "cqm", "FLAT"),
        ("libx264", "cqm", "Flat"),
        ("libx264", "cqm", "JVT"),
        ("libx264", "cqm", "fla"),
        ("libx264", "cqm", "default"),
        ("libx264", "cqm", ""),
        ("libx264", "nocqm", "flat"),  # x264 opens a file named "true"
        ("libx264", "no-cqm", "jvt"),
        ("libx264", "cqmfile", "flat"),
        ("libx265", "scaling-list", "DEFAULT"),
        ("libx265", "scaling-list", "default "),  # quoted or escaped: FFmpeg trims a plain space
        ("libx265", "scaling-list", "./default"),
        ("libx265", "scaling-list", "flat"),
        ("libx265", "no-scaling-list", "default"),  # x265 opens a file named "true"
        ("libx265", "noscaling-list", "off"),
    ]
    for encoder, key, value in file_named:
        assert file_key(encoder, key, value) is not None, (encoder, key, value)
    names = [
        ("libx264", "cqm", "flat"),
        ("libx264", "cqm", "jvt"),
        ("libx264", "cqm", "jvt "),
        ("libx264", "cqm", "./flat"),  # x264 takes these as the presets: no file is opened
        ("libx264", "cqm", "/x/jvt/y.cfg"),
        ("libx264", "cqm", "flatjvt"),
        ("libx264", "CQM", "flat"),
        ("libx265", "scaling-list", "default"),
        ("libx265", "scaling-list", "off"),
        ("libx265", "scaling_list", "off"),
    ]
    for encoder, key, value in names:
        assert file_key(encoder, key, value) is None, (encoder, key, value)
    assert file_key("libx264", "cqm", "/home/u/secret.cfg") == (
        "reads quantisation matrices from this file unless the value is flat or jvt"
    )


def test_the_value_names_are_matched_in_a_known_way() -> None:
    data = resources.files("reframe.definitions") / "data" / "custom_params.toml"
    raw = tomllib.loads(data.read_text(encoding="utf-8"))
    assert set(raw["value_match"].values()) <= {"whole", "contains"}
    assert set(raw["value_match"]) <= set(raw["value_exceptions"])
    rules = custom_param_rules()
    assert rules.value_contains == {"cqm"}
    assert rules.value_exceptions["cqm"] == {"flat", "jvt"}


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
