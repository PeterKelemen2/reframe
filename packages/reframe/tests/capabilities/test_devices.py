"""VAAPI render nodes (decision 0020) and ``CapabilitySnapshot.usable_filter``."""

from __future__ import annotations

from pathlib import Path

import pytest

from reframe.capabilities import render_nodes
from reframe.models import CapabilitySnapshot, EncoderSettings


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


def test_vaapi_device_setting_defaults_to_automatic() -> None:
    assert EncoderSettings().vaapi_device is None
    forced = EncoderSettings.model_validate({"vaapi_device": "/dev/dri/renderD129"})
    assert forced.vaapi_device == "/dev/dri/renderD129"


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


def test_has_filter_keeps_its_meaning() -> None:
    failed = CapabilitySnapshot(filters=["libplacebo"], filter_failures={"libplacebo": "x"})
    assert failed.has_filter("libplacebo") is True
    assert failed.usable_filter("libplacebo") is False
