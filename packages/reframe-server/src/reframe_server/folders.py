"""The server's own folders (config, data, cache) in an answer: a client sees ``<config>``,
``<data>`` and ``<cache>``, never where the server keeps its files."""

from __future__ import annotations

import functools
import re
import sys
from dataclasses import dataclass

from pydantic import JsonValue

from reframe.service import Reframe

__all__ = ["hide_server_folders"]


@dataclass(frozen=True)
class _FolderMask:
    pattern: re.Pattern[str]
    labels: dict[str, str]
    windows: bool

    def text(self, text: str) -> str:
        return self.pattern.sub(self._label, text)

    def _label(self, match: re.Match[str]) -> str:
        return self.labels.get(_key(match.group(0), self.windows), match.group(0))

    def value(self, value: JsonValue) -> JsonValue:
        if isinstance(value, str):
            return self.text(value)
        if isinstance(value, list):
            return [self.value(item) for item in value]
        if isinstance(value, dict):
            return {self.text(key): self.value(item) for key, item in value.items()}
        return value


def _key(text: str, windows: bool) -> str:
    # Windows takes either separator and any case for the same folder, and FFmpeg filter
    # text writes "C\:/Users/...".
    return text.replace("\\:", ":").replace("/", "\\").casefold() if windows else text


def _alternative(folder: str, windows: bool) -> str:
    if not windows:
        return re.escape(folder)
    parts = folder.replace("/", "\\").split("\\")
    return r"[\\/]".join(re.escape(part).replace(":", r"\\?:") for part in parts)


@functools.cache
def _mask(
    config: str, data: str, cache: str, windows: bool = sys.platform == "win32"
) -> _FolderMask:
    labels: dict[str, str] = {}
    texts: list[str] = []
    for folder, label in ((config, "<config>"), (data, "<data>"), (cache, "<cache>")):
        if _key(folder, windows) not in labels:
            labels[_key(folder, windows)] = label
            texts.append(folder)
    # Longest first: on Windows the cache folder is inside the data folder.
    texts.sort(key=len, reverse=True)
    alternatives = "|".join(_alternative(text, windows) for text in texts)
    # The folder's text inside a longer name ("/srv/data2", "/mnt/srv/data") is another path.
    pattern = re.compile(
        rf"(?<![\w.\-\\/])(?:{alternatives})(?![\w.\-])", re.IGNORECASE if windows else 0
    )
    return _FolderMask(pattern, labels, windows)


def hide_server_folders(reframe: Reframe, value: JsonValue) -> JsonValue:
    """``value`` with the facade's config, data and cache folders written as ``<config>``,
    ``<data>`` and ``<cache>`` in every string and object key."""
    mask = _mask(str(reframe.config_dir), str(reframe.data_dir), str(reframe.cache_dir))
    return mask.value(value)
