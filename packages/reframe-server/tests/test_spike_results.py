"""The spike's measurement scripts keep their raw output in ``desktop/spike/results/``, named
with the machine and the date, so that their tables can be recomputed later."""

from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[3]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from desktop.spike.scripts import cleanup, cold_start  # noqa: E402

STAMP = r"\d{4}-\d{2}-\d{2}-\d{6}"


@pytest.fixture
def results(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    monkeypatch.setattr(cold_start, "RESULTS", tmp_path / "results")
    return tmp_path / "results"


def test_a_cold_start_run_keeps_every_sample_and_its_load(
    monkeypatch: pytest.MonkeyPatch, results: Path
) -> None:
    totals = iter([0.5, 0.7, 0.6])
    monkeypatch.setattr(cold_start, "run_sidecar", lambda case, xdg: {"total": next(totals)})
    monkeypatch.setattr(time, "sleep", lambda seconds: None)
    monkeypatch.setattr(cold_start, "loadavg", iter(["1.00 before", "2.00 after"]).__next__)
    assert cold_start.main(["--target", "sidecar", "--runs", "2", "--machine", "box"]) == 0
    [written] = results.iterdir()
    assert re.fullmatch(rf"cold-start-box-{STAMP}\.json", written.name)
    [case] = json.loads(written.read_text(encoding="utf-8"))
    assert [sample["total"] for sample in case["samples"]] == [0.7, 0.6]
    assert case["loadavg"] == {"before": "1.00 before", "after": "2.00 after"}


def test_a_cleanup_proof_keeps_what_it_printed(
    monkeypatch: pytest.MonkeyPatch, results: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    def run(case: str, *, death_signal: bool, parent_watch: bool) -> dict[str, Any]:
        print("--- before\n$ ps -o pid … (the processes)")
        return {"case": case, "death signal": death_signal, "watch": parent_watch}

    monkeypatch.setattr(cleanup, "run", run)
    assert cleanup.main(["quit", "--no-parent-pid", "--machine", "box"]) == 0
    [written] = results.iterdir()
    assert re.fullmatch(rf"cleanup-box-{STAMP}-quit-no-parent-pid\.out", written.name)
    text = written.read_text(encoding="utf-8")
    assert "$ ps -o pid … (the processes)" in text
    assert "death signal: True\nwatch: False\n" in text
    assert "loadavg before: " in text
    assert text in capsys.readouterr().out
