"""Without mkvpropedit, every issue about what it would have written names it and says how to get
it: no package bundles it, and nothing it would write is dropped silently."""

from __future__ import annotations

import importlib.util
import sys
from collections.abc import Callable
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from reframe.definitions import Definitions
from reframe.models import Severity, ToolStatus
from reframe.tools.discovery import check_tool, locate_tools


def _load(name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        f"_reframe_validation_{name}", Path(__file__).with_name(f"{name}.py")
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


sc = _load("scenario")

INSTALL = "install MKVToolNix from https://mkvtoolnix.download/"


def _edit_in_place(s: Any) -> None:
    from reframe.metadata import remux_job

    s.job = remux_job(s.job, s.source, edit_in_place=True)


def _bcp47_language(s: Any) -> None:
    s.job.audio[0].metadata.language = "pt-BR"


def _flag_via_mkvpropedit(s: Any) -> None:
    definitions: Definitions = sc.DEFS.model_copy(deep=True)
    mkv = definitions.containers["mkv"]
    mkv.flags = [f for f in mkv.flags if f != "original"]
    mkv.mkvpropedit_flags = ["original"]
    s.definitions = definitions
    s.job.audio[0].metadata.original = True


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("change", "code", "severity"),
    [
        (_edit_in_place, "tool.mkvpropedit_missing", Severity.ERROR),
        (_bcp47_language, "metadata.language_tag_lost", Severity.WARNING),
        (_flag_via_mkvpropedit, "tool.mkvpropedit_missing", Severity.WARNING),
    ],
)
async def test_each_issue_that_needs_mkvpropedit_says_what_to_install(
    tmp_path: Path, change: Callable[[Any], None], code: str, severity: Severity
) -> None:
    location = locate_tools(
        environ={}, bundled_roots=[], search_path=str(tmp_path), platform="win32"
    )["mkvpropedit"]
    missing = await check_tool(location)
    assert missing.status is ToolStatus.MISSING
    s = sc.base()
    change(s)
    s.tools = sc.make_tools(mkvpropedit=missing)

    [issue] = [i for i in s.validate() if i.code == code]

    assert issue.severity is severity
    assert "mkvpropedit" in issue.message
    assert INSTALL in issue.message
