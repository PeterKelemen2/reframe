"""A test never reaches the owner's own Reframe folders: the queue lock, the owner search (which
reads ``server.json`` and may start a server) and a started server are refused in the
platform's default folders and in the folders that the session's environment named, and the
owner search is refused the endpoint file that the session's environment named. A test that
would start a real server process from the pytest process fails too: real-process tests run the
CLI as a subprocess with private folders and kill what they started."""

from __future__ import annotations

import os
from collections.abc import Iterator, Sequence
from pathlib import Path
from typing import Any

import platformdirs
import pytest

from reframe import paths

__all__ = ["guard_reframe_folders", "real_endpoint_file", "real_folders"]

#: The environment before any test changed it.
_SESSION_ENV = dict(os.environ)


def real_folders() -> list[Path]:
    """The owner's folders: the platform defaults, and the ``REFRAME_*_DIR`` folders of the
    session's environment."""
    folders = [
        platformdirs.user_config_path(paths.APP_NAME, appauthor=False),
        platformdirs.user_data_path(paths.APP_NAME, appauthor=False),
        platformdirs.user_cache_path(paths.APP_NAME, appauthor=False),
    ]
    for name in (paths.CONFIG_DIR_ENV, paths.DATA_DIR_ENV, paths.CACHE_DIR_ENV):
        value = _SESSION_ENV.get(name, "").strip()
        if value:
            folders.append(Path(value).expanduser())
    return [folder.absolute() for folder in folders]


def real_endpoint_file() -> Path | None:
    """The endpoint file that the session's environment named, read as the client reads it.
    Needs the ``[cli]`` extra."""
    from reframe.remote.owner import ENDPOINT_ENV

    value = _SESSION_ENV.get(ENDPOINT_ENV, "").strip()
    return Path(os.path.abspath(value)) if value else None


def _refuse(path: Path, folders: Sequence[Path], what: str) -> None:
    resolved = Path(os.path.abspath(path))
    for folder in folders:
        if resolved == folder or resolved.is_relative_to(folder):
            pytest.fail(
                f"a test reached the owner's own Reframe files at {folder} ({what} {path}): set "
                "REFRAME_CONFIG_DIR, REFRAME_DATA_DIR and REFRAME_CACHE_DIR to temporary "
                "folders, and REFRAME_ENDPOINT_FILE to a temporary file or not at all",
                pytrace=True,
            )


@pytest.fixture(autouse=True)
def guard_reframe_folders(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    from reframe.queue import lock

    folders = real_folders()
    acquire = lock.StoreLock.acquire

    def guarded_acquire(self: lock.StoreLock) -> lock.LockResult:
        _refuse(self.path, folders, "the lock")
        return acquire(self)

    monkeypatch.setattr(lock.StoreLock, "acquire", guarded_acquire)
    try:
        from reframe.platform.childproc import launch_detached
        from reframe.remote import owner
    except ImportError:  # the [cli] extra is not installed
        yield
        return
    endpoint = real_endpoint_file()
    endpoints = [*folders, *([] if endpoint is None else [endpoint])]
    run = owner.OwnerSearch.run

    async def guarded_run(self: owner.OwnerSearch) -> owner.Owner | owner.NoOwner:
        _refuse(self.data_dir, folders, "the owner search of")
        _refuse(self.endpoint_file, endpoints, "the owner search with the endpoint file")
        return await run(self)

    start = owner._start

    def guarded_start(argv: Sequence[str], data_dir: Path, *args: Any, **options: Any) -> Any:
        _refuse(data_dir, folders, "a server for")
        if options.get("launcher", launch_detached) is launch_detached:
            pytest.fail(
                "a test started a real Reframe server from the pytest process: give the owner "
                "search a fake launcher, or run the CLI as a subprocess with private folders",
                pytrace=True,
            )
        return start(argv, data_dir, *args, **options)

    monkeypatch.setattr(owner.OwnerSearch, "run", guarded_run)
    monkeypatch.setattr(owner, "_start", guarded_start)
    yield
