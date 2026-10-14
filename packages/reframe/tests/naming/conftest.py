from __future__ import annotations

from collections.abc import Callable, Iterator, Mapping
from datetime import datetime
from pathlib import Path

import pytest
from guessit.api import default_api

from reframe.naming import FileTimes, NamingFs
from reframe.naming.parse import guess_matches

#: A fixed "now" for ``{date}`` / ``{time}``: 2026-10-11 14:30, local time.
NOW = datetime(2026, 10, 11, 14, 30, 5).astimezone()


class FakeFs:
    """A file system for naming: folder listings and file times from dictionaries."""

    def __init__(
        self,
        files: Mapping[Path, list[str]] | None = None,
        times: Mapping[Path, FileTimes] | None = None,
    ) -> None:
        self.files = dict(files or {})
        self.times = dict(times or {})
        self.listed: list[Path] = []

    def list_files(self, folder: Path) -> list[str] | None:
        self.listed.append(folder)
        names = self.files.get(folder)
        return None if names is None else sorted(names)

    def file_times(self, file: Path) -> FileTimes | None:
        return self.times.get(file)


type FsFactory = Callable[..., FakeFs]


@pytest.fixture
def fake_fs() -> FsFactory:
    """``fake_fs({folder: [file names]}, {file: FileTimes(...)})``."""
    return FakeFs


@pytest.fixture
def empty_fs() -> NamingFs:
    """No folder can be listed, no file has times (paths that do not exist)."""
    return FakeFs()


@pytest.fixture
def now() -> datetime:
    return NOW


#: Contents of the guessit config files of :func:`guessit_user_config`: one that changes what
#: guessit reports (the episode title of an episode becomes ``alternative_title``), and one
#: that makes every guessit call fail.
GUESSIT_USER_CONFIGS = {"type-movie": '{"type": "movie"}', "malformed": "{not json"}


@pytest.fixture(params=list(GUESSIT_USER_CONFIGS.values()), ids=list(GUESSIT_USER_CONFIGS))
def guessit_user_config(
    request: pytest.FixtureRequest, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Iterator[str]:
    """A guessit config file in every place guessit 4.4.0 reads one from (the working folder,
    ``~/.guessit``, ``~/.config/guessit``) and in ``$XDG_CONFIG_HOME/guessit``, under a fake
    home folder. Yields the file contents.

    guessit loads its config files once per process and keeps them in ``default_api``, so the
    fixture resets it (and the parse cache) before and after the test: else a config loaded
    before the files exist would hide the bug.
    """
    content: str = request.param
    home = tmp_path / "home"
    xdg = tmp_path / "xdg"
    work = tmp_path / "work"
    for folder in (home / ".guessit", home / ".config" / "guessit", xdg / "guessit"):
        folder.mkdir(parents=True)
        for extension in ("json", "yml", "yaml"):
            (folder / f"options.{extension}").write_text(content, encoding="utf-8")
    work.mkdir()
    for extension in ("json", "yml", "yaml"):
        (work / f"guessit.options.{extension}").write_text(content, encoding="utf-8")
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))  # os.path.expanduser on Windows
    monkeypatch.setenv("XDG_CONFIG_HOME", str(xdg))
    monkeypatch.chdir(work)
    default_api.reset()
    guess_matches.cache_clear()
    yield content
    default_api.reset()
    guess_matches.cache_clear()
