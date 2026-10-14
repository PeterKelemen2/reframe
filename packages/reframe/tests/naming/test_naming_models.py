"""The naming models: round trips, and ``JobNaming.field_overrides`` in stored jobs.

``tests/models/test_roundtrip.py`` already round-trips every public model with generated
values; these tests pin the cases that matter for C-16.
"""

from __future__ import annotations

from pathlib import Path

from hypothesis import given
from hypothesis import strategies as st

from reframe.models import (
    JobNaming,
    JobSettings,
    NameCandidate,
    NameResult,
    NameSpan,
    NamingVariable,
    ParsedName,
    SourceRef,
)
from reframe.naming import VARIABLES


def test_job_without_field_overrides_still_loads() -> None:
    """A job stored before C-16 has no ``field_overrides``: it loads with an empty dict."""
    stored = {"source": {"path": "/m/a.mkv"}, "output": {"naming": {"mode": "template"}}}
    job = JobSettings.model_validate(stored)
    assert job.output.naming.field_overrides == {}


def test_field_overrides_round_trip_and_unknown_fields_survive() -> None:
    naming = JobNaming.model_validate(
        {"field_overrides": {"name": "Hacksaw Ridge", "year": "2016"}, "from_newer": 1}
    )
    again = JobNaming.model_validate_json(naming.model_dump_json())
    assert again == naming
    assert again.field_overrides == {"name": "Hacksaw Ridge", "year": "2016"}
    assert again.model_dump()["from_newer"] == 1


@given(st.dictionaries(st.text(max_size=12), st.text(max_size=12), max_size=4))
def test_any_field_overrides_round_trip(overrides: dict[str, str]) -> None:
    job = JobSettings(source=SourceRef(path=Path("/m/a.mkv")))
    job.output.naming.field_overrides = overrides
    assert JobSettings.model_validate_json(job.model_dump_json()) == job


def test_name_result_round_trip() -> None:
    fields = ParsedName(
        kind="episode", main_title="A.S01E02", name="A", season=1, episode=2, episodes=[2]
    )
    result = NameResult(
        source="file",
        reason="why",
        candidates=[
            NameCandidate(
                kind="file",
                text="A.S01E02",
                path=Path("/m/A.S01E02.mkv"),
                score=3,
                recognised=["title"],
                word_separators=False,
                fields=fields,
                spans=[NameSpan(field="name", start=0, end=1, text="A")],
            )
        ],
        fields=fields,
        template="{main_title}",
        template_kind="episode",
        relative_path="A.S01E02.mkv",
        path=Path("/m/A.S01E02.mkv"),
        extension="mkv",
        variables={"name": "A"},
    )
    assert NameResult.model_validate_json(result.model_dump_json()) == result


def test_variables_are_models() -> None:
    assert all(isinstance(variable, NamingVariable) for variable in VARIABLES)
    assert NamingVariable.model_validate_json(VARIABLES[0].model_dump_json()) == VARIABLES[0]
