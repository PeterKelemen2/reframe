"""The preset store: CRUD, default, export and import, migrations, and damaged or newer files."""

from __future__ import annotations

import json
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from reframe import settings as settings_module
from reframe.events import EventBus
from reframe.jsonpatch import apply_patch
from reframe.models import (
    AppWarningEvent,
    ConstantQuality,
    JobTemplate,
    Preset,
    PresetFile,
    ReplaceOp,
    ValidationIssue,
)
from reframe.models import migrations as migrations_module
from reframe.models.migrations import MigrationRegistry
from reframe.presets import DEFAULT_BUILTIN_ID, PresetStore, builtin_presets, normalise_name
from reframe_testing.helpers import drain, nested

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def registry_v2() -> MigrationRegistry:
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


@pytest.fixture
def use_registry(monkeypatch: pytest.MonkeyPatch) -> Callable[[MigrationRegistry], None]:
    """Installs a fake migration registry for the rest of the test."""
    # The built-ins are cached at their first load: loaded under a fake registry, they would
    # keep its schema versions for the whole test process.
    builtin_presets()

    def install(registry: MigrationRegistry) -> None:
        monkeypatch.setattr(migrations_module, "REGISTRY", registry)

    return install


def created(store: PresetStore, name: str, **video: Any) -> Preset:
    result = store.create(template(**video), name)
    assert isinstance(result, Preset), result
    return result


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


def test_delete(tmp_path: Path, store: PresetStore) -> None:
    mine = created(store, "Mine")
    deleted = store.delete(mine.id)
    assert deleted == mine
    assert store.user_presets() == []
    assert PresetStore(tmp_path).user_presets() == []
    again = store.delete(mine.id)
    assert isinstance(again, ValidationIssue)
    assert again.code == "preset.not_found"


def test_default_preset(tmp_path: Path, store: PresetStore) -> None:
    assert DEFAULT_BUILTIN_ID == "h265-mkv-1080p"
    assert store.default().id == DEFAULT_BUILTIN_ID
    mine = created(store, "Mine")
    assert store.set_default(mine.id) == mine
    assert PresetStore(tmp_path).default() == mine
    builtin = store.set_default("fast-1080p30")
    assert isinstance(builtin, Preset)
    assert builtin.id == "fast-1080p30"
    assert store.set_default(mine.id) == mine
    store.delete(mine.id)  # deleting the default falls back to the built-in default
    assert store.default().id == DEFAULT_BUILTIN_ID
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
    result = store.save(mine.model_copy(update={"name": "Renamed"}))
    assert isinstance(result, ValidationIssue)
    assert result.code == "presets.write_failed"
    assert store.user_presets() == [mine]
    [event] = drain(events)
    assert isinstance(event, AppWarningEvent)
    assert event.code == "presets.write_failed"


def test_export_import_gives_the_same_result(tmp_path: Path) -> None:
    source = PresetStore(tmp_path / "a")
    first = created(source, "Anime x265", encoder="libx265", tune="animation")
    created(source, "Archive AV1", encoder="libsvtav1", preset="4")
    source.set_default(first.id)
    exported = source.export().file
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
    assert target.export().file == exported


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
    target.import_(PresetFile.model_validate_json(source.export().file.model_dump_json()))
    assert target.user_presets() == source.user_presets()
    assert target.default().id == source.default().id


def test_export_selected_ids_and_builtins(store: PresetStore) -> None:
    mine = created(store, "Mine")
    created(store, "Other")
    store.set_default(mine.id)
    file = store.export([mine.id, "h265-mkv-1080p", "unknown", mine.id]).file
    assert [p.id for p in file.presets] == [mine.id, "h265-mkv-1080p"]
    assert file.default_preset_id == mine.id
    assert store.export(["h265-mkv-1080p"]).file.default_preset_id is None


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


def test_import_migrates_an_old_export(
    tmp_path: Path, use_registry: Callable[[MigrationRegistry], None]
) -> None:
    use_registry(registry_v2())
    store = PresetStore(tmp_path)
    raw = json.loads((FIXTURES / "presets-v1.json").read_text("utf-8"))
    result = store.import_(raw)
    assert result.ok
    assert [p.name for p in result.imported] == ["Anime 720p (old)", "Archive x265 (old)"]
    assert result.imported[0].video.rate_control == ConstantQuality(value=19)


def test_old_schema_fixture_loads_after_migration(
    tmp_path: Path, use_registry: Callable[[MigrationRegistry], None]
) -> None:
    use_registry(registry_v2())
    (tmp_path / "presets.json").write_bytes((FIXTURES / "presets-v1.json").read_bytes())
    store = PresetStore(tmp_path)
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
    store.save(anime.model_copy(update={"name": "Anime 720p"}))
    data = json.loads((tmp_path / "presets.json").read_text("utf-8"))
    assert data["schema_version"] == 2
    assert data["written_by"] == "Reframe 0.0.1"
    assert data["default_preset_id"] == archive.id
    assert data["presets"][0]["name"] == "Anime 720p"
    assert data["presets"][0]["schema_version"] == 2
    assert data["presets"][0]["video"]["rate_control"] == {"mode": "quality", "value": 19.0}
    assert data["presets"][1]["user_note"] == "for the shelf"


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
    store.save(mine.model_copy(update={"name": "Mine, renamed"}))
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


#: A preset that a newer Reframe wrote (its schema version is above ours).
FUTURE: dict[str, Any] = {
    "id": "f",
    "name": "Future",
    "schema_version": 5,
    "video": {"encoder": "h266"},
    "new_in_v5": {"keep": True},
}


def with_future(folder: Path, *, default: str | None = None) -> Preset:
    """``presets.json`` with :data:`FUTURE` and one current preset (returned)."""
    mine = Preset(id="m", name="Mine")
    data = {
        "schema_version": 1,
        "presets": [FUTURE, mine.model_dump(mode="json")],
        "default_preset_id": default,
    }
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "presets.json").write_text(json.dumps(data), encoding="utf-8")
    return mine


def registry_v5() -> MigrationRegistry:
    """A newer Reframe: ``preset`` at version 5 (empty migrations)."""
    registry = MigrationRegistry()
    registry.add_kind("preset_file", 1)
    registry.add_kind("preset", 5)
    for version in range(1, 5):
        registry.register("preset", from_version=version)(lambda data: data)
    return registry


def test_save_refuses_a_preset_of_a_newer_reframe(tmp_path: Path) -> None:
    """A preset of a newer Reframe would be hidden after a restart, so ``save`` refuses it."""
    store = PresetStore(tmp_path)
    mine = created(store, "Mine")
    before = (tmp_path / "presets.json").read_bytes()
    for preset in (
        mine.model_copy(update={"schema_version": 5, "description": "changed"}),
        Preset(id="n", name="New", schema_version=5),
    ):
        refused = store.save(preset)
        assert isinstance(refused, ValidationIssue)
        assert refused.code == "preset.newer_version"
        assert "newer Reframe" in refused.message
    assert (tmp_path / "presets.json").read_bytes() == before
    assert store.user_presets() == [mine]
    assert PresetStore(tmp_path).user_presets() == [mine]


def test_create_from_a_template_makes_a_preset_of_the_current_version(tmp_path: Path) -> None:
    """The template's ``schema_version`` (a ``job_template``) is not the preset's."""
    store = PresetStore(tmp_path)
    made = store.create(JobTemplate.model_validate({"schema_version": 5}), "From a template")
    assert isinstance(made, Preset)
    assert made.schema_version == 1
    assert [p.name for p in PresetStore(tmp_path).user_presets()] == ["From a template"]


def test_import_of_a_preset_file_refuses_newer_presets(tmp_path: Path) -> None:
    store = PresetStore(tmp_path)
    file = PresetFile(
        presets=[Preset(id="a", name="A", schema_version=5), Preset(id="b", name="B")]
    )
    result = store.import_(file)
    assert [p.name for p in result.imported] == ["B"]
    assert result.skipped == ["A"]
    [issue] = result.issues
    assert issue.code == "preset.newer_version"
    assert "newer Reframe" in issue.message
    assert [p.name for p in store.user_presets()] == ["B"]
    assert [p.name for p in PresetStore(tmp_path).user_presets()] == ["B"]


def test_save_and_import_never_take_the_id_of_a_newer_preset(tmp_path: Path) -> None:
    with_future(tmp_path)
    store = PresetStore(tmp_path)
    refused = store.save(Preset(id="f", name="Taken id"))
    assert isinstance(refused, ValidationIssue)
    assert refused.code == "preset.newer_version"
    result = store.import_(PresetFile(presets=[Preset(id="f", name="Imported")]))
    [imported] = result.imported
    assert imported.id != "f"
    saved = json.loads((tmp_path / "presets.json").read_text("utf-8"))
    assert saved["presets"][0] == FUTURE
    assert [p["id"] for p in saved["presets"]] == ["f", "m", imported.id]


def test_the_name_of_a_newer_preset_is_taken(
    tmp_path: Path, use_registry: Callable[[MigrationRegistry], None]
) -> None:
    """Otherwise the newer Reframe would read two presets with one name."""
    mine = with_future(tmp_path)
    store = PresetStore(tmp_path)
    clash = store.create(template(), "future")
    assert isinstance(clash, ValidationIssue)
    assert clash.code == "preset.name_conflict"
    assert clash.message == "A preset named “Future” already exists."
    assert store.unique_name("Future") == "Future (2)"
    refused = store.save(mine.model_copy(update={"name": "FUTURE"}))
    assert isinstance(refused, ValidationIssue)
    assert refused.code == "preset.name_conflict"
    renamed = store.import_(PresetFile(presets=[Preset(id="r", name="Future")]), "rename")
    assert [p.name for p in renamed.imported] == ["Future (2)"]
    replacing = store.import_(PresetFile(presets=[Preset(id="p", name="Future")]), "replace")
    assert [p.name for p in replacing.imported] == ["Future (3)"]
    assert replacing.replaced == []
    skipped = store.import_(PresetFile(presets=[Preset(id="s", name="Future")]), "skip")
    assert skipped.skipped == ["Future"]
    use_registry(registry_v5())
    newer = PresetStore(tmp_path)
    names = [normalise_name(p.name) for p in newer.user_presets()]
    assert sorted(names) == ["future", "future (2)", "future (3)", "mine"]
    saved = json.loads((tmp_path / "presets.json").read_text("utf-8"))
    assert saved["presets"][0] == FUTURE


def test_export_all_keeps_newer_presets_unchanged(
    tmp_path: Path, use_registry: Callable[[MigrationRegistry], None]
) -> None:
    """Newer presets go into the export file unchanged, with a warning that only a newer
    Reframe can import them."""
    mine = with_future(tmp_path / "a", default="f")
    store = PresetStore(tmp_path / "a")
    exported = store.export()
    assert exported.file.presets == [mine]
    assert exported.file.default_preset_id is None  # the default is not in ``file``
    assert exported.newer == [FUTURE]
    [issue] = exported.issues
    assert issue.code == "preset.newer_version"
    assert "Future" in issue.message
    assert issue.severity == "warning"
    document = json.loads(json.dumps(exported.document()))
    assert document["presets"] == [mine.model_dump(mode="json"), FUTURE]
    assert document["default_preset_id"] == "f"
    # Chosen ids may name a newer preset too.
    only = store.export(["f"])
    assert only.file.presets == []
    assert only.newer == [FUTURE]
    # This Reframe imports what it can read and says what it could not.
    result = PresetStore(tmp_path / "b").import_(exported)
    assert [p.name for p in result.imported] == ["Mine"]
    assert result.skipped == ["Future"]
    assert [i.code for i in result.issues] == ["preset.newer_version"]
    # The newer Reframe imports both, the newer one unchanged.
    use_registry(registry_v5())
    newer = PresetStore(tmp_path / "c")
    result = newer.import_(document)
    assert sorted(p.name for p in result.imported) == ["Future", "Mine"]
    future = newer.find("Future")
    assert future is not None
    assert future.model_dump(mode="json")["new_in_v5"] == {"keep": True}
    assert newer.default().id == "f"


def test_a_deeply_nested_preset_is_damaged_and_the_others_are_kept(tmp_path: Path) -> None:
    good = Preset(id="g", name="Good")
    deep = '{"id": "d", "name": "Deep", "x": ' + "[" * 600 + "]" * 600 + "}"
    text = f'{{"schema_version": 1, "presets": [{good.model_dump_json()}, {deep}]}}'
    (tmp_path / "presets.json").write_text(text, encoding="utf-8")
    store = PresetStore(tmp_path)
    assert store.user_presets() == [good]
    [problem] = store.problems
    assert problem.code == "presets.corrupt"
    assert problem.detail is not None
    assert "Deep" in problem.detail
    assert "nested" in problem.detail
    [backup] = tmp_path.glob("presets.corrupt-*.json")
    assert backup.read_text("utf-8") == text
    rewritten = json.loads((tmp_path / "presets.json").read_text("utf-8"))
    assert [p["name"] for p in rewritten["presets"]] == ["Good"]


@pytest.mark.parametrize(
    "text",
    [
        '{"schema_version": 1, "presets": [], "x": ' + "[" * 600 + "]" * 600 + "}",
        '{"presets": ' + "[" * 100_000 + "]" * 100_000 + "}",
    ],
    ids=["deep-header", "too-deep-to-parse"],
)
def test_a_deeply_nested_presets_file_is_corrupt(tmp_path: Path, text: str) -> None:
    (tmp_path / "presets.json").write_text(text, encoding="utf-8")
    store = PresetStore(tmp_path)
    assert store.user_presets() == []
    [problem] = store.problems
    assert problem.code == "presets.corrupt"
    assert problem.detail is not None
    assert "nested" in problem.detail
    assert len(list(tmp_path.glob("presets.corrupt-*.json"))) == 1


def test_import_of_a_deeply_nested_preset_skips_it(store: PresetStore) -> None:
    raw = {
        "schema_version": 1,
        "presets": [{"id": "d", "name": "Deep", "x": nested(600)}, {"id": "ok", "name": "Fine"}],
    }
    result = store.import_(raw)
    assert [p.name for p in result.imported] == ["Fine"]
    assert result.skipped == ["Deep"]
    assert [i.code for i in result.issues] == ["preset.invalid"]
    deep = Preset.model_validate({"id": "d2", "name": "Deep 2", "x": nested(400)})
    result = store.import_(PresetFile(presets=[deep]))
    assert result.imported == []
    assert [i.code for i in result.issues] == ["presets.import_invalid"]


@pytest.mark.parametrize("depth", [100, 400])
def test_saving_a_too_deep_preset_is_an_issue(store: PresetStore, depth: int) -> None:
    deep = Preset.model_validate({"id": "d", "name": "Deep", "x": nested(depth)})
    refused = store.save(deep)
    assert isinstance(refused, ValidationIssue)
    assert refused.code == "preset.invalid"
    assert "nested" in refused.message
    assert store.user_presets() == []


def test_a_linked_presets_file_stays_a_link(tmp_path: Path) -> None:
    real = tmp_path / "dotfiles" / "presets.json"
    real.parent.mkdir()
    real.write_text('{"schema_version": 1, "presets": []}', encoding="utf-8")
    config = tmp_path / "config"
    config.mkdir()
    link = config / "presets.json"
    try:
        link.symlink_to(real)
    except (OSError, NotImplementedError) as exc:  # Windows without the privilege
        pytest.skip(f"cannot make a symbolic link: {exc}")
    created(PresetStore(config), "Mine")
    assert link.is_symlink()
    assert [p["name"] for p in json.loads(real.read_text("utf-8"))["presets"]] == ["Mine"]
    assert [p.name for p in PresetStore(config).user_presets()] == ["Mine"]
