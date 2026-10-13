"""C-9 preset store: CRUD, default, export / import with name conflicts, migrations, and the
damaged / newer / unreadable file handling of ``<config>/presets.json``.

"Done when" (05 §C-9) parts proved here:

- an old-schema fixture loads after migration: :func:`test_old_schema_fixture_loads_after_migration`
  (``fixtures/presets-v1.json`` with a test registry) and
  :func:`test_real_loader_runs_the_migration_registry` (the real ``migrate()`` path);
- export → import gives the same result: :func:`test_export_import_gives_the_same_result`
  and the property :func:`test_export_import_round_trip_property`;
- a corrupt file is backed up and replaced with defaults plus a warning event:
  :func:`test_corrupt_file_is_backed_up_and_replaced_with_defaults`.
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from reframe import settings as settings_module
from reframe.events import EventBus, Subscription
from reframe.jsonpatch import apply_patch
from reframe.models import (
    AppWarningEvent,
    ConstantQuality,
    Event,
    JobTemplate,
    Preset,
    PresetFile,
    ReplaceOp,
    ValidationIssue,
)
from reframe.models import migrations as migrations_module
from reframe.models.migrations import MigrationRegistry
from reframe.presets import DEFAULT_BUILTIN_ID, PresetStore, builtin_presets

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def drain(subscription: Subscription) -> list[Event]:
    events = []
    while (event := subscription.get_nowait()) is not None:
        events.append(event)
    return events


def registry_v2() -> MigrationRegistry:
    """``preset_file`` and ``preset`` at version 2 (see ``fixtures/presets-v1.json``):

    - ``preset_file`` 1 → 2: the default was stored as ``default`` (now ``default_preset_id``);
    - ``preset`` 1 → 2: the quality was ``video.quality`` (now ``video.rate_control``).
    """
    registry = MigrationRegistry()
    registry.add_kind("preset_file", 2)
    registry.add_kind("preset", 2)

    @registry.register("preset_file", from_version=1)
    def _file(data: dict[str, Any]) -> dict[str, Any]:
        data["default_preset_id"] = data.pop("default", None)
        return data

    @registry.register("preset", from_version=1)
    def _preset(data: dict[str, Any]) -> dict[str, Any]:
        video = data.setdefault("video", {})
        if "quality" in video:
            video["rate_control"] = {"mode": "quality", "value": video.pop("quality")}
        return data

    return registry


def template(**video: Any) -> JobTemplate:
    return JobTemplate.model_validate({"video": video} if video else {})


@pytest.fixture
def store(tmp_path: Path) -> PresetStore:
    return PresetStore(tmp_path)


def created(store: PresetStore, name: str, **video: Any) -> Preset:
    result = store.create(template(**video), name)
    assert isinstance(result, Preset), result
    return result


# --------------------------------------------------------------------------- reading


def test_builtins_come_first_and_user_presets_after(store: PresetStore) -> None:
    mine = created(store, "Mine")
    names = [p.name for p in store.list()]
    assert names[: len(builtin_presets())] == [p.name for p in builtin_presets()]
    assert names[-1] == "Mine"
    assert store.user_presets() == [mine]


def test_nothing_is_written_until_a_change(tmp_path: Path) -> None:
    store = PresetStore(tmp_path / "config")
    assert store.user_presets() == []
    assert store.default().id == DEFAULT_BUILTIN_ID
    assert not (tmp_path / "config").exists()


def test_find_by_id_or_name_without_case(store: PresetStore) -> None:
    found = store.find("  h.265   MKV 1080P ")
    assert found is not None
    assert found.id == "h265-mkv-1080p"
    assert store.find("h265-mkv-1080p") == found
    assert store.find("No such preset") is None
    assert store.get("h265-nvenc-1080p") is not None
    assert store.get("nope") is None


def test_returned_presets_are_copies(store: PresetStore) -> None:
    mine = created(store, "Mine")
    mine.name = "Changed"
    got = store.get(mine.id)
    assert got is not None
    assert got.name == "Mine"
    builtin = store.get("fast-1080p30")
    assert builtin is not None
    builtin.video.encoder = "changed"
    again = store.get("fast-1080p30")
    assert again is not None
    assert again.video.encoder == "libx264"


# --------------------------------------------------------------------------- CRUD


def test_create_saves_a_user_preset_with_a_uuid(tmp_path: Path, store: PresetStore) -> None:
    mine = created(store, "  My   x265 ", encoder="libx265", preset="slow")
    assert mine.name == "My x265"
    assert mine.category == "Custom"
    assert not mine.built_in
    uuid.UUID(mine.id)
    assert PresetStore(tmp_path).user_presets() == [mine]


def test_save_updates_by_id(tmp_path: Path, store: PresetStore) -> None:
    mine = created(store, "Mine")
    changed = mine.model_copy(update={"description": "slower"})
    changed.video.preset = "slower"
    result = store.save(changed)
    assert isinstance(result, Preset)
    [reloaded] = PresetStore(tmp_path).user_presets()
    assert reloaded.description == "slower"
    assert reloaded.video.preset == "slower"


def test_save_never_stores_built_in_true(store: PresetStore) -> None:
    sneaky = Preset(id=str(uuid.uuid4()), name="Sneaky", built_in=True)
    result = store.save(sneaky)
    assert isinstance(result, Preset)
    assert not result.built_in


def test_builtins_cannot_be_changed_renamed_or_deleted(store: PresetStore) -> None:
    builtin = store.get("fast-1080p30")
    assert builtin is not None
    for result in (
        store.save(builtin),
        store.rename("fast-1080p30", "Faster"),
        store.delete("fast-1080p30"),
    ):
        assert isinstance(result, ValidationIssue)
        assert result.code == "preset.built_in"
        assert "Duplicate" in result.message


def test_name_conflict_is_an_issue_with_a_fix(store: PresetStore) -> None:
    created(store, "Mine")
    clash = store.create(template(), "MINE")
    assert isinstance(clash, ValidationIssue)
    assert clash.code == "preset.name_conflict"
    assert clash.path == "name"
    [fix] = clash.fixes
    assert fix.target == "template"
    assert fix.patch == [ReplaceOp(path="/name", value="MINE (2)")]
    builtin_clash = store.create(template(), "fast 1080p30")
    assert isinstance(builtin_clash, ValidationIssue)
    assert "built-in" in builtin_clash.message
    assert builtin_clash.fixes[0].label == "Use “fast 1080p30 (2)”"


def test_the_fix_of_a_name_conflict_resolves_it(store: PresetStore) -> None:
    created(store, "Mine")
    preset = Preset(id=str(uuid.uuid4()), name="Mine")
    clash = store.save(preset)
    assert isinstance(clash, ValidationIssue)
    fixed = Preset.model_validate(apply_patch(preset.model_dump(mode="json"), clash.fixes[0].patch))
    assert isinstance(store.save(fixed), Preset)


def test_empty_name_is_an_issue(store: PresetStore) -> None:
    result = store.create(template(), "   ")
    assert isinstance(result, ValidationIssue)
    assert result.code == "preset.name_empty"


def test_rename(tmp_path: Path, store: PresetStore) -> None:
    mine = created(store, "Mine")
    created(store, "Other")
    clash = store.rename(mine.id, "other")
    assert isinstance(clash, ValidationIssue)
    assert clash.code == "preset.name_conflict"
    renamed = store.rename(mine.id, "Mine (archive)")
    assert isinstance(renamed, Preset)
    assert renamed.name == "Mine (archive)"
    # Renaming to the same name with another case is fine (it is the preset's own name).
    assert isinstance(store.rename(mine.id, "MINE (ARCHIVE)"), Preset)
    missing = store.rename("nope", "x")
    assert isinstance(missing, ValidationIssue)
    assert missing.code == "preset.not_found"


def test_delete(tmp_path: Path, store: PresetStore) -> None:
    mine = created(store, "Mine")
    deleted = store.delete(mine.id)
    assert deleted == mine
    assert store.user_presets() == []
    assert PresetStore(tmp_path).user_presets() == []
    again = store.delete(mine.id)
    assert isinstance(again, ValidationIssue)
    assert again.code == "preset.not_found"


def test_duplicate_builtin_and_user_presets(store: PresetStore) -> None:
    copy = store.duplicate("h265-mkv-1080p")
    assert isinstance(copy, Preset)
    assert copy.name == "H.265 MKV 1080p (2)"
    assert copy.category == "Custom"
    assert not copy.built_in
    assert copy.id != "h265-mkv-1080p"
    original = store.get("h265-mkv-1080p")
    assert original is not None
    assert copy.video == original.video
    second = store.duplicate("h265-mkv-1080p")
    assert isinstance(second, Preset)
    assert second.name == "H.265 MKV 1080p (3)"
    mine = created(store, "Mine")
    mine_copy = store.duplicate(mine.id, "Mine, slower")
    assert isinstance(mine_copy, Preset)
    assert mine_copy.category == mine.category
    missing = store.duplicate("nope")
    assert isinstance(missing, ValidationIssue)
    assert missing.code == "preset.not_found"


def test_default_preset(tmp_path: Path, store: PresetStore) -> None:
    assert store.default().id == DEFAULT_BUILTIN_ID
    mine = created(store, "Mine")
    assert store.set_default(mine.id) == mine
    assert PresetStore(tmp_path).default() == mine
    builtin = store.set_default("h265-mkv-1080p")
    assert isinstance(builtin, Preset)
    assert builtin.id == "h265-mkv-1080p"
    assert store.set_default(mine.id) == mine
    store.delete(mine.id)  # deleting the default falls back to the built-in default
    assert store.default().id == DEFAULT_BUILTIN_ID
    assert store.default_id is None
    missing = store.set_default("nope")
    assert isinstance(missing, ValidationIssue)
    assert missing.code == "preset.not_found"
    reset = store.set_default(None)
    assert isinstance(reset, Preset)
    assert reset.id == DEFAULT_BUILTIN_ID


def test_dangling_default_in_the_file_falls_back(tmp_path: Path) -> None:
    (tmp_path / "presets.json").write_text(
        json.dumps({"schema_version": 1, "presets": [], "default_preset_id": "gone"}), "utf-8"
    )
    assert PresetStore(tmp_path).default().id == DEFAULT_BUILTIN_ID


def test_a_failed_write_changes_nothing(
    tmp_path: Path, store: PresetStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    mine = created(store, "Mine")

    def full(source: Path, target: Path) -> None:
        raise OSError(28, "No space left on device", str(target))

    bus = EventBus()
    events = bus.subscribe()
    store = PresetStore(tmp_path, bus)
    monkeypatch.setattr(settings_module, "_replace", full)
    result = store.rename(mine.id, "Renamed")
    assert isinstance(result, ValidationIssue)
    assert result.code == "presets.write_failed"
    assert store.user_presets() == [mine]
    [event] = drain(events)
    assert isinstance(event, AppWarningEvent)
    assert event.code == "presets.write_failed"


# --------------------------------------------------------------------------- export / import


def test_export_import_gives_the_same_result(tmp_path: Path) -> None:
    source = PresetStore(tmp_path / "a")
    first = created(source, "Anime x265", encoder="libx265", tune="animation")
    created(source, "Archive AV1", encoder="libsvtav1", preset="4")
    source.set_default(first.id)
    exported = source.export()
    assert exported.default_preset_id == first.id
    # Through the JSON text, as a file on disk would carry it.
    text = exported.model_dump_json()
    target = PresetStore(tmp_path / "b")
    result = target.import_(json.loads(text))
    assert result.ok
    assert result.renamed == []
    assert result.skipped == []
    assert target.user_presets() == source.user_presets()
    assert target.default() == source.default()
    assert PresetStore(tmp_path / "b").user_presets() == source.user_presets()
    assert target.export() == exported


@settings(
    max_examples=25,
    deadline=None,
    suppress_health_check=[
        HealthCheck.function_scoped_fixture,
        HealthCheck.too_slow,
        HealthCheck.filter_too_much,
    ],
)
@given(
    names=st.lists(
        st.text(alphabet="abcXYZ 0123", min_size=1, max_size=12).filter(lambda s: s.strip()),
        min_size=1,
        max_size=5,
        unique_by=lambda s: " ".join(s.split()).casefold(),
    ),
    quality=st.floats(min_value=0, max_value=51, allow_nan=False),
    default=st.integers(min_value=-1, max_value=4),
)
def test_export_import_round_trip_property(
    tmp_path_factory: pytest.TempPathFactory, names: list[str], quality: float, default: int
) -> None:
    source = PresetStore(tmp_path_factory.mktemp("a"))
    made = []
    for name in names:
        result = source.create(template(rate_control={"mode": "quality", "value": quality}), name)
        if isinstance(result, Preset):  # a name may clash with a built-in ("abc" is fine)
            made.append(result)
    if made and 0 <= default < len(made):
        source.set_default(made[default].id)
    target = PresetStore(tmp_path_factory.mktemp("b"))
    target.import_(PresetFile.model_validate_json(source.export().model_dump_json()))
    assert target.user_presets() == source.user_presets()
    assert target.default().id == source.default().id


def test_export_selected_ids_and_builtins(store: PresetStore) -> None:
    mine = created(store, "Mine")
    created(store, "Other")
    store.set_default(mine.id)
    file = store.export([mine.id, "h265-mkv-1080p", "unknown", mine.id])
    assert [p.id for p in file.presets] == [mine.id, "h265-mkv-1080p"]
    assert file.default_preset_id == mine.id
    assert store.export(["h265-mkv-1080p"]).default_preset_id is None


def test_importing_a_builtin_export_makes_a_user_copy(store: PresetStore) -> None:
    result = store.import_(store.export(["h265-mkv-1080p"]))
    [imported] = result.imported
    assert not imported.built_in
    assert imported.id != "h265-mkv-1080p"
    assert imported.name == "H.265 MKV 1080p (2)"
    assert result.renamed == [("H.265 MKV 1080p", "H.265 MKV 1080p (2)")]


@pytest.mark.parametrize("policy", ["rename", "replace", "skip"])
def test_import_name_conflicts(tmp_path: Path, policy: Any) -> None:
    store = PresetStore(tmp_path / "mine")
    mine = created(store, "Shared name", encoder="libx264")
    other = PresetStore(tmp_path / "other")
    theirs = created(other, "shared NAME", encoder="libx265")
    result = store.import_(other.export(), on_conflict=policy)
    users = store.user_presets()
    if policy == "rename":
        assert [p.name for p in users] == ["Shared name", "shared NAME (2)"]
        assert result.renamed == [("shared NAME", "shared NAME (2)")]
        assert users[1].id == theirs.id  # the id was free
    elif policy == "replace":
        [replaced] = users
        assert replaced.id == mine.id  # the user's id is kept (jobs and the default refer to it)
        assert replaced.name == "shared NAME"
        assert replaced.video.encoder == "libx265"
        assert result.replaced == ["Shared name"]
    else:
        assert users == [mine]
        assert result.skipped == ["shared NAME"]
        assert result.imported == []


@pytest.mark.parametrize("policy", ["rename", "replace", "skip"])
def test_import_id_conflicts(tmp_path: Path, policy: Any) -> None:
    store = PresetStore(tmp_path)
    mine = created(store, "Original")
    incoming = mine.model_copy(update={"name": "Edited elsewhere"}, deep=True)
    incoming.video.preset = "veryslow"
    result = store.import_(PresetFile(presets=[incoming]), on_conflict=policy)
    users = store.user_presets()
    if policy == "rename":
        assert [p.name for p in users] == ["Original", "Edited elsewhere"]
        assert users[1].id != mine.id
    elif policy == "replace":
        assert users == [incoming]
        assert result.replaced == ["Original"]
    else:
        assert users == [mine]
        assert result.skipped == ["Edited elsewhere"]


def test_replace_never_replaces_a_builtin(store: PresetStore) -> None:
    result = store.import_(
        PresetFile(presets=[Preset(id="x", name="Fast 1080p30")]), on_conflict="replace"
    )
    [imported] = result.imported
    assert imported.name == "Fast 1080p30 (2)"
    assert store.get("fast-1080p30") is not None
    assert result.replaced == []


def test_presets_in_one_import_do_not_clash_with_each_other(store: PresetStore) -> None:
    file = PresetFile(presets=[Preset(id="a", name="Twin"), Preset(id="b", name="twin")])
    result = store.import_(file)
    assert [p.name for p in result.imported] == ["Twin", "twin (2)"]


def test_import_keeps_the_target_default(store: PresetStore, tmp_path: Path) -> None:
    mine = created(store, "Mine")
    store.set_default(mine.id)
    other = PresetStore(tmp_path / "other")
    theirs = created(other, "Theirs")
    other.set_default(theirs.id)
    store.import_(other.export())
    assert store.default().id == mine.id


def test_import_of_damaged_and_newer_entries(store: PresetStore) -> None:
    raw = {
        "schema_version": 1,
        "presets": [
            {"id": "ok", "name": "Good one"},
            {"id": "bad", "name": "Broken", "video": {"bit_depth": 12}},
            {"id": "new", "name": "From the future", "schema_version": 99},
            "not even an object",
        ],
    }
    result = store.import_(raw)
    assert [p.name for p in result.imported] == ["Good one"]
    assert result.skipped == ["Broken", "From the future", "preset #4"]
    assert [i.code for i in result.issues] == [
        "preset.invalid",
        "preset.newer_version",
        "preset.invalid",
    ]
    assert result.ok  # warnings only


@pytest.mark.parametrize(
    ("raw", "code"),
    [
        ({"schema_version": 99, "presets": []}, "presets.import_newer"),
        ({"schema_version": 1, "presets": "nope"}, "presets.import_invalid"),
        ({"schema_version": "one"}, "presets.import_invalid"),
        ({"schema_version": 1, "presets": [], "default_preset_id": 5}, "presets.import_invalid"),
    ],
)
def test_import_of_a_bad_file(store: PresetStore, raw: dict[str, Any], code: str) -> None:
    result = store.import_(raw)
    assert [i.code for i in result.issues] == [code]
    assert not result.ok
    assert store.user_presets() == []


def test_import_with_a_failed_write_imports_nothing(
    store: PresetStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    def full(source: Path, target: Path) -> None:
        raise OSError(28, "No space left on device", str(target))

    monkeypatch.setattr(settings_module, "_replace", full)
    result = store.import_(PresetFile(presets=[Preset(id="a", name="A")]))
    assert result.imported == []
    assert result.skipped == ["A"]
    assert [i.code for i in result.issues] == ["presets.write_failed"]
    assert store.user_presets() == []


def test_import_migrates_an_old_export(tmp_path: Path) -> None:
    store = PresetStore(tmp_path, registry=registry_v2())
    raw = json.loads((FIXTURES / "presets-v1.json").read_text("utf-8"))
    result = store.import_(raw)
    assert result.ok
    assert [p.name for p in result.imported] == ["Anime 720p (old)", "Archive x265 (old)"]
    assert result.imported[0].video.rate_control == ConstantQuality(value=19)


# --------------------------------------------------------------------------- file handling


def test_old_schema_fixture_loads_after_migration(tmp_path: Path) -> None:
    (tmp_path / "presets.json").write_bytes((FIXTURES / "presets-v1.json").read_bytes())
    store = PresetStore(tmp_path, registry=registry_v2())
    presets = store.user_presets()
    assert store.problems == []
    assert [p.name for p in presets] == ["Anime 720p (old)", "Archive x265 (old)"]
    anime, archive = presets
    assert anime.schema_version == 2
    assert anime.video.rate_control == ConstantQuality(value=19)
    assert anime.video.tune == "animation"
    assert archive.video.rate_control == ConstantQuality(value=20)
    assert store.default() == archive
    # Unknown fields survive, in the file and in each preset, and are written back.
    store.rename(anime.id, "Anime 720p")
    data = json.loads((tmp_path / "presets.json").read_text("utf-8"))
    assert data["schema_version"] == 2
    assert data["written_by"] == "Reframe 0.0.1"
    assert data["default_preset_id"] == archive.id
    assert data["presets"][0]["name"] == "Anime 720p"
    assert data["presets"][0]["schema_version"] == 2
    assert data["presets"][0]["video"]["rate_control"] == {"mode": "quality", "value": 19.0}
    assert data["presets"][1]["user_note"] == "for the shelf"


def test_real_loader_runs_the_migration_registry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(migrations_module, "REGISTRY", registry_v2())
    (tmp_path / "presets.json").write_bytes((FIXTURES / "presets-v1.json").read_bytes())
    presets = PresetStore(tmp_path, builtins=[]).user_presets()
    assert presets[0].video.rate_control == ConstantQuality(value=19)


def test_corrupt_file_is_backed_up_and_replaced_with_defaults(tmp_path: Path) -> None:
    path = tmp_path / "presets.json"
    path.write_text('{"presets": [', encoding="utf-8")
    bus = EventBus()
    events = bus.subscribe()
    store = PresetStore(tmp_path, bus)
    assert store.user_presets() == []
    assert store.default().id == DEFAULT_BUILTIN_ID
    [backup] = tmp_path.glob("presets.corrupt-*.json")
    assert backup.read_text("utf-8") == '{"presets": ['
    assert json.loads(path.read_text("utf-8")) == {
        "schema_version": 1,
        "presets": [],
        "default_preset_id": None,
    }
    [event] = drain(events)
    assert isinstance(event, AppWarningEvent)
    assert event.code == "presets.corrupt"
    assert str(backup) in event.message
    assert store.problems == [event]
    assert isinstance(store.create(template(), "After"), Preset)


@pytest.mark.parametrize(
    "content",
    [
        "[]",
        '{"schema_version": 1, "presets": {"a": 1}}',
        '{"schema_version": 1, "presets": [], "default_preset_id": ["x"]}',
    ],
)
def test_damaged_file_structure_is_corrupt(tmp_path: Path, content: str) -> None:
    (tmp_path / "presets.json").write_text(content, encoding="utf-8")
    store = PresetStore(tmp_path)
    assert store.user_presets() == []
    assert [p.code for p in store.problems] == ["presets.corrupt"]


def test_damaged_presets_are_left_out_and_the_rest_kept(tmp_path: Path) -> None:
    good = Preset(id="11111111-1111-1111-1111-111111111111", name="Good")
    data = {
        "schema_version": 1,
        "presets": [
            good.model_dump(mode="json"),
            {"id": "x", "name": "Bad", "audio_defaults": {"codec_rules": []}},
            {**good.model_dump(mode="json"), "name": "Same id"},
        ],
        "default_preset_id": good.id,
    }
    (tmp_path / "presets.json").write_text(json.dumps(data), encoding="utf-8")
    store = PresetStore(tmp_path)
    assert store.user_presets() == [good]
    assert store.default() == good
    [problem] = store.problems
    assert problem.code == "presets.corrupt"
    assert problem.detail is not None
    assert "Bad" in problem.detail
    assert "used twice" in problem.detail
    assert len(list(tmp_path.glob("presets.corrupt-*.json"))) == 1
    rewritten = json.loads((tmp_path / "presets.json").read_text("utf-8"))
    assert [p["name"] for p in rewritten["presets"]] == ["Good"]


def test_presets_of_a_newer_reframe_are_kept_verbatim(tmp_path: Path) -> None:
    future = {"id": "f", "name": "Future", "schema_version": 5, "video": {"encoder": "h266"}}
    mine = Preset(id="m", name="Mine")
    data = {"schema_version": 1, "presets": [future, mine.model_dump(mode="json")]}
    (tmp_path / "presets.json").write_text(json.dumps(data), encoding="utf-8")
    store = PresetStore(tmp_path)
    assert store.user_presets() == [mine]
    assert store.problems == []
    assert store.find("Future") is None
    store.rename("m", "Mine, renamed")
    rewritten = json.loads((tmp_path / "presets.json").read_text("utf-8"))
    assert rewritten["presets"][0] == future
    assert rewritten["presets"][1]["name"] == "Mine, renamed"


def test_newer_file_is_kept_untouched(tmp_path: Path) -> None:
    path = tmp_path / "presets.json"
    path.write_text(json.dumps({"schema_version": 3, "presets": [{"id": "a"}]}), "utf-8")
    before = path.read_bytes()
    store = PresetStore(tmp_path)
    assert store.user_presets() == []
    assert store.read_only
    assert [p.code for p in store.problems] == ["presets.newer_version"]
    refused = store.create(template(), "Mine")
    assert isinstance(refused, ValidationIssue)
    assert refused.code == "presets.read_only"
    result = store.import_(PresetFile(presets=[Preset(id="b", name="B")]))
    assert [i.code for i in result.issues] == ["presets.read_only"]
    assert path.read_bytes() == before


def test_unreadable_file_is_not_touched(tmp_path: Path) -> None:
    (tmp_path / "presets.json").mkdir()
    store = PresetStore(tmp_path)
    assert store.user_presets() == []
    assert [p.code for p in store.problems] == ["presets.unreadable"]
    refused = store.set_default("fast-1080p30")
    assert isinstance(refused, ValidationIssue)
    assert refused.code == "presets.read_only"


def test_corrupt_file_that_cannot_be_backed_up_is_left_alone(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "presets.json").write_text("{", encoding="utf-8")

    def denied(source: Path, target: Path) -> None:
        raise PermissionError(13, "Permission denied", str(source))

    monkeypatch.setattr(settings_module, "_replace", denied)
    store = PresetStore(tmp_path)
    assert store.user_presets() == []
    assert store.read_only
    [problem] = store.problems
    assert problem.code == "presets.corrupt"
    assert (tmp_path / "presets.json").read_text("utf-8") == "{"


def test_load_rereads_the_file(tmp_path: Path) -> None:
    store = PresetStore(tmp_path)
    assert store.user_presets() == []
    created(PresetStore(tmp_path), "From elsewhere")
    assert store.user_presets() == []  # read once, at the first use
    assert [p.name for p in store.load()] == ["From elsewhere"]


def test_user_preset_named_like_a_newer_builtin_wins_find(tmp_path: Path) -> None:
    """A newer Reframe may add a built-in with the name of an existing user preset."""
    mine = Preset(id="u", name="Fast 1080p30")
    (tmp_path / "presets.json").write_text(
        json.dumps({"schema_version": 1, "presets": [mine.model_dump(mode="json")]}), "utf-8"
    )
    store = PresetStore(tmp_path)
    found = store.find("fast 1080p30")
    assert found is not None
    assert found.id == "u"
