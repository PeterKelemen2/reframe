"""C-9 settings store: ``<config>/settings.json`` with migrations, atomic writes and the
damaged / newer / unreadable file handling.

"Done when" (05 §C-9) parts proved here: an old-schema settings file loads after migration
(:func:`test_old_schema_fixture_loads_after_migration`, with a test registry, and
:func:`test_real_loader_runs_the_migration_registry` for the real ``migrate()``), and a corrupt
file is backed up and replaced with defaults plus a warning event
(:func:`test_corrupt_file_is_backed_up_and_replaced_with_defaults`).
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from typing import Any

import pytest

from reframe import settings as settings_module
from reframe.events import EventBus, Subscription
from reframe.models import AppSettings, AppWarningEvent, Event
from reframe.models import migrations as migrations_module
from reframe.models.migrations import MigrationRegistry
from reframe.settings import (
    REPLACE_ATTEMPTS,
    JsonDocumentFile,
    SettingsStore,
    migrate_document,
    replace_file,
)

#: settings.json as a (made-up) schema version 1 wrote it: the queue setting was called
#: ``parallel``; version 2 renamed it to ``parallel_jobs``. Plus a field this Reframe does not
#: know, which must survive.
OLD_SETTINGS_V1: dict[str, Any] = {
    "schema_version": 1,
    "tools": {"ffmpeg": "/opt/ffmpeg/bin/ffmpeg"},
    "queue": {"parallel": 3, "when_done": "notify"},
    "languages": {"preferred_audio": ["hu", "en"]},
    "from_the_future": {"keep": ["me"]},
}


def registry_v2() -> MigrationRegistry:
    """A registry in which ``settings`` is at version 2 (1 → 2 renames ``queue.parallel``)."""
    registry = MigrationRegistry()
    registry.add_kind("settings", 2)

    @registry.register("settings", from_version=1)
    def _rename_parallel(data: dict[str, Any]) -> dict[str, Any]:
        queue = data.setdefault("queue", {})
        if "parallel" in queue:
            queue["parallel_jobs"] = queue.pop("parallel")
        return data

    return registry


def drain(subscription: Subscription) -> list[Event]:
    events = []
    while (event := subscription.get_nowait()) is not None:
        events.append(event)
    return events


def write_json(path: Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


# --------------------------------------------------------------------------- loading


def test_missing_file_gives_defaults_and_writes_nothing(tmp_path: Path) -> None:
    store = SettingsStore(tmp_path / "config")
    assert store.load() == AppSettings()
    assert store.problems == []
    assert not store.read_only
    assert not (tmp_path / "config").exists()


def test_save_then_load_round_trip_keeps_unknown_fields(tmp_path: Path) -> None:
    store = SettingsStore(tmp_path)
    settings = AppSettings.model_validate(
        {"queue": {"parallel_jobs": 2, "new_queue_knob": True}, "new_section": {"a": 1}}
    )
    store.save(settings)
    data = json.loads((tmp_path / "settings.json").read_text("utf-8"))
    assert data["new_section"] == {"a": 1}
    assert data["queue"]["new_queue_knob"] is True
    loaded = SettingsStore(tmp_path).load()
    assert loaded == settings
    assert loaded.model_dump(mode="json") == settings.model_dump(mode="json")


def test_old_schema_fixture_loads_after_migration(tmp_path: Path) -> None:
    write_json(tmp_path / "settings.json", OLD_SETTINGS_V1)
    store = SettingsStore(tmp_path, registry=registry_v2())
    settings = store.load()
    assert store.problems == []
    assert settings.schema_version == 2
    assert settings.queue.parallel_jobs == 3
    assert settings.queue.when_done == "notify"
    assert settings.tools.ffmpeg == Path("/opt/ffmpeg/bin/ffmpeg")
    assert settings.languages.preferred_audio == ["hu", "en"]
    # The unknown field is kept and written back; the file itself is not touched by a load.
    assert json.loads((tmp_path / "settings.json").read_text("utf-8")) == OLD_SETTINGS_V1
    store.save(settings)
    saved = json.loads((tmp_path / "settings.json").read_text("utf-8"))
    assert saved["schema_version"] == 2
    assert saved["queue"]["parallel_jobs"] == 3
    assert "parallel" not in saved["queue"]
    assert saved["from_the_future"] == {"keep": ["me"]}


def test_real_loader_runs_the_migration_registry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Without ``registry=`` the store uses ``reframe.models.migrations.migrate`` (the real
    registry): swap that registry and the same fixture migrates."""
    monkeypatch.setattr(migrations_module, "REGISTRY", registry_v2())
    write_json(tmp_path / "settings.json", OLD_SETTINGS_V1)
    settings = SettingsStore(tmp_path).load()
    assert settings.schema_version == 2
    assert settings.queue.parallel_jobs == 3


def test_current_files_need_no_migration() -> None:
    data = AppSettings().model_dump(mode="json")
    assert migrate_document("settings", data) == data


def test_corrupt_file_is_backed_up_and_replaced_with_defaults(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    path.write_text('{"queue": {"parallel_jobs": 2,', encoding="utf-8")
    bus = EventBus()
    events = bus.subscribe()
    store = SettingsStore(tmp_path, bus)
    assert store.load() == AppSettings()
    backups = list(tmp_path.glob("settings.corrupt-*.json"))
    assert len(backups) == 1
    assert backups[0].read_text("utf-8") == '{"queue": {"parallel_jobs": 2,'
    assert json.loads(path.read_text("utf-8")) == AppSettings().model_dump(mode="json")
    [event] = drain(events)
    assert isinstance(event, AppWarningEvent)
    assert event.code == "settings.corrupt"
    assert str(backups[0]) in event.message
    assert event.detail is not None
    assert "not valid JSON" in event.detail
    assert store.problems == [event]
    assert not store.read_only


@pytest.mark.parametrize(
    ("content", "detail"),
    [
        ("[1, 2, 3]", "not a JSON object"),
        ('{"queue": {"parallel_jobs": 99}}', "queue.parallel_jobs"),
        ('{"preview": {"cache_size_mb": NaN}}', "preview.cache_size_mb"),
        (b"\xff\xfe\x00garbage", "not valid JSON"),
    ],
)
def test_damaged_contents_count_as_corrupt(
    tmp_path: Path, content: str | bytes, detail: str
) -> None:
    path = tmp_path / "settings.json"
    if isinstance(content, bytes):
        path.write_bytes(content)
    else:
        path.write_text(content, encoding="utf-8")
    store = SettingsStore(tmp_path)
    assert store.load() == AppSettings()
    [problem] = store.problems
    assert problem.code == "settings.corrupt"
    assert problem.detail is not None
    assert detail in problem.detail
    assert len(list(tmp_path.glob("settings.corrupt-*.json"))) == 1


def test_a_failing_migration_counts_as_corrupt(tmp_path: Path) -> None:
    registry = MigrationRegistry()
    registry.add_kind("settings", 2)

    @registry.register("settings", from_version=1)
    def _broken(data: dict[str, Any]) -> dict[str, Any]:
        return {"queue": data["no such key"]}

    write_json(tmp_path / "settings.json", {"schema_version": 1})
    store = SettingsStore(tmp_path, registry=registry)
    assert store.load() == AppSettings()
    assert [p.code for p in store.problems] == ["settings.corrupt"]


def test_newer_file_is_kept_untouched_and_never_overwritten(tmp_path: Path) -> None:
    newer = {"schema_version": 7, "queue": {"parallel_jobs": 4}, "brand_new": True}
    write_json(tmp_path / "settings.json", newer)
    before = (tmp_path / "settings.json").read_bytes()
    bus = EventBus()
    events = bus.subscribe()
    store = SettingsStore(tmp_path, bus)
    assert store.load() == AppSettings()
    assert store.read_only
    [event] = drain(events)
    assert isinstance(event, AppWarningEvent)
    assert event.code == "settings.newer_version"
    assert event.detail is not None
    assert "7" in event.detail
    # Saving is refused with a warning, and the file stays as it was.
    store.save(AppSettings.model_validate({"queue": {"parallel_jobs": 2}}))
    [refused] = drain(events)
    assert isinstance(refused, AppWarningEvent)
    assert refused.code == "settings.not_saved"
    assert (tmp_path / "settings.json").read_bytes() == before
    assert list(tmp_path.glob("settings.corrupt-*")) == []


def test_unreadable_file_is_not_overwritten(tmp_path: Path) -> None:
    (tmp_path / "settings.json").mkdir()  # a folder where the file should be
    store = SettingsStore(tmp_path)
    assert store.load() == AppSettings()
    assert [p.code for p in store.problems] == ["settings.unreadable"]
    assert store.read_only
    warning = store.write(AppSettings())
    assert warning is not None
    assert warning.code == "settings.not_saved"
    assert (tmp_path / "settings.json").is_dir()


@pytest.mark.skipif(sys.platform == "win32" or os.geteuid() == 0, reason="POSIX permissions")
def test_permission_denied_on_read_is_unreadable(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    write_json(path, {"queue": {"parallel_jobs": 2}})
    path.chmod(0)
    try:
        store = SettingsStore(tmp_path)
        assert store.load() == AppSettings()
        [problem] = store.problems
        assert problem.code == "settings.unreadable"
        assert problem.detail is not None
        assert "denied" in problem.detail.lower()
    finally:
        path.chmod(0o600)


@pytest.mark.skipif(sys.platform == "win32" or os.geteuid() == 0, reason="POSIX permissions")
def test_permission_denied_on_write_is_a_warning(tmp_path: Path) -> None:
    folder = tmp_path / "config"
    folder.mkdir()
    folder.chmod(0o500)
    bus = EventBus()
    events = bus.subscribe()
    try:
        store = SettingsStore(folder, bus)
        store.save(AppSettings())  # no exception
        [event] = drain(events)
        assert isinstance(event, AppWarningEvent)
        assert event.code == "settings.write_failed"
        assert store.problems == [event]
    finally:
        folder.chmod(0o700)
    assert list(folder.iterdir()) == []


def test_corrupt_file_that_cannot_be_backed_up_is_left_alone(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "settings.json"
    path.write_text("{", encoding="utf-8")

    def fail(source: Path, target: Path) -> None:
        raise PermissionError(13, "Permission denied", str(source))

    monkeypatch.setattr(settings_module, "_replace", fail)
    store = SettingsStore(tmp_path)
    assert store.load() == AppSettings()
    [problem] = store.problems
    assert problem.code == "settings.corrupt"
    assert problem.detail is not None
    assert "backup failed" in problem.detail
    assert store.read_only
    assert path.read_text("utf-8") == "{"


def test_utf8_bom_is_accepted(tmp_path: Path) -> None:
    (tmp_path / "settings.json").write_bytes(
        b"\xef\xbb\xbf" + json.dumps({"queue": {"parallel_jobs": 2}}).encode()
    )
    store = SettingsStore(tmp_path)
    assert store.load().queue.parallel_jobs == 2
    assert store.problems == []


# --------------------------------------------------------------------------- writing


def test_write_is_atomic_and_leaves_no_temporary_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = SettingsStore(tmp_path)
    store.save(AppSettings.model_validate({"queue": {"parallel_jobs": 2}}))
    before = (tmp_path / "settings.json").read_bytes()
    seen: list[tuple[Path, Path]] = []

    def crash(source: Path, target: Path) -> None:
        seen.append((source, target))
        raise OSError(28, "No space left on device", str(target))

    monkeypatch.setattr(settings_module, "_replace", crash)
    warning = store.write(AppSettings.model_validate({"queue": {"parallel_jobs": 3}}))
    assert warning is not None
    assert warning.code == "settings.write_failed"
    assert warning.detail is not None
    assert "No space left" in warning.detail
    # The new content went to a temporary file in the same folder, never into the target.
    [(source, target)] = seen
    assert source.parent == tmp_path
    assert source.name.startswith(".settings.json.")
    assert target == tmp_path / "settings.json"
    assert (tmp_path / "settings.json").read_bytes() == before
    assert sorted(p.name for p in tmp_path.iterdir()) == ["settings.json"]


def test_written_file_is_readable_json_with_a_newline(tmp_path: Path) -> None:
    JsonDocumentFile(tmp_path / "x" / "doc.json").write({"name": "Magyar 5.1", "n": 1})
    text = (tmp_path / "x" / "doc.json").read_text("utf-8")
    assert text.endswith("}\n")
    assert json.loads(text) == {"name": "Magyar 5.1", "n": 1}


def test_unserialisable_data_is_a_failure_not_an_exception(tmp_path: Path) -> None:
    error = JsonDocumentFile(tmp_path / "doc.json").write({"bad": object()})
    assert error is not None
    assert list(tmp_path.iterdir()) == []


class FlakyReplace:
    """``os.replace`` that fails ``failures`` times with a Windows sharing violation."""

    def __init__(self, failures: int) -> None:
        self.failures = failures
        self.calls = 0

    def __call__(self, source: Path, target: Path) -> None:
        self.calls += 1
        if self.calls <= self.failures:
            # ERROR_SHARING_VIOLATION as Python reports it on Windows
            raise PermissionError(13, "The process cannot access the file", str(target))
        os.replace(source, target)


def test_windows_sharing_violation_is_retried(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    flaky = FlakyReplace(failures=2)
    sleeps: list[float] = []
    monkeypatch.setattr(settings_module, "WINDOWS", True)
    monkeypatch.setattr(settings_module, "_replace", flaky)
    monkeypatch.setattr(settings_module, "_sleep", sleeps.append)
    store = SettingsStore(tmp_path)
    assert store.write(AppSettings.model_validate({"queue": {"parallel_jobs": 2}})) is None
    assert flaky.calls == 3
    assert sleeps == [0.05, 0.1]
    assert SettingsStore(tmp_path).load().queue.parallel_jobs == 2


def test_windows_gives_up_after_the_last_attempt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    flaky = FlakyReplace(failures=100)
    monkeypatch.setattr(settings_module, "WINDOWS", True)
    monkeypatch.setattr(settings_module, "_replace", flaky)
    monkeypatch.setattr(settings_module, "_sleep", lambda seconds: None)
    warning = SettingsStore(tmp_path).write(AppSettings())
    assert warning is not None
    assert warning.code == "settings.write_failed"
    assert flaky.calls == REPLACE_ATTEMPTS
    assert list(tmp_path.iterdir()) == []  # the temporary file is gone


def test_permission_error_is_not_retried_on_linux(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    flaky = FlakyReplace(failures=1)
    monkeypatch.setattr(settings_module, "WINDOWS", False)
    monkeypatch.setattr(settings_module, "_replace", flaky)
    with pytest.raises(PermissionError):
        replace_file(tmp_path / "a", tmp_path / "b")
    assert flaky.calls == 1


def test_other_os_errors_are_not_retried_on_windows(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[int] = []

    def gone(source: Path, target: Path) -> None:
        calls.append(1)
        raise FileNotFoundError(2, "No such file", str(source))

    monkeypatch.setattr(settings_module, "WINDOWS", True)
    monkeypatch.setattr(settings_module, "_replace", gone)
    with pytest.raises(FileNotFoundError):
        replace_file(tmp_path / "a", tmp_path / "b")
    assert calls == [1]


def test_backup_names_do_not_collide(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(time, "strftime", lambda fmt: "20261013-120000")
    file = JsonDocumentFile(tmp_path / "presets.json")
    names = []
    for content in ("a", "b", "c"):
        (tmp_path / "presets.json").write_text(content, encoding="utf-8")
        names.append(file.backup().name)
    assert names == [
        "presets.corrupt-20261013-120000.json",
        "presets.corrupt-20261013-120000-2.json",
        "presets.corrupt-20261013-120000-3.json",
    ]


# --------------------------------------------------------------------------- M2 review fixes


def nested(depth: int) -> list[Any]:
    """A list nested ``depth`` levels deep (built without recursion)."""
    value: list[Any] = []
    for _ in range(depth - 1):
        value = [value]
    return value


@pytest.mark.parametrize("depth", [100, 600, 100_000])
def test_deeply_nested_file_is_corrupt_not_a_crash(tmp_path: Path, depth: int) -> None:
    """A deeply nested settings.json raised ``RecursionError`` from ``load()`` (in
    ``Reframe.__init__``, so the app did not start). It is a damaged file now."""
    path = tmp_path / "settings.json"
    text = '{"x": ' + "[" * depth + "]" * depth + "}"
    path.write_text(text, encoding="utf-8")
    store = SettingsStore(tmp_path)
    assert store.load() == AppSettings()
    [problem] = store.problems
    assert problem.code == "settings.corrupt"
    assert problem.detail is not None
    assert "nested" in problem.detail
    [backup] = tmp_path.glob("settings.corrupt-*.json")
    assert backup.read_text("utf-8") == text
    assert json.loads(path.read_text("utf-8")) == AppSettings().model_dump(mode="json")


def test_nesting_up_to_the_limit_is_fine(tmp_path: Path) -> None:
    value = nested(settings_module.MAX_DEPTH - 1)  # plus the settings object itself
    store = SettingsStore(tmp_path)
    assert store.write(AppSettings.model_validate({"x": value})) is None
    assert store.load().model_dump(mode="json")["x"] == value
    assert store.problems == []


@pytest.mark.parametrize("depth", [100, 400])
def test_too_deep_settings_are_not_saved_and_no_exception(tmp_path: Path, depth: int) -> None:
    """A document the loader would reject as damaged is never written (400 levels also made
    Pydantic's ``model_dump`` raise)."""
    store = SettingsStore(tmp_path)
    store.save(AppSettings.model_validate({"queue": {"parallel_jobs": 2}}))
    before = (tmp_path / "settings.json").read_bytes()
    warning = store.write(AppSettings.model_validate({"x": nested(depth)}))
    assert warning is not None
    assert warning.code == "settings.write_failed"
    assert (tmp_path / "settings.json").read_bytes() == before


def test_too_deep_counts_levels_without_recursion() -> None:
    assert not settings_module.too_deep({"a": [1, {"b": 2}]}, 3)
    assert settings_module.too_deep({"a": [1, {"b": []}]}, 3)
    assert not settings_module.too_deep("text", 0)
    assert settings_module.too_deep(nested(1_000_000), 64)


def test_the_store_writes_the_current_schema_version(tmp_path: Path) -> None:
    """A settings object labelled with another version is written as the current version:
    the content is what this Reframe's model holds, and a newer label would make the next
    start treat the file as newer and use the defaults."""
    store = SettingsStore(tmp_path)
    assert store.write(AppSettings.model_validate({"schema_version": 7})) is None
    saved = json.loads((tmp_path / "settings.json").read_text("utf-8"))
    assert saved["schema_version"] == 1
    again = SettingsStore(tmp_path)
    again.load()
    assert again.problems == []
    v2 = SettingsStore(tmp_path, registry=registry_v2())
    assert v2.write(AppSettings()) is None
    assert json.loads((tmp_path / "settings.json").read_text("utf-8"))["schema_version"] == 2


def symlink_or_skip(link: Path, target: Path) -> None:
    try:
        link.symlink_to(target)
    except (OSError, NotImplementedError) as exc:  # Windows without the privilege
        pytest.skip(f"cannot make a symbolic link: {exc}")


def test_a_linked_settings_file_is_written_through_the_link(tmp_path: Path) -> None:
    """``os.replace`` onto the link replaced the link with a regular file. The new content
    goes to the link's target now, and the link stays."""
    dotfiles = tmp_path / "dotfiles"
    dotfiles.mkdir()
    real = dotfiles / "reframe-settings.json"
    write_json(real, {"queue": {"parallel_jobs": 2}})
    config = tmp_path / "config"
    config.mkdir()
    link = config / "settings.json"
    symlink_or_skip(link, real)
    store = SettingsStore(config)
    assert store.load().queue.parallel_jobs == 2
    assert store.write(AppSettings.model_validate({"queue": {"parallel_jobs": 3}})) is None
    assert link.is_symlink()
    assert json.loads(real.read_text("utf-8"))["queue"]["parallel_jobs"] == 3
    assert sorted(p.name for p in config.iterdir()) == ["settings.json"]
    assert sorted(p.name for p in dotfiles.iterdir()) == ["reframe-settings.json"]


def test_a_damaged_linked_file_is_backed_up_next_to_its_target(tmp_path: Path) -> None:
    dotfiles = tmp_path / "dotfiles"
    dotfiles.mkdir()
    real = dotfiles / "settings.json"
    real.write_text("{", encoding="utf-8")
    config = tmp_path / "config"
    config.mkdir()
    link = config / "settings.json"
    symlink_or_skip(link, real)
    store = SettingsStore(config)
    assert store.load() == AppSettings()
    [problem] = store.problems
    assert problem.code == "settings.corrupt"
    [backup] = dotfiles.glob("settings.corrupt-*.json")
    assert backup.read_text("utf-8") == "{"
    assert str(backup) in problem.message
    assert link.is_symlink()
    assert json.loads(real.read_text("utf-8")) == AppSettings().model_dump(mode="json")
    assert sorted(p.name for p in config.iterdir()) == ["settings.json"]


def test_a_dangling_link_gets_its_target_written(tmp_path: Path) -> None:
    config = tmp_path / "config"
    config.mkdir()
    real = tmp_path / "elsewhere" / "settings.json"
    link = config / "settings.json"
    symlink_or_skip(link, real)
    store = SettingsStore(config)
    assert store.load() == AppSettings()
    assert store.write(AppSettings()) is None
    assert link.is_symlink()
    assert json.loads(real.read_text("utf-8")) == AppSettings().model_dump(mode="json")


def test_a_link_loop_is_unreadable_and_never_written(tmp_path: Path) -> None:
    symlink_or_skip(tmp_path / "settings.json", tmp_path / "other.json")
    symlink_or_skip(tmp_path / "other.json", tmp_path / "settings.json")
    store = SettingsStore(tmp_path)
    assert store.load() == AppSettings()
    assert [p.code for p in store.problems] == ["settings.unreadable"]
    warning = store.write(AppSettings())
    assert warning is not None
    assert warning.code == "settings.not_saved"
    assert (tmp_path / "settings.json").is_symlink()
    assert sorted(p.name for p in tmp_path.iterdir()) == ["other.json", "settings.json"]


def test_windows_link_target_is_written_mock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The Windows path, with mocks (no symbolic link needed): the read, the backup and the
    write go to the link's target (as ``os.path.realpath`` gives it), never onto the link,
    and the sharing-violation retry still works there."""
    config = tmp_path / "config"
    config.mkdir()
    real = tmp_path / "OneDrive" / "settings.json"
    real.parent.mkdir()
    real.write_text("{", encoding="utf-8")
    link = config / "settings.json"
    monkeypatch.setattr(settings_module, "WINDOWS", True)
    monkeypatch.setattr(
        settings_module, "_link_target", lambda path: real if path == link else path
    )
    flaky = FlakyReplace(failures=1)
    seen: list[tuple[Path, Path]] = []

    def replace(source: Path, target: Path) -> None:
        seen.append((source, target))
        flaky(source, target)

    monkeypatch.setattr(settings_module, "_replace", replace)
    monkeypatch.setattr(settings_module, "_sleep", lambda seconds: None)
    store = SettingsStore(config)
    store.load()  # reads "{" through the "link": damaged
    [problem] = store.problems
    assert problem.code == "settings.corrupt"
    assert seen
    assert all(target.parent == real.parent for _, target in seen)
    assert all(source.parent == real.parent for source, _ in seen)
    assert json.loads(real.read_text("utf-8")) == AppSettings().model_dump(mode="json")
    assert len(list(real.parent.glob("settings.corrupt-*.json"))) == 1
    assert not link.exists()  # the mock "link" was never written
