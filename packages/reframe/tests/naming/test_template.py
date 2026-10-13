"""Template syntax (03 §Template syntax): variables, format specs, optional groups,
subfolders, brace escapes, and the validation issues of a bad template."""

from __future__ import annotations

from datetime import datetime
from typing import Any

import pytest
from hypothesis import given
from hypothesis import strategies as st

from reframe.jsonpatch import apply_patch
from reframe.models import AddOp, Severity
from reframe.naming import check_template
from reframe.naming.template import (
    Group,
    Slash,
    Text,
    Var,
    format_value,
    parse_template,
    render,
    template_variables,
)
from reframe.naming.variables import VARIABLE_KINDS


def _render(template: str, **values: Any) -> list[str]:
    """The rendered segments as strings."""
    parsed = parse_template(template)
    assert not parsed.errors, parsed.errors
    return ["".join(piece.text for piece in segment) for segment in render(parsed, values)]


# --------------------------------------------------------------------------- parsing


def test_parse_nodes() -> None:
    parsed = parse_template("{name}< ({year})>/S{season:02}{{x}}")
    assert parsed.errors == ()
    assert parsed.nodes == (
        Var("name", None, 0, 6),
        Group((Text(" ("), Var("year", None, 9, 15), Text(")")), 6),
        Slash(),
        Text("S"),
        Var("season", "02", 19, 30),
        Text("{x}"),
    )
    assert [v.name for v in template_variables(parsed.nodes)] == ["name", "year", "season"]


def test_nested_groups() -> None:
    parsed = parse_template("<a<{year}>b>")
    assert parsed.errors == ()
    assert parsed.nodes == (Group((Text("a"), Group((Var("year", None, 3, 9),), 2), Text("b")), 0),)


@pytest.mark.parametrize(
    ("template", "message", "position"),
    [
        ("{name", "'{' is not closed", 0),
        ("{na{me}", "'{' is not closed", 0),
        ("a}b", "'}' without '{'", 1),
        ("{}", "A variable has no name", 0),
        ("{a b}", "'{a b}' is not a variable name", 0),
        ("<{name}", "'<' is not closed", 0),
        ("{name}>", "'>' without '<'", 6),
    ],
)
def test_syntax_errors(template: str, message: str, position: int) -> None:
    errors = parse_template(template).errors
    assert len(errors) == 1
    assert errors[0].message.startswith(message)
    assert errors[0].position == position


@given(st.text(max_size=40))
def test_any_text_parses_without_an_exception(text: str) -> None:
    parsed = parse_template(text)
    render(parsed, dict.fromkeys(VARIABLE_KINDS, "x"))
    check_template(text)


# --------------------------------------------------------------------------- rendering


def test_literal_braces() -> None:
    assert _render("{{{name}}}", name="Movie") == ["{Movie}"]
    assert _render("a}}b{{c") == ["a}b{c"]


def test_subfolders() -> None:
    assert _render(
        "{name}/<Season {season:02}/>{main_title}", name="Show", season=3, main_title="M"
    ) == [
        "Show",
        "Season 03",
        "M",
    ]
    assert _render("{name}/<Season {season:02}/>{main_title}", name="Movie", main_title="M") == [
        "Movie",
        "M",
    ]


def test_optional_group_drops_when_a_variable_is_empty() -> None:
    template = "{name}< ({year})>< - S{season:02}E{episode:02}>< - {sub_title}>"
    assert _render(template, name="Hacksaw Ridge", year=2016) == ["Hacksaw Ridge (2016)"]
    assert _render(template, name="The Sopranos", season=3, episode=2, sub_title="Proshai") == [
        "The Sopranos - S03E02 - Proshai"
    ]
    # One empty variable drops the whole group: an episode without a season.
    assert _render(template, name="One Piece", episode=1071) == ["One Piece"]


def test_season_zero_is_not_empty() -> None:
    assert _render("<S{season:02}>", season=0) == ["S00"]


def test_inner_group_does_not_drop_the_outer_one() -> None:
    assert _render("<{name}< ({year})>!>", name="X") == ["X!"]
    assert _render("<{name}< ({year})>!>", year=2016) == [""]


def test_group_without_variables_is_kept() -> None:
    assert _render("a<b>c") == ["abc"]


def test_empty_variable_outside_a_group() -> None:
    assert _render("{edition}x") == ["x"]


def test_render_with_a_bad_spec_uses_the_default_format() -> None:
    parsed = parse_template("{season:upper}")
    assert ["".join(p.text for p in s) for s in render(parsed, {"season": 3})] == ["3"]


def test_pieces_remember_their_variable() -> None:
    segments = render(parse_template("{name} - {sub_title}"), {"name": "A", "sub_title": "B"})
    assert [(p.text, p.var) for p in segments[0]] == [
        ("A", "name"),
        (" - ", None),
        ("B", "sub_title"),
    ]


# --------------------------------------------------------------------------- format specs


def test_number_specs() -> None:
    assert format_value("season", 3, "02") == "03"
    assert format_value("episode", 7, "03d") == "007"
    assert format_value("year", 2016, None) == "2016"
    assert format_value("quality_bitrate", 22.0, None) == "22"
    assert format_value("quality_bitrate", 22.5, None) == "22.5"
    assert format_value("quality_bitrate", 22.5, ".0f") == "22"


def test_text_specs() -> None:
    assert format_value("name", "The Sopranos", "upper") == "THE SOPRANOS"
    assert format_value("name", "The Sopranos", "lower") == "the sopranos"
    assert format_value("name", "the sopranos", "title") == "The Sopranos"
    assert format_value("name", "The Sopranos", ".3") == "The"
    assert format_value("name", "", "upper") == ""


def test_date_specs() -> None:
    moment = datetime(2026, 10, 11, 14, 30)
    assert format_value("date", moment, None) == "2026-10-11"
    assert format_value("time", moment, None) == "14-30"
    assert format_value("date", moment, "%d.%m.%Y") == "11.10.2026"
    with pytest.raises(ValueError, match="not a date format"):
        format_value("date", moment, "YYYY")


def test_empty_values() -> None:
    assert format_value("season", None, "02") == ""
    assert format_value("name", None, None) == ""


# --------------------------------------------------------------------------- check_template


def test_good_templates_have_no_issues() -> None:
    for template in (
        "{main_title}",
        "{main_title}.{resolution}",
        "{name}< ({year})>< - S{season:02}E{episode:02}>< - {sub_title}>",
        "{name}/<Season {season:02}/>{main_title}",
        "{source}-{title}",
        "{date:%d.%m.%Y} {time} {creation-date} {modification-time:%H.%M}",
        "{name:upper} {{literal}}",
    ):
        assert check_template(template) == [], template


def test_unknown_variable_with_did_you_mean_fixes() -> None:
    [issue] = check_template("{nmae} - {episode:02}")
    assert issue.severity is Severity.ERROR
    assert issue.code == "naming.unknown_variable"
    assert issue.path == "output.naming.template"
    assert "Did you mean {name}?" in issue.message
    assert issue.fixes[0].label == "Use {name}"
    assert issue.fixes[0].patch == [
        AddOp(path="/output/naming/template", value="{name} - {episode:02}")
    ]
    assert issue.fixes[0].target == "job"


@pytest.mark.parametrize(
    ("typed", "suggested"),
    [
        ("Source", "source"),
        ("creation_date", "creation-date"),
        ("episode_title", "sub_title"),
        ("show", "name"),
        ("maintitle", "main_title"),
        ("resolutoin", "resolution"),
    ],
)
def test_suggestions(typed: str, suggested: str) -> None:
    [issue] = check_template("{" + typed + "}")
    assert issue.fixes[0].label == "Use {" + suggested + "}"


def test_unknown_variable_without_a_suggestion() -> None:
    [issue] = check_template("{zzzzzz}")
    assert issue.fixes == []
    assert "Did you mean" not in issue.message


def test_unknown_variable_keeps_its_spec_in_the_fix() -> None:
    [issue] = check_template("{seasn:02}")
    assert issue.fixes[0].patch[0].value == "{season:02}"  # type: ignore[union-attr]


def test_every_fix_removes_its_issue() -> None:
    """Applying a fix to a job document gives a template without that issue."""
    for template in ("{nmae}", "{season:upper}", "{date:YYYY}", "a\\b", "", "{Source}-{titel}"):
        for issue in check_template(template):
            for fix in issue.fixes:
                document = {"output": {"naming": {"template": template}}}
                fixed = apply_patch(document, fix.patch)["output"]["naming"]["template"]
                remaining = [i for i in check_template(fixed) if i.message == issue.message]
                assert not remaining, (template, fix.label, fixed)


def test_bad_format_spec() -> None:
    issues = check_template("{season:upper} {date:YYYY} {name:xyz}")
    assert [i.code for i in issues] == ["naming.bad_format_spec"] * 3
    assert all(i.severity is Severity.ERROR for i in issues)
    assert issues[0].fixes[0].patch[0].value == "{season} {date:YYYY} {name:xyz}"  # type: ignore[union-attr]


def test_syntax_issue() -> None:
    [issue] = check_template("{name")
    assert issue.code == "naming.template_syntax"
    assert issue.severity is Severity.ERROR
    assert "position 1" in issue.message


def test_backslash_warning() -> None:
    [issue] = check_template("{name}\\{main_title}")
    assert issue.code == "naming.backslash"
    assert issue.severity is Severity.WARNING
    assert issue.fixes[0].patch[0].value == "{name}/{main_title}"  # type: ignore[union-attr]


def test_empty_template_warning() -> None:
    [issue] = check_template("  ")
    assert issue.code == "naming.empty_template"
    assert issue.severity is Severity.WARNING


def test_field_and_target_of_the_fix() -> None:
    [issue] = check_template("{nmae}", field="naming.movie_template", target="template")
    assert issue.path == "naming.movie_template"
    assert issue.fixes[0].patch[0].path == "/naming/movie_template"
    assert issue.fixes[0].target == "template"
    [issue] = check_template("{nmae}", field="presets[2].naming.episode_template")
    assert issue.fixes[0].patch[0].path == "/presets/2/naming/episode_template"
