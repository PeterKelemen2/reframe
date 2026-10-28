"""The folders guard, in a pytest session whose environment names the owner's folders and
endpoint file: each refusal fails the test that reaches them, and temporary folders pass."""

from __future__ import annotations

from pathlib import Path

import pytest

from reframe_testing import folders_guard

pytest_plugins = ["pytester"]

PLUGIN = ("-p", "reframe_testing.pytest_plugin")

INNER = """
import asyncio
import os
import sys
from pathlib import Path

import pytest

from reframe.queue.lock import StoreLock
from reframe.remote import owner

SESSION_DATA = Path(os.environ["REFRAME_DATA_DIR"])
REACHED = "a test reached the owner's own Reframe files at "


def refused(what):
    return pytest.raises(pytest.fail.Exception, match=REACHED + r".* \\(" + what)


def test_the_lock_of_the_sessions_data_folder():
    with refused("the lock "):
        StoreLock(SESSION_DATA / "queue.lock").acquire()


def test_the_owner_search_of_the_sessions_data_folder():
    with refused("the owner search of "):
        asyncio.run(owner.find_owner(SESSION_DATA, start=False, environ={}))


def test_the_owner_search_with_the_sessions_endpoint_file(tmp_path):
    with refused("the owner search with the endpoint file "):
        asyncio.run(owner.find_owner(tmp_path, start=False))


def test_the_owner_search_with_an_endpoint_file_in_a_real_folder(tmp_path):
    environ = {"REFRAME_ENDPOINT_FILE": str(SESSION_DATA / "other.json")}
    with refused("the owner search with the endpoint file "):
        asyncio.run(owner.find_owner(tmp_path, start=False, environ=environ))


def test_a_server_for_the_sessions_data_folder():
    with refused("a server for "):
        owner._start(["reframe-server"], SESSION_DATA, sys.platform, launcher=lambda *a, **k: 0)


def test_a_real_server_started_from_pytest(tmp_path):
    with pytest.raises(pytest.fail.Exception, match="a test started a real Reframe server"):
        owner._start([sys.executable, "-c", "pass"], tmp_path, sys.platform)


def test_temporary_folders_pass(tmp_path):
    lock = StoreLock(tmp_path / "queue.lock")
    assert lock.acquire().owned
    lock.release()
    found = asyncio.run(owner.find_owner(tmp_path, start=False, environ={}))
    assert isinstance(found, owner.NoOwner)
    process = owner._start(
        [sys.executable, "-c", "pass"],
        tmp_path,
        sys.platform,
        launcher=lambda argv, *, popen, **_: popen(argv).pid,
    )
    assert process.wait(10) == 0
"""


def test_the_guard_refuses_the_sessions_folders_and_endpoint_file(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    real = tmp_path / "owner"
    for name, folder in (
        ("REFRAME_CONFIG_DIR", "config"),
        ("REFRAME_DATA_DIR", "data"),
        ("REFRAME_CACHE_DIR", "cache"),
    ):
        (real / folder).mkdir(parents=True)
        monkeypatch.setenv(name, str(real / folder))
    monkeypatch.setenv("REFRAME_ENDPOINT_FILE", str(real / "endpoint" / "server.json"))
    # A separate pytest process: the guard reads the environment of its session at import.
    monkeypatch.setenv("PYTHONPATH", str(Path(folders_guard.__file__).resolve().parents[1]))
    pytester.makepyfile(test_inner=INNER)
    result = pytester.runpytest_subprocess(*PLUGIN, "-p", "no:cacheprovider")
    result.assert_outcomes(passed=7)
    assert list((real / "data").iterdir()) == []  # nothing was made there
