"""User presets (``<config>/presets.json``) and the read-only built-ins, as one list.

Names are compared without case and repeated spaces. Two presets that this Reframe reads never
share a name, except when a newer Reframe adds a built-in with the name of a user preset.
"""

from __future__ import annotations

import copy
import threading
import uuid
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from pydantic import ValidationError

from reframe.events import EventBus
from reframe.models.events import AppWarningEvent
from reframe.models.issues import Fix, ReplaceOp, Severity, ValidationIssue
from reframe.models.migrations import MigrationError, MigrationRegistry, UnsupportedSchemaVersion
from reframe.models.preset import Preset, PresetFile
from reframe.models.template import JobTemplate
from reframe.presets.builtin import DEFAULT_BUILTIN_ID, builtin_presets
from reframe.settings import (
    TOO_DEEP,
    JsonDocumentFile,
    is_newer,
    migrate_document,
    too_deep,
    validation_detail,
)

__all__ = [
    "CUSTOM_CATEGORY",
    "PRESETS_FILE",
    "ConflictPolicy",
    "ImportResult",
    "PresetExport",
    "PresetStore",
    "normalise_name",
]

PRESETS_FILE = "presets.json"
#: The category of new user presets and of copies of built-ins.
CUSTOM_CATEGORY = "Custom"
ConflictPolicy = Literal["rename", "replace", "skip"]

#: A preset entry of the file: a preset, or the raw JSON of one written by a newer Reframe.
_Entry = Preset | dict[str, Any]
# Aliases for annotations inside PresetStore, whose ``list`` method hides the builtin there.
_Entries = list[_Entry]
_Presets = list[Preset]


def normalise_name(name: str) -> str:
    """The form names are compared in: no case, single spaces, no leading or trailing ones."""
    return " ".join(name.split()).casefold()


def _clean_name(name: str) -> str:
    return " ".join(name.split())


@dataclass
class ImportResult:
    """What :meth:`PresetStore.import_` did.

    ``imported``: the presets as stored (with their new id or name). ``renamed``: ``(name in
    the file, name given)``. ``replaced``: names of user presets that were overwritten.
    ``skipped``: names that were not imported (a clash with ``skip``, or a damaged or newer
    preset: see ``issues``).
    """

    imported: list[Preset] = field(default_factory=list)
    renamed: list[tuple[str, str]] = field(default_factory=list)
    replaced: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    issues: list[ValidationIssue] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not any(issue.severity is Severity.ERROR for issue in self.issues)


@dataclass
class PresetExport:
    """What :meth:`PresetStore.export` gives.

    ``file`` holds the presets this Reframe reads (its ``default_preset_id`` is set when the
    default is among them). ``newer`` holds the chosen presets that a newer Reframe wrote, as
    JSON, unchanged. ``default_preset_id`` is the default when it is among all of them.
    ``issues`` has one ``preset.newer_version`` warning for each entry of ``newer``.

    :meth:`document` is the export file: write it, or pass the export to
    :meth:`PresetStore.import_` as it is.
    """

    file: PresetFile
    newer: list[dict[str, Any]] = field(default_factory=list)
    default_preset_id: str | None = None
    issues: list[ValidationIssue] = field(default_factory=list)

    def document(self) -> dict[str, Any]:
        """The export file as JSON: the newer presets come last, unchanged."""
        data = self.file.model_dump(mode="json")
        data["presets"].extend(copy.deepcopy(self.newer))
        data["default_preset_id"] = self.default_preset_id
        return data


def _issue(
    code: str,
    message: str,
    path: str = "",
    fixes: Iterable[Fix] = (),
    *,
    severity: Severity = Severity.ERROR,
) -> ValidationIssue:
    return ValidationIssue(
        severity=severity, code=code, path=path, message=message, fixes=list(fixes)
    )


def _newer_issue(
    label: str, exc: UnsupportedSchemaVersion, what: str, severity: Severity = Severity.WARNING
) -> ValidationIssue:
    """``preset.newer_version``: the preset needs a newer Reframe; ``what`` says what
    happened to it."""
    return _issue(
        "preset.newer_version",
        f"“{label}” was written by a newer Reframe (preset schema version {exc.found}; this "
        f"Reframe reads up to {exc.current}). It needs that Reframe or a later one: {what}.",
        severity=severity,
    )


class PresetStore:
    """Built-in and user presets. Expected failures are values, not exceptions.

    Presets that a newer Reframe wrote are kept as raw JSON and written back unchanged. They
    are not in :meth:`list`, and this Reframe cannot change them. The file is read at the first
    use, not at start.
    """

    def __init__(
        self,
        config_dir: Path,
        events: EventBus | None = None,
        *,
        registry: MigrationRegistry | None = None,
        builtins: Sequence[Preset] | None = None,
    ) -> None:
        self.path = Path(config_dir) / PRESETS_FILE
        # The depth is checked per preset (one deep preset must not damage the whole file).
        self._file = JsonDocumentFile(self.path, max_depth=None)
        self._events = events
        self._registry = registry
        source = builtin_presets() if builtins is None else builtins
        self._builtins = [p.model_copy(update={"built_in": True}, deep=True) for p in source]
        self._builtin_ids = {p.id for p in self._builtins}
        self._entries: list[_Entry] | None = None
        self._default_id: str | None = None
        self._schema_version = int(PresetFile.model_fields["schema_version"].default)
        self._extra: dict[str, Any] = {}
        self._problems: list[AppWarningEvent] = []
        self._protected: str | None = None
        self._lock = threading.RLock()

    @property
    def problems(self) -> list[AppWarningEvent]:
        """The warnings of the last load and of later failed writes."""
        with self._lock:
            self._ensure()
            return list(self._problems)

    @property
    def read_only(self) -> bool:
        """``True`` when ``presets.json`` must not be overwritten (newer or unreadable)."""
        with self._lock:
            self._ensure()
            return self._protected is not None

    @property
    def default_id(self) -> str | None:
        """The user's default preset id (``None``: the built-in default is used)."""
        with self._lock:
            self._ensure()
            return self._default_id

    def load(self) -> list[Preset]:
        """(Re)read ``presets.json``; returns the user presets."""
        with self._lock:
            self._load()
            return self.user_presets()

    def builtins(self) -> list[Preset]:
        return [p.model_copy(deep=True) for p in self._builtins]

    def user_presets(self) -> list[Preset]:
        with self._lock:
            return [p.model_copy(deep=True) for p in self._user()]

    def list(self) -> list[Preset]:
        """Every preset: the built-ins (in their order), then the user presets."""
        with self._lock:
            return self.builtins() + self.user_presets()

    def get(self, preset_id: str) -> Preset | None:
        with self._lock:
            found = self._by_id(preset_id)
            return None if found is None else found.model_copy(deep=True)

    def find(self, name_or_id: str) -> Preset | None:
        """By id, else by name (case-insensitive; user presets first)."""
        with self._lock:
            found = self._by_id(name_or_id)
            if found is None:
                key = normalise_name(name_or_id)
                found = next(
                    (p for p in [*self._user(), *self._builtins] if normalise_name(p.name) == key),
                    None,
                )
            return None if found is None else found.model_copy(deep=True)

    def default(self) -> Preset:
        """The default preset: the user's choice, else the built-in default."""
        with self._lock:
            self._ensure()
            chosen = self._by_id(self._default_id) if self._default_id else None
            if chosen is None:
                chosen = self._by_id(DEFAULT_BUILTIN_ID)
            if chosen is None:
                chosen = (self._builtins or self._user())[0]
            return chosen.model_copy(deep=True)

    def unique_name(self, name: str, *, exclude_id: str | None = None) -> str:
        """``name`` if no other preset has it, else the next free ``name (2)``, ``name (3)`` …"""
        with self._lock:
            base = _clean_name(name)
            if self._name_owner(base, exclude_id) is None:
                return base
            number = 2
            while self._name_owner(f"{base} ({number})", exclude_id) is not None:
                number += 1
            return f"{base} ({number})"

    def create(
        self,
        template: JobTemplate,
        name: str,
        *,
        category: str = CUSTOM_CATEGORY,
        description: str = "",
    ) -> Preset | ValidationIssue:
        """Save ``template`` as a new user preset (of the current preset schema version: the
        template's ``schema_version`` is that of a ``job_template``)."""
        try:
            data = template.model_dump(
                mode="json",
                exclude={"id", "name", "category", "description", "built_in", "schema_version"},
            )
        except (ValueError, TypeError, RecursionError):  # nested far too deeply
            return _issue("preset.invalid", f"The preset is not valid: {TOO_DEEP}")
        data.update(
            id=str(uuid.uuid4()),
            name=_clean_name(name) or name,
            category=category,
            description=description,
            built_in=False,
        )
        try:
            preset = Preset.model_validate(data)
        except ValidationError as exc:
            return _issue("preset.invalid", f"The preset is not valid: {validation_detail(exc)}")
        return self.save(preset)

    def save(self, preset: Preset) -> Preset | ValidationIssue:
        """Add a new user preset, or update the user preset with the same id.

        The preset goes through the file's checks first (migrations, nesting): one of a
        newer Reframe (``preset.newer_version``) or one that a newer Reframe wrote with the
        same id is refused, so the next load never hides or drops it."""
        with self._lock:
            self._ensure()
            if preset.id in self._builtin_ids:
                return self._built_in_issue(preset.id, "changed")
            try:
                parsed = self._parse_entry(preset.model_dump(mode="json"))
            except (ValueError, TypeError, RecursionError):  # nested far too deeply
                parsed = TOO_DEEP
            if isinstance(parsed, UnsupportedSchemaVersion):
                return _newer_issue(
                    preset.name, parsed, "this one cannot save it", severity=Severity.ERROR
                )
            if isinstance(parsed, str):
                return _issue("preset.invalid", f"The preset is not valid: {parsed}")
            if preset.id in self._newer_ids():
                return _issue(
                    "preset.newer_version",
                    f"The preset with the id “{preset.id}” was written by a newer Reframe. It "
                    "needs that Reframe or a later one: this one cannot change it.",
                )
            preset = parsed
            problem = self._check_name(preset.name, preset.id)
            if problem is not None:
                return problem
            stored = preset.model_copy(
                update={"built_in": False, "name": _clean_name(preset.name)}, deep=True
            )
            entries = list(self._entries or [])
            index = self._index(preset.id)
            if index is None:
                entries.append(stored)
            else:
                entries[index] = stored
            return self._commit(entries, self._default_id) or stored.model_copy(deep=True)

    def rename(self, preset_id: str, name: str) -> Preset | ValidationIssue:
        with self._lock:
            current = self._user_preset(preset_id)
            if isinstance(current, ValidationIssue):
                return current
            return self.save(current.model_copy(update={"name": name}))

    def delete(self, preset_id: str) -> Preset | ValidationIssue:
        """Delete a user preset; returns it. If it was the default, the built-in default is
        used again."""
        with self._lock:
            current = self._user_preset(preset_id)
            if isinstance(current, ValidationIssue):
                return current
            entries = [e for e in self._entries or [] if not _is(e, preset_id)]
            default = None if self._default_id == preset_id else self._default_id
            return self._commit(entries, default) or current

    def duplicate(self, preset_id: str, name: str | None = None) -> Preset | ValidationIssue:
        """Copy any preset (built-in or user) as a new user preset. Without ``name``: the next
        free name after the original's."""
        with self._lock:
            self._ensure()
            original = self._by_id(preset_id)
            if original is None:
                return self._not_found(preset_id)
            copy = original.model_copy(
                update={
                    "id": str(uuid.uuid4()),
                    "name": name if name is not None else self.unique_name(original.name),
                    "built_in": False,
                    "category": CUSTOM_CATEGORY if original.built_in else original.category,
                },
                deep=True,
            )
            return self.save(copy)

    def set_default(self, preset_id: str | None) -> Preset | ValidationIssue:
        """Make ``preset_id`` the default (``None``: back to the built-in default). Returns the
        default preset now in effect."""
        with self._lock:
            self._ensure()
            if preset_id is not None and self._by_id(preset_id) is None:
                return self._not_found(preset_id)
            return self._commit(list(self._entries or []), preset_id) or self.default()

    def export(self, ids: Sequence[str] | None = None) -> PresetExport:
        """The given presets (``None``: every user preset) as a :class:`PresetExport`. Unknown
        ids are left out (resolve names with :meth:`find` first). Presets of a newer Reframe
        are exported unchanged (``newer``), each with a warning."""
        with self._lock:
            self._ensure()
            newer_entries = [e for e in self._entries or [] if isinstance(e, dict)]
            if ids is None:
                chosen = self._user()
                newer = newer_entries
            else:
                wanted = list(dict.fromkeys(ids))
                chosen = [p for p in (self._by_id(i) for i in wanted) if p is not None]
                newer = [e for e in newer_entries if e.get("id") in wanted]
            presets = [p.model_copy(deep=True) for p in chosen]
            in_file = {p.id for p in presets}
            everything = in_file | {e.get("id") for e in newer}
            issues = []
            for number, entry in enumerate(newer, start=1):
                parsed = self._parse_entry(entry)
                if isinstance(parsed, UnsupportedSchemaVersion):
                    issues.append(
                        _newer_issue(
                            _entry_label(entry, number),
                            parsed,
                            "it is exported unchanged, and only that Reframe can import it",
                        )
                    )
            return PresetExport(
                file=PresetFile(
                    schema_version=self._schema_version,
                    presets=presets,
                    default_preset_id=self._default_id if self._default_id in in_file else None,
                ),
                newer=copy.deepcopy(newer),
                default_preset_id=self._default_id if self._default_id in everything else None,
                issues=issues,
            )

    def import_(
        self,
        file: PresetFile | PresetExport | Mapping[str, Any],
        on_conflict: ConflictPolicy = "rename",
    ) -> ImportResult:
        """Import presets (a :class:`PresetFile`, a :class:`PresetExport`, or the raw JSON
        object of an export file). All three go through the checks of the file: migrations,
        nesting, and presets of a newer Reframe, which are not imported
        (``preset.newer_version``).

        ``on_conflict``: ``rename`` (the default) gives a clashing id or name a new one;
        ``replace`` overwrites the user preset with the same id or name and keeps its id;
        ``skip`` leaves the clashing preset out. A built-in is never replaced: the imported
        preset gets a new id or name instead."""
        result = ImportResult()
        incoming, default_id = self._incoming(file, result)
        with self._lock:
            self._ensure()
            if self._protected is not None:
                result.issues.append(self._read_only_issue())
                result.skipped.extend(p.name for p in incoming)
                return result
            entries = list(self._entries or [])
            new_ids: dict[str, str] = {}
            for original in incoming:
                placed = self._place(original, entries, on_conflict, result)
                if placed is not None:
                    new_ids[original.id] = placed.id
            if not result.imported:
                return result
            default = self._default_id
            if default is None and default_id is not None and default_id in new_ids:
                default = new_ids[default_id]
            failure = self._commit(entries, default)
            if failure is not None:
                result.issues.append(failure)
                result.skipped.extend(p.name for p in result.imported)
                result.imported, result.renamed, result.replaced = [], [], []
            return result

    def _ensure(self) -> None:
        if self._entries is None:
            self._load()

    def _user(self) -> _Presets:
        self._ensure()
        return [e for e in self._entries or [] if isinstance(e, Preset)]

    def _by_id(self, preset_id: str | None) -> Preset | None:
        if preset_id is None:
            return None
        for preset in [*self._builtins, *self._user()]:
            if preset.id == preset_id:
                return preset
        return None

    def _index(self, preset_id: str) -> int | None:
        for index, entry in enumerate(self._entries or []):
            if _is(entry, preset_id):
                return index
        return None

    def _name_owner(
        self, name: str, exclude_id: str | None, entries: Sequence[_Entry] | None = None
    ) -> Preset | None:
        key = normalise_name(name)
        users = [e for e in (self._entries or []) if isinstance(e, Preset)]
        if entries is not None:
            users = [e for e in entries if isinstance(e, Preset)]
        for preset in [*self._builtins, *users]:
            if preset.id != exclude_id and normalise_name(preset.name) == key:
                return preset
        return None

    def _user_preset(self, preset_id: str) -> Preset | ValidationIssue:
        self._ensure()
        if preset_id in self._builtin_ids:
            return self._built_in_issue(preset_id, "changed or deleted")
        for preset in self._user():
            if preset.id == preset_id:
                return preset
        return self._not_found(preset_id)

    def _check_name(self, name: str, preset_id: str) -> ValidationIssue | None:
        if not _clean_name(name):
            return _issue("preset.name_empty", "A preset needs a name.", "name")
        owner = self._name_owner(name, preset_id)
        if owner is None:
            return None
        suggestion = self.unique_name(name, exclude_id=preset_id)
        kind = "built-in preset" if owner.built_in else "preset"
        return _issue(
            "preset.name_conflict",
            f"A {kind} named “{owner.name}” already exists.",
            "name",
            [
                Fix(
                    label=f"Use “{suggestion}”",
                    patch=[ReplaceOp(path="/name", value=suggestion)],
                    target="template",
                )
            ],
        )

    def _built_in_issue(self, preset_id: str, what: str) -> ValidationIssue:
        name = next((p.name for p in self._builtins if p.id == preset_id), preset_id)
        return _issue(
            "preset.built_in",
            f"“{name}” is a built-in preset and cannot be {what}. Duplicate it to make a copy "
            "you can change.",
        )

    def _not_found(self, preset_id: str) -> ValidationIssue:
        return _issue("preset.not_found", f"There is no preset with the id “{preset_id}”.")

    def _read_only_issue(self) -> ValidationIssue:
        return _issue("presets.read_only", f"The presets were not saved: {self._protected}")

    def _incoming(
        self, file: PresetFile | PresetExport | Mapping[str, Any], result: ImportResult
    ) -> tuple[_Presets, str | None]:
        def invalid(detail: str) -> tuple[_Presets, str | None]:
            result.issues.append(
                _issue("presets.import_invalid", f"The file is not a Reframe preset file: {detail}")
            )
            return [], None

        try:
            if isinstance(file, PresetExport):
                raw_file = file.document()
            elif isinstance(file, PresetFile):
                # As JSON, so its presets get the checks of a file (a newer one is refused).
                raw_file = file.model_dump(mode="json")
            else:
                raw_file = dict(file)
        except (ValueError, TypeError, RecursionError):  # nested far too deeply
            return invalid(TOO_DEEP)
        prepared = _without_deep_presets(raw_file)
        if isinstance(prepared, str):
            return invalid(prepared)
        raw_file, numbers, deep = prepared
        try:
            data = migrate_document("preset_file", raw_file, self._registry)
            header = PresetFile.model_validate({**data, "presets": []})
        except UnsupportedSchemaVersion as exc:
            if is_newer(exc):
                result.issues.append(
                    _issue(
                        "presets.import_newer", f"The file was written by a newer Reframe ({exc})."
                    )
                )
            else:
                result.issues.append(
                    _issue(
                        "presets.import_invalid", f"The file is not a Reframe preset file: {exc}"
                    )
                )
            return [], None
        except (ValidationError, MigrationError, LookupError, TypeError, ValueError) as exc:
            detail = validation_detail(exc) if isinstance(exc, ValidationError) else str(exc)
            result.issues.append(
                _issue("presets.import_invalid", f"The file is not a Reframe preset file: {detail}")
            )
            return [], None
        raw = data.get("presets")
        if not isinstance(raw, list):
            result.issues.append(
                _issue(
                    "presets.import_invalid",
                    "The file is not a Reframe preset file: no preset list.",
                )
            )
            return [], None
        if len(numbers) != len(raw):  # a migration changed the list: count afresh
            numbers = list(range(1, len(raw) + 1))
        outcomes: list[tuple[int, object, Preset | UnsupportedSchemaVersion | str]] = [
            (number, entry, TOO_DEEP) for number, entry in deep
        ]
        outcomes += [
            (number, entry, self._parse_entry(entry))
            for number, entry in zip(numbers, raw, strict=True)
        ]
        presets: list[Preset] = []
        for number, entry, parsed in sorted(outcomes, key=lambda outcome: outcome[0]):
            label = _entry_label(entry, number)
            if isinstance(parsed, Preset):
                presets.append(parsed)
                continue
            result.skipped.append(label)
            if isinstance(parsed, UnsupportedSchemaVersion):
                result.issues.append(_newer_issue(label, parsed, "it was not imported"))
            else:
                result.issues.append(
                    _issue(
                        "preset.invalid",
                        f"“{label}” is not a valid preset and was not imported: {parsed}",
                        severity=Severity.WARNING,
                    )
                )
        return presets, header.default_preset_id

    def _place(
        self,
        original: Preset,
        entries: _Entries,
        on_conflict: ConflictPolicy,
        result: ImportResult,
    ) -> Preset | None:
        """Put one imported preset into ``entries`` (or not); records it in ``result``."""
        preset = original.model_copy(
            update={"built_in": False, "name": _clean_name(original.name) or original.name},
            deep=True,
        )
        same_id = next(
            (i for i, e in enumerate(entries) if isinstance(e, Preset) and e.id == preset.id), None
        )
        id_taken = (
            same_id is not None
            or preset.id in self._builtin_ids
            or preset.id in self._newer_ids(entries)  # never replaced: a new id
        )
        owner = self._name_owner(preset.name, None, entries)
        if on_conflict == "skip" and (id_taken or owner is not None):
            result.skipped.append(preset.name)
            return None
        target: int | None = None
        if on_conflict == "replace":
            target = same_id
            if target is None and owner is not None and not owner.built_in:
                target = next(
                    i for i, e in enumerate(entries) if isinstance(e, Preset) and e.id == owner.id
                )
        if target is not None:
            replaced = entries[target]
            assert isinstance(replaced, Preset)
            preset = preset.model_copy(update={"id": replaced.id})
            result.replaced.append(replaced.name)
        elif id_taken:
            preset = preset.model_copy(update={"id": str(uuid.uuid4())})
        if self._name_owner(preset.name, preset.id, entries) is not None:
            new_name = self._free_name(preset.name, preset.id, entries)
            result.renamed.append((preset.name, new_name))
            preset = preset.model_copy(update={"name": new_name})
        if target is not None:
            entries[target] = preset
        else:
            entries.append(preset)
        result.imported.append(preset.model_copy(deep=True))
        return preset

    def _free_name(self, name: str, preset_id: str, entries: Sequence[_Entry]) -> str:
        number = 2
        while self._name_owner(f"{name} ({number})", preset_id, entries) is not None:
            number += 1
        return f"{name} ({number})"

    def _newer_ids(self, entries: Sequence[_Entry] | None = None) -> set[object]:
        """The ids of the presets of a newer Reframe (kept as raw JSON)."""
        source = self._entries or [] if entries is None else entries
        return {e.get("id") for e in source if isinstance(e, dict)}

    def _parse_entry(self, entry: object) -> Preset | UnsupportedSchemaVersion | str:
        """A preset, the error of a preset of a newer Reframe, or why the entry is damaged."""
        if not isinstance(entry, dict):
            return "not a JSON object"
        if too_deep(entry):
            return TOO_DEEP
        try:
            return Preset.model_validate(migrate_document("preset", entry, self._registry))
        except UnsupportedSchemaVersion as exc:
            return exc if is_newer(exc) else str(exc)
        except ValidationError as exc:
            return validation_detail(exc)
        except RecursionError:
            return TOO_DEEP
        except (MigrationError, LookupError, TypeError, ValueError) as exc:
            return f"migration failed: {exc}"

    def _load(self) -> None:
        self._entries = []
        self._default_id = None
        self._extra = {}
        self._problems = []
        self._protected = None
        self._schema_version = int(PresetFile.model_fields["schema_version"].default)
        read = self._file.read()
        if read.status == "missing":
            return
        if read.status == "unreadable":
            self._protect(
                "presets.unreadable",
                f"The presets file {self.path} cannot be read. Only the built-in presets are "
                "shown, and the file is not changed.",
                read.detail,
            )
            return
        if read.status == "corrupt" or read.data is None:
            self._replace_corrupt(read.detail, keep=[])
            return
        prepared = _without_deep_presets(read.data)
        if isinstance(prepared, str):
            self._replace_corrupt(prepared, keep=[])
            return
        without_deep, numbers, deep = prepared
        try:
            data = migrate_document("preset_file", without_deep, self._registry)
            header = PresetFile.model_validate({**data, "presets": []})
            raw = data.get("presets", [])
            if not isinstance(raw, list):
                raise ValueError("'presets' is not a list")
        except UnsupportedSchemaVersion as exc:
            if not is_newer(exc):
                self._replace_corrupt(str(exc), keep=[])
                return
            self._protect(
                "presets.newer_version",
                f"The presets file {self.path} was written by a newer Reframe. Only the "
                "built-in presets are shown, and the file is not changed.",
                str(exc),
            )
            return
        except (ValidationError, MigrationError, LookupError, TypeError, ValueError) as exc:
            detail = validation_detail(exc) if isinstance(exc, ValidationError) else str(exc)
            self._replace_corrupt(detail, keep=[])
            return
        self._schema_version = header.schema_version
        self._default_id = header.default_preset_id
        self._extra = {k: v for k, v in data.items() if k not in PresetFile.model_fields}
        entries: list[_Entry] = []
        damaged: list[tuple[int, str]] = [
            (number, f"{_entry_label(entry, number)}: {TOO_DEEP}") for number, entry in deep
        ]
        seen_ids: set[str] = set(self._builtin_ids)
        if len(numbers) != len(raw):  # a migration changed the list: count afresh
            numbers = list(range(1, len(raw) + 1))
        for number, entry in zip(numbers, raw, strict=True):
            parsed = self._parse_entry(entry)
            if isinstance(parsed, UnsupportedSchemaVersion):
                assert isinstance(entry, dict)
                entries.append(entry)
                continue
            if not isinstance(parsed, Preset):
                damaged.append((number, f"{_entry_label(entry, number)}: {parsed}"))
                continue
            if parsed.id in seen_ids:
                damaged.append(
                    (number, f"{_entry_label(entry, number)}: the id {parsed.id} is used twice")
                )
                continue
            seen_ids.add(parsed.id)
            entries.append(parsed.model_copy(update={"built_in": False}))
        if damaged:
            self._replace_corrupt("; ".join(text for _, text in sorted(damaged)), keep=entries)
        else:
            self._entries = entries

    def _replace_corrupt(self, detail: str | None, *, keep: _Entries) -> None:
        try:
            backup = self._file.backup()
        except OSError as exc:
            self._entries = [e for e in keep if isinstance(e, Preset)] if keep else []
            self._protect(
                "presets.corrupt",
                f"The presets file {self.path} is damaged and could not be backed up. It is "
                "not changed.",
                f"{detail}; backup failed: {exc}",
            )
            return
        self._entries = keep
        default = self._default_id
        if default is not None and self._by_id(default) is None:
            self._default_id = default if default in self._newer_ids() else None
        error = self._file.write(self._document(keep, self._default_id))
        what = (
            "Some presets were damaged and left out" if keep else "It was replaced by an empty list"
        )
        message = f"The presets file was damaged. It was saved as {backup}. {what}."
        if error is not None:
            message += f" Writing the new file failed: {error}"
        self._warn("presets.corrupt", message, detail)

    def _document(self, entries: Sequence[_Entry], default_id: str | None) -> dict[str, Any]:
        return {
            **self._extra,
            "schema_version": self._schema_version,
            "presets": [e.model_dump(mode="json") if isinstance(e, Preset) else e for e in entries],
            "default_preset_id": default_id,
        }

    def _commit(self, entries: _Entries, default_id: str | None) -> ValidationIssue | None:
        """Write the new state; it takes effect only when the write worked."""
        if self._protected is not None:
            return self._read_only_issue()
        error = self._file.write(self._document(entries, default_id))
        if error is not None:
            self._warn(
                "presets.write_failed", f"The presets could not be saved to {self.path}.", error
            )
            return _issue(
                "presets.write_failed", f"The presets could not be saved to {self.path}: {error}"
            )
        self._entries = entries
        self._default_id = default_id
        return None

    def _protect(self, code: str, message: str, detail: str | None) -> None:
        self._protected = message
        self._warn(code, message, detail)

    def _warn(self, code: str, message: str, detail: str | None = None) -> None:
        event = AppWarningEvent(code=code, message=message, detail=detail)
        self._problems.append(event)
        if self._events is not None:
            self._events.publish(event)


def _is(entry: _Entry, preset_id: str) -> bool:
    return isinstance(entry, Preset) and entry.id == preset_id


def _without_deep_presets(
    data: dict[str, Any],
) -> tuple[dict[str, Any], list[int], list[tuple[int, object]]] | str:
    """Take the presets that are nested too deeply out of a preset file before it is
    migrated (the migrations ``deepcopy`` it, which fails on very deep JSON).

    Returns the file without them, the numbers (from 1) of the presets it keeps, and the
    deep ones with their numbers; or :data:`TOO_DEEP` when the rest of the file is too deep.
    """
    presets = data.get("presets")
    if not isinstance(presets, list):  # the migration or the caller reports it
        return TOO_DEEP if too_deep(data) else (data, [], [])
    header = {key: value for key, value in data.items() if key != "presets"}
    if too_deep(header):
        return TOO_DEEP
    kept: list[object] = []
    numbers: list[int] = []
    deep: list[tuple[int, object]] = []
    for number, entry in enumerate(presets, start=1):
        if too_deep(entry):
            deep.append((number, entry))
        else:
            kept.append(entry)
            numbers.append(number)
    return {**data, "presets": kept}, numbers, deep


def _entry_label(entry: object, number: int) -> str:
    if isinstance(entry, dict) and isinstance(entry.get("name"), str) and entry["name"]:
        return str(entry["name"])
    return f"preset #{number}"
