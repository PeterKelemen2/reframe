"""VAAPI render nodes and ``CapabilitySnapshot.usable_filter``."""

from __future__ import annotations

from pathlib import Path

import pytest

from reframe.capabilities import render_nodes
from reframe.models import CapabilitySnapshot


def test_render_nodes_sorted_by_number(tmp_path: Path) -> None:
    for name in ("renderD130", "card0", "renderD128", "renderD1000", "renderD129", "by-path"):
        (tmp_path / name).touch()
    (tmp_path / "renderDx").touch()
    assert render_nodes(tmp_path) == [
        str(tmp_path / "renderD128"),
        str(tmp_path / "renderD129"),
        str(tmp_path / "renderD130"),
        str(tmp_path / "renderD1000"),
    ]


def test_no_dri_folder(tmp_path: Path) -> None:
    assert render_nodes(tmp_path / "missing") == []


@pytest.mark.parametrize(
    ("snapshot", "usable"),
    [
        (CapabilitySnapshot(), None),  # the filter list was not read
        (CapabilitySnapshot(filters=["zscale"]), False),  # not in the build
        (CapabilitySnapshot(filters=["libplacebo"], untested_filters=["libplacebo"]), None),
        (
            CapabilitySnapshot(
                filters=["libplacebo"], filter_failures={"libplacebo": "No working Vulkan driver"}
            ),
            False,
        ),
        (CapabilitySnapshot(filters=["libplacebo"]), True),
    ],
)
def test_usable_filter(snapshot: CapabilitySnapshot, usable: bool | None) -> None:
    assert snapshot.usable_filter("libplacebo") is usable
