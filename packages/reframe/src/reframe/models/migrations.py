"""Schema migrations for persisted documents (02 §Cross-cutting rules, rule 4; C-9).

Every persisted document has ``schema_version``. A migration function takes the raw JSON
data of version *N* and returns the data of version *N + 1*; it is registered per document
kind and version::

    @register_migration("settings", from_version=1)
    def _settings_1_to_2(data: dict[str, Any]) -> dict[str, Any]:
        data["queue"]["parallel_jobs"] = data["queue"].pop("parallel", 1)
        return data

:func:`migrate` runs the chain up to the current version (the ``schema_version`` default of
the kind's model) and sets ``schema_version``. Migrations change only what they must, so
unknown fields stay (the models keep them too). A document that has no ``schema_version``
is version 1. A document **newer** than this Reframe raises
:class:`UnsupportedSchemaVersion`: the caller (C-9) keeps the file untouched and reports it.

Embedded documents (the presets inside a ``preset_file``, the ``JobSettings`` inside a queue
row) carry their own ``schema_version``; a container's loader migrates them with their own
kind.
"""

from __future__ import annotations

import copy
from collections.abc import Callable
from typing import Any

from pydantic import BaseModel

from reframe.models.job import JobSettings
from reframe.models.media import MediaSource
from reframe.models.preset import Preset, PresetFile
from reframe.models.settings import AppSettings
from reframe.models.template import JobTemplate

__all__ = [
    "DOCUMENT_MODELS",
    "MigrationError",
    "MigrationRegistry",
    "UnsupportedSchemaVersion",
    "current_version",
    "load_document",
    "migrate",
    "register_migration",
]

Migration = Callable[[dict[str, Any]], dict[str, Any]]

#: Document kind → model. The model's ``schema_version`` default is the current version.
DOCUMENT_MODELS: dict[str, type[BaseModel]] = {
    "settings": AppSettings,
    "preset_file": PresetFile,
    "preset": Preset,
    "job_template": JobTemplate,
    "job_settings": JobSettings,
    "media_source": MediaSource,
}


class MigrationError(ValueError):
    """A migration is missing or failed (a programming error in Reframe)."""


class UnsupportedSchemaVersion(MigrationError):
    """The document is newer than this Reframe (or its version is not a positive integer)."""

    def __init__(self, kind: str, found: object, current: int) -> None:
        super().__init__(
            f"{kind}: schema_version {found!r} is not supported (this Reframe reads up to "
            f"{current})"
        )
        self.kind = kind
        self.found = found
        self.current = current


class MigrationRegistry:
    """Migrations by ``(kind, from_version)``, and the current version of each kind."""

    def __init__(self) -> None:
        self._current: dict[str, int] = {}
        self._steps: dict[tuple[str, int], Migration] = {}

    def add_kind(self, kind: str, current_version: int) -> None:
        if current_version < 1:
            raise ValueError("schema versions start at 1")
        self._current[kind] = current_version

    def current_version(self, kind: str) -> int:
        try:
            return self._current[kind]
        except KeyError:
            raise MigrationError(f"unknown document kind {kind!r}") from None

    def register(self, kind: str, from_version: int) -> Callable[[Migration], Migration]:
        """Decorator: ``fn`` migrates ``kind`` from ``from_version`` to ``from_version + 1``."""

        def decorate(fn: Migration) -> Migration:
            key = (kind, from_version)
            if key in self._steps:
                raise MigrationError(f"{kind}: a migration from version {from_version} exists")
            self._steps[key] = fn
            return fn

        return decorate

    def migrate(self, kind: str, data: dict[str, Any]) -> dict[str, Any]:
        """Return a migrated **copy** of ``data`` (the input is not changed)."""
        current = self.current_version(kind)
        found = data.get("schema_version", 1)
        if isinstance(found, bool) or not isinstance(found, int) or found < 1 or found > current:
            raise UnsupportedSchemaVersion(kind, found, current)
        result = copy.deepcopy(data)
        version = found
        while version < current:
            step = self._steps.get((kind, version))
            if step is None:
                raise MigrationError(f"{kind}: no migration from version {version}")
            result = step(result)
            version += 1
            result["schema_version"] = version
        result["schema_version"] = version
        return result


#: The registry of Reframe's documents.
REGISTRY = MigrationRegistry()
for _kind, _model in DOCUMENT_MODELS.items():
    REGISTRY.add_kind(_kind, int(_model.model_fields["schema_version"].default))


def register_migration(kind: str, from_version: int) -> Callable[[Migration], Migration]:
    """Register a migration of ``kind`` from ``from_version`` (see the module doc)."""
    return REGISTRY.register(kind, from_version)


def current_version(kind: str) -> int:
    return REGISTRY.current_version(kind)


def migrate(kind: str, data: dict[str, Any]) -> dict[str, Any]:
    """``migrate(kind, data) -> data``: bring ``data`` to the current schema version."""
    return REGISTRY.migrate(kind, data)


def load_document(kind: str, data: dict[str, Any]) -> BaseModel:
    """Migrate ``data`` and validate it with the kind's model."""
    return DOCUMENT_MODELS[kind].model_validate(migrate(kind, data))
