"""Word separator and the HandBrake clean-up options."""

from __future__ import annotations

import pytest

from reframe.models import NamingOptions
from reframe.naming.clean import clean_name_text, convert_separator, title_case


@pytest.mark.parametrize(
    ("text", "source", "target", "expected"),
    [
        ("The.Sopranos", ".", " ", "The Sopranos"),
        ("The Sopranos", " ", ".", "The.Sopranos"),
        ("The_Office_US", "_", " ", "The Office US"),
        ("The.Sopranos", ".", None, "The.Sopranos"),
        ("The.Sopranos", ".", ".", "The.Sopranos"),
        ("Rose", None, " ", "Rose"),
        # Acronyms and numbers keep their dots.
        ("Marvels.Agents.of.S.H.I.E.L.D", ".", " ", "Marvels Agents of S.H.I.E.L.D"),
        (
            "Marvels.Agents.of.S.H.I.E.L.D.S01E01.Pilot",
            ".",
            " ",
            "Marvels Agents of S.H.I.E.L.D. S01E01 Pilot",
        ),
        ("E.T.the.Extra-Terrestrial", ".", " ", "E.T. the Extra-Terrestrial"),
        ("A.Quiet.Place", ".", " ", "A Quiet Place"),
        ("12.00.AM-1.00.AM", ".", " ", "12.00 AM-1.00 AM"),
        ("Blade.Runner.2049", ".", " ", "Blade Runner 2049"),
    ],
)
def test_convert_separator(
    text: str, source: str | None, target: str | None, expected: str
) -> None:
    assert convert_separator(text, source, target) == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("THE SOPRANOS", "The Sopranos"),
        ("they're here", "They're Here"),
        ("hacksaw.ridge.1080p", "Hacksaw.Ridge.1080p"),
        ("x-men_days", "X-Men_Days"),
    ],
)
def test_title_case_is_handbrakes(text: str, expected: str) -> None:
    """HandBrake lower-cases the text, then capitalises each word."""
    assert title_case(text) == expected


def test_handbrake_options_in_handbrake_order() -> None:
    options = NamingOptions(replace_underscores=True, remove_punctuation=True, title_case=True)
    assert clean_name_text("the_sopranos-s03e02,x", "_", options) == "The Sopranoss03e02x"
    # HandBrake parity: "Keep source" + "Remove common punctuation" joins dotted words.
    assert (
        clean_name_text("The.Sopranos", ".", NamingOptions(remove_punctuation=True))
        == "TheSopranos"
    )


def test_word_separator_runs_before_the_handbrake_options() -> None:
    options = NamingOptions(word_separator="space", remove_punctuation=True)
    assert clean_name_text("The.Sopranos", ".", options) == "The Sopranos"


def test_replace_underscores_only() -> None:
    options = NamingOptions(replace_underscores=True)
    assert clean_name_text("The_Office_US", "_", options) == "The Office US"


def test_keep_source_is_the_default() -> None:
    assert clean_name_text("The.Sopranos", ".", NamingOptions()) == "The.Sopranos"
