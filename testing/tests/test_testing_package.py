from __future__ import annotations

import reframe_testing


def test_testing_package_is_importable() -> None:
    assert reframe_testing.__doc__
