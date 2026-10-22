"""The server's own folders (config, data, cache) in an answer: a client sees ``<config>``,
``<data>`` and ``<cache>``, never where the server keeps its files."""

from __future__ import annotations

import functools
import re
from dataclasses import dataclass

from pydantic import JsonValue

from reframe.service import Reframe

__all__ = ["hide_server_folders"]


@dataclass(frozen=True)
class _FolderMask:
    pattern: re.Pattern[str]
    labels: dict[str, str]

    def text(self, text: str) -> str:
        return self.pattern.sub(lambda match: self.labels[match.group(0)], text)

    def value(self, value: JsonValue) -> JsonValue:
        if isinstance(value, str):
            return self.text(value)
        if isinstance(value, list):
            return [self.value(item) for item in value]
        if isinstance(value, dict):
            return {self.text(key): self.value(item) for key, item in value.items()}
        return value


@functools.cache
def _mask(config: str, data: str, cache: str) -> _FolderMask:
    labels: dict[str, str] = {}
    for folder, label in ((config, "<config>"), (data, "<data>"), (cache, "<cache>")):
        labels.setdefault(folder, label)
    # Longest first: on Windows the cache folder is inside the data folder.
    texts = sorted(labels, key=len, reverse=True)
    alternatives = "|".join(re.escape(text) for text in texts)
    # The folder's text inside a longer name ("/srv/data2", "/mnt/srv/data") is another path.
    pattern = re.compile(rf"(?<![\w.\-\\/])(?:{alternatives})(?![\w.\-])")
    return _FolderMask(pattern, labels)


def hide_server_folders(reframe: Reframe, value: JsonValue) -> JsonValue:
    """``value`` with the facade's config, data and cache folders written as ``<config>``,
    ``<data>`` and ``<cache>`` in every string and object key."""
    mask = _mask(str(reframe.config_dir), str(reframe.data_dir), str(reframe.cache_dir))
    return mask.value(value)
