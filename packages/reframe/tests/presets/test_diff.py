"""``diff(template, preset)`` for the *modified* marker."""

from __future__ import annotations

from typing import Any

from hypothesis import given
from hypothesis import strategies as st

from reframe.models import FieldChange, FilterConfig, JobTemplate, Preset
from reframe.presets import builtin_presets, diff, diff_documents


def preset() -> Preset:
    return next(p for p in builtin_presets() if p.id == "hq-1080p30-surround")


def as_template(p: Preset) -> JobTemplate:
    return JobTemplate.model_validate(
        p.model_dump(mode="json", exclude={"id", "name", "category", "description", "built_in"})
    )


def edited(**changes: Any) -> JobTemplate:
    data = as_template(preset()).model_dump(mode="json")
    for path, value in changes.items():
        target: Any = data
        keys = path.split("__")
        for key in keys[:-1]:
            target = target[int(key)] if isinstance(target, list) else target[key]
        target[keys[-1]] = value
    return JobTemplate.model_validate(data)


def test_unchanged_template_has_no_changes() -> None:
    p = preset()
    assert diff(as_template(p), p) == []
    assert diff(p, p) == []


def test_identity_fields_and_unknown_fields_do_not_count() -> None:
    p = preset()
    other = p.model_copy(update={"name": "Renamed", "description": "x", "built_in": False})
    assert diff(other, p) == []
    with_extra = JobTemplate.model_validate(
        {**as_template(p).model_dump(mode="json"), "from_the_future": 1, "schema_version": 3}
    )
    assert diff(with_extra, p) == []


def test_changed_leaf_values_have_dotted_paths() -> None:
    template = edited(video__preset="veryslow", audio_defaults__codec_rules__0__max_bitrate=448)
    assert diff(template, preset()) == [
        FieldChange(path="video.preset", preset_value="slow", value="veryslow"),
        FieldChange(path="audio_defaults.codec_rules[0].max_bitrate", preset_value=640, value=448),
    ]


def test_filters_added_and_removed() -> None:
    template = as_template(preset())
    template.filters.root["denoise"] = FilterConfig(preset="light", implementation="hqdn3d")
    del template.filters.root["interlace_detection"]
    changes = diff(template, preset())
    assert [(c.path, c.kind) for c in changes] == [
        ("filters.interlace_detection", "removed"),
        ("filters.denoise", "added"),
    ]
    assert changes[0].preset_value == {
        "preset": "default",
        "tune": None,
        "custom": None,
        "implementation": None,
    }
    assert changes[1].value == {
        "preset": "light",
        "tune": None,
        "custom": None,
        "implementation": "hqdn3d",
    }


def test_list_items_added_and_removed() -> None:
    p = preset()
    shorter = as_template(p)
    shorter.audio_defaults.codec_rules = shorter.audio_defaults.codec_rules[1:]
    changes = diff(shorter, p)
    assert changes[-1].path == "audio_defaults.codec_rules[1]"
    assert changes[-1].kind == "removed"
    longer = as_template(p)
    longer.audio_defaults.passthru.allowed = ["ac3", "eac3"]
    assert diff(longer, p) == [
        FieldChange(path="audio_defaults.passthru.allowed[1]", kind="added", value="eac3")
    ]


def test_a_union_member_change_is_one_change() -> None:
    template = edited(video__rate_control={"mode": "bitrate", "kbps": 8000})
    [change] = diff(template, preset())
    assert change.path == "video.rate_control"
    assert change.preset_value == {"mode": "quality", "value": 20.0}
    assert change.value == {
        "mode": "bitrate",
        "kbps": 8000,
        "two_pass": False,
        "turbo_first_pass": False,
    }
    size = edited(dimensions__size={"mode": "source"})
    assert [c.path for c in diff(size, preset())] == ["dimensions.size"]


def test_none_to_value_and_naming() -> None:
    template = edited(video__tune="film", naming={"movie_template": "{name}"})
    changes = {c.path: c for c in diff(template, preset())}
    assert changes["video.tune"].preset_value is None
    assert changes["video.tune"].value == "film"
    assert changes["naming"].preset_value is None


def test_json_equality_rules() -> None:
    assert diff_documents({"a": 1}, {"a": 1.0}) == []
    assert diff_documents({"a": True}, {"a": 1}) == [
        FieldChange(path="a", preset_value=True, value=1)
    ]
    assert diff_documents({"a": {"b": [1]}}, {"a": {"b": [1, 2]}}) == [
        FieldChange(path="a.b[1]", kind="added", value=2)
    ]


@given(st.sampled_from(builtin_presets()), st.sampled_from(builtin_presets()))
def test_diff_is_empty_exactly_when_the_templates_are_equal(a: Preset, b: Preset) -> None:
    changes = diff(as_template(a), b)
    assert (changes == []) == (as_template(a) == as_template(b))
