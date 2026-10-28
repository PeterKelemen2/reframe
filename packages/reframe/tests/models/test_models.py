"""Behaviour of the models: persistence (unknown fields, migrations), validators and unions."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from pydantic import TypeAdapter, ValidationError

from reframe.jsonpatch import apply_patch
from reframe.models import (
    DOCUMENT_MODELS,
    EVENT_ADAPTER,
    EVENT_TYPES,
    AppSettings,
    ArgTemplate,
    AudioCodecRule,
    AudioCodecRules,
    AudioDefaults,
    AudioOutputSettings,
    AudioOutputTrack,
    BitrateInfo,
    BitrateSource,
    CapabilitySnapshot,
    ChapterRange,
    Disposition,
    DocumentModel,
    EncodePlan,
    EncoderState,
    EncoderStatus,
    Event,
    ExternalSubtitle,
    FilterConfig,
    FilterSettings,
    FullRange,
    JobSettings,
    LanguageTag,
    Measurement,
    MediaSource,
    MigrationError,
    MigrationRegistry,
    MoveOp,
    OutputTrackRule,
    PlanStep,
    Preset,
    PresetFile,
    Range,
    Rational,
    ServerEndpoint,
    SourceRef,
    SubtitleDefaults,
    SubtitleOutputTrack,
    TimeRange,
    ToolPaths,
    TrackSelector,
    UnsupportedSchemaVersion,
    ValueRef,
    VideoStream,
    current_version,
    load_document,
    migrate,
    resolve_argv,
)
from reframe.models import migrations as migrations_mod
from reframe.tools.discovery import locate_tools


def _full_settings() -> dict[str, Any]:
    data = AppSettings().model_dump(mode="json")
    data["queue"]["future_option"] = {"nested": [1, 2, 3]}
    data["output"]["naming"]["future_flag"] = True
    data["brand_new_section"] = {"x": 1}
    return data


def _full_presets() -> dict[str, Any]:
    preset = Preset(id="p1", name="H.265 MKV 1080p", category="Matroska")
    preset.audio_defaults.codec_rules = [
        AudioCodecRule(
            languages=["hun"], source_channels="5.1_or_more", codec="ac3", max_bitrate=320
        ),
        AudioCodecRule(codec="libopus", mixdown="up_to_5.1", max_bitrate=256, if_fits="reencode"),
    ]
    preset.audio_rules = [
        OutputTrackRule(
            selector=TrackSelector(kind="audio", languages=["jpn"]),
            settings=AudioOutputSettings(encoder="libopus", bitrate=448),
        )
    ]
    data = PresetFile(presets=[preset], default_preset_id="p1").model_dump(mode="json")
    data["presets"][0]["video"]["future_video_field"] = "x265-next"
    data["presets"][0]["audio_defaults"]["codec_rules"][0]["extras"]["future"] = 1
    data["presets"][0]["audio_rules"][0]["settings"]["future"] = [None]
    data["presets"][0]["audio_rules"][0]["selector"]["future"] = {"a": "b"}
    data["future_top_level"] = "kept"
    return data


def _full_job() -> dict[str, Any]:
    job = JobSettings(
        source=SourceRef(path=Path("/media/Show.S01E01.mkv")),
        audio=[AudioOutputTrack(source_stream=1, encoder="ac3", bitrate=640)],
        subtitles=[
            SubtitleOutputTrack(source=4),
            SubtitleOutputTrack(source=ExternalSubtitle(path=Path("/media/Show.S01E01.hu.srt"))),
        ],
        filters=FilterSettings({"deinterlace": FilterConfig(preset="bob")}),
    )
    data = job.model_dump(mode="json")
    data["dimensions"]["crop"]["future"] = "kept"
    data["audio"][0]["metadata"]["future_flag"] = True
    data["subtitles"][1]["source"]["future_charset_guess"] = "cp1250"
    data["range"]["future"] = 1
    data["filters"]["deinterlace"]["future_param"] = 3
    data["video"]["rate_control"]["future"] = 0.5
    return data


@pytest.mark.parametrize(
    ("kind", "make"),
    [("settings", _full_settings), ("preset_file", _full_presets), ("job_settings", _full_job)],
)
def test_unknown_fields_are_kept(kind: str, make: Any) -> None:
    text = json.dumps(make())
    original = json.loads(text)
    loaded = load_document(kind, json.loads(text))
    assert json.loads(loaded.model_dump_json()) == original
    model = DOCUMENT_MODELS[kind]
    assert json.loads(model.model_validate_json(text).model_dump_json()) == original


def test_media_source_keeps_unknown_fields() -> None:
    data = MediaSource(
        ref=SourceRef(path=Path("/m.mkv")),
        video=[VideoStream(index=0, width=1920, height=1080)],
    ).model_dump(mode="json")
    data["video"][0]["future_hdr_field"] = {"x": 1}
    data["video"][0]["color"]["future"] = "bt2100"
    assert MediaSource.model_validate(data).model_dump(mode="json") == data


def test_every_persisted_model_has_schema_version() -> None:
    for kind, model in DOCUMENT_MODELS.items():
        assert issubclass(model, DocumentModel), kind
        assert model.model_fields["schema_version"].default == 1
        assert current_version(kind) == 1


def test_a_newer_servers_endpoint_file_is_read_and_its_token_never_printed() -> None:
    """A client reads ``server.json`` of a newer server (its ``api_version`` decides), and a log
    line with the endpoint does not show the local token."""
    data = {
        "pid": 4242,
        "instance": "9f1c2a",
        "port": 8765,
        "token": "local-token-secret",
        "version": "0.3.0",
        "api_version": 2,
        "started_at": "2026-10-28T06:00:00Z",
        "future": {"socket": "/run/reframe.sock"},
    }
    endpoint = ServerEndpoint.model_validate_json(json.dumps(data))
    assert endpoint.model_dump(mode="json") == data
    assert "local-token-secret" not in f"{endpoint!r} {endpoint}"


def test_an_endpoint_file_that_is_not_valid_does_not_show_its_token() -> None:
    """A client logs why it cannot use ``server.json``: the message must not hold the token."""
    data = {
        "pid": 4242,
        "instance": "9f1c2a",
        "port": 8765,
        "token": ["local-token-secret"],
        "version": "0.3.0",
        "api_version": 1,
        "started_at": "2026-10-28T06:00:00Z",
    }
    with pytest.raises(ValidationError) as caught:
        ServerEndpoint.model_validate_json(json.dumps(data))
    assert "token" in str(caught.value)
    assert "local-token-secret" not in str(caught.value)


def test_runtime_models_reject_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        EncodePlan.model_validate(
            {
                "job_type": "encode",
                "steps": [],
                "output_tmp": "a.part.mkv",
                "output_final": "a.mkv",
                "expected_duration": 1.0,
                "display": "ffmpeg",
                "typo": 1,
            }
        )


def test_migration_chain_keeps_unknown_fields() -> None:
    registry = MigrationRegistry()
    registry.add_kind("thing", 3)

    @registry.register("thing", from_version=1)
    def one_to_two(data: dict[str, Any]) -> dict[str, Any]:
        data["queue"] = {"parallel_jobs": data.pop("parallel", 1)}
        return data

    @registry.register("thing", from_version=2)
    def two_to_three(data: dict[str, Any]) -> dict[str, Any]:
        data["queue"]["when_done"] = "nothing"
        return data

    original = {"parallel": 2, "unknown": {"keep": True}}
    migrated = registry.migrate("thing", original)
    assert migrated == {
        "schema_version": 3,
        "queue": {"parallel_jobs": 2, "when_done": "nothing"},
        "unknown": {"keep": True},
    }
    assert original == {"parallel": 2, "unknown": {"keep": True}}
    assert registry.migrate("thing", {"schema_version": 2, "queue": {}})["schema_version"] == 3
    assert registry.migrate("thing", {"schema_version": 3}) == {"schema_version": 3}


def test_migration_errors() -> None:
    registry = MigrationRegistry()
    registry.add_kind("thing", 2)
    with pytest.raises(MigrationError, match="no migration from version 1"):
        registry.migrate("thing", {})
    with pytest.raises(UnsupportedSchemaVersion) as info:
        registry.migrate("thing", {"schema_version": 3})
    assert (info.value.kind, info.value.found, info.value.current) == ("thing", 3, 2)
    for bad in (0, -1, "1", True, 1.5, None):
        with pytest.raises(UnsupportedSchemaVersion):
            registry.migrate("thing", {"schema_version": bad})
    with pytest.raises(MigrationError, match="unknown document kind"):
        registry.migrate("nope", {})
    registry.register("thing", 1)(lambda d: d)
    with pytest.raises(MigrationError, match="exists"):
        registry.register("thing", 1)(lambda d: d)
    with pytest.raises(ValueError, match="start at 1"):
        registry.add_kind("other", 0)


def test_module_level_migrate() -> None:
    assert migrate("settings", {}) == {"schema_version": 1}
    settings = load_document("settings", {"queue": {"parallel_jobs": 2}})
    assert isinstance(settings, AppSettings)
    assert settings.queue.parallel_jobs == 2
    with pytest.raises(UnsupportedSchemaVersion):
        migrate("preset_file", {"schema_version": 99})


def test_register_migration_uses_the_global_registry(monkeypatch: pytest.MonkeyPatch) -> None:
    registry = MigrationRegistry()
    registry.add_kind("settings", 2)
    monkeypatch.setattr(migrations_mod, "REGISTRY", registry)

    @migrations_mod.register_migration("settings", from_version=1)
    def rename(data: dict[str, Any]) -> dict[str, Any]:
        data["renamed"] = True
        return data

    assert migrate("settings", {"schema_version": 1}) == {"schema_version": 2, "renamed": True}


def test_audio_defaults_end_with_a_catch_all() -> None:
    assert AudioDefaults().codec_rules[-1].is_catch_all
    rules = [
        AudioCodecRule(
            languages=["hun"],
            source_channels="5.1_or_more",
            codec="ac3",
            mixdown="5.1",
            max_bitrate=320,
        ),
        AudioCodecRule(
            languages=["eng"],
            source_channels="5.1_or_more",
            codec="ac3",
            mixdown="5.1",
            max_bitrate=384,
        ),
        AudioCodecRule(
            source_channels="stereo_or_less", codec="aac", mixdown="stereo", max_bitrate=160
        ),
        AudioCodecRule(codec="libopus", mixdown="up_to_5.1", max_bitrate=256, if_fits="reencode"),
    ]
    assert len(AudioDefaults(codec_rules=rules).codec_rules) == 4
    with pytest.raises(ValidationError, match="catch-all"):
        AudioDefaults(codec_rules=rules[:3])
    with pytest.raises(ValidationError, match="at least one"):
        AudioDefaults(codec_rules=[])
    with pytest.raises(ValidationError, match="catch-all"):
        AudioCodecRules(rules=[AudioCodecRule(languages=["eng"])])
    with pytest.raises(ValidationError, match="catch-all"):
        AudioDefaults.model_validate({"codec_rules": [{"source_channels": "mono"}]})


def test_bitrate_value_matches_its_source() -> None:
    assert BitrateInfo().source is BitrateSource.UNKNOWN
    assert BitrateInfo(value=192000, source=BitrateSource.STREAM).value == 192000
    with pytest.raises(ValidationError):
        BitrateInfo(value=192000)
    with pytest.raises(ValidationError):
        BitrateInfo(source=BitrateSource.STATS_TAG)


@pytest.mark.parametrize("tag", ["en", "hun", "zh-Hans", "es-419", "de-CH-1996"])
def test_language_tags(tag: str) -> None:
    assert TypeAdapter(LanguageTag).validate_python(tag) == tag


@pytest.mark.parametrize("tag", ["e", "en_US", "english language", "1en", "en-", "-en"])
def test_bad_language_tags(tag: str) -> None:
    with pytest.raises(ValidationError):
        TypeAdapter(LanguageTag).validate_python(tag)


def test_subtitle_defaults_differ_from_audio() -> None:
    selection = SubtitleDefaults().selection
    assert selection.no_match == "none"
    assert selection.default_track == "none"
    assert AudioDefaults().selection.no_match == "default_flagged"
    assert AudioDefaults().selection.default_track == "first_output"


def test_range_union() -> None:
    adapter: TypeAdapter[Range] = TypeAdapter(Range)
    assert adapter.validate_python({"kind": "chapters", "start": 2, "end": 5}) == ChapterRange(
        start=2, end=5
    )
    assert adapter.validate_python({"kind": "time", "start": 10.5}) == TimeRange(start=10.5)
    assert JobSettings(source=SourceRef(path=Path("a.mkv"))).range == FullRange()
    with pytest.raises(ValidationError):
        adapter.validate_python({"kind": "minutes"})


def test_filter_settings_keep_their_order() -> None:
    filters = FilterSettings.model_validate(
        {
            "sharpen": {"preset": "light"},
            "deinterlace": {},
            "denoise": {"preset": "medium", "tune": "film"},
        }
    )
    assert list(filters.root) == ["sharpen", "deinterlace", "denoise"]
    assert list(json.loads(filters.model_dump_json())) == ["sharpen", "deinterlace", "denoise"]


def test_event_types_match_the_union() -> None:
    members = TypeAdapter(Event).json_schema()["discriminator"]["mapping"]
    assert set(members) == set(EVENT_TYPES)
    assert len(EVENT_TYPES) == 12
    assert EVENT_TYPES[-1] == "resync"
    assert EVENT_TYPES[:7] == (
        "capabilities.changed",
        "task.progress",
        "task.done",
        "job.state",
        "job.progress",
        "job.log",
        "queue.changed",
    )
    event = EVENT_ADAPTER.validate_python({"type": "job.state", "job_id": "1", "state": "running"})
    assert event.type == "job.state"


def test_move_op_alias() -> None:
    op = MoveOp(from_="/a", path="/b")
    assert op.model_dump() == {"op": "move", "from": "/a", "path": "/b"}
    assert MoveOp.model_validate({"from": "/a", "path": "/b"}) == op


def test_plan_placeholders_resolve() -> None:
    analyse = PlanStep(
        kind="analyse",
        tool="ffmpeg",
        argv=["-i", "in.mkv", "-af", "loudnorm=print_format=json", "-f", "null", "-"],
        measures=[Measurement(id="a0", parser="loudnorm")],
    )
    encode = PlanStep(
        kind="encode",
        tool="ffmpeg",
        argv=[
            "-filter:a:0",
            ArgTemplate(
                parts=["loudnorm=I=-23:measured_I=", ValueRef(ref="a0.input_i"), ":linear=true"]
            ),
            "out.part.mkv",
        ],
    )
    assert resolve_argv(analyse.argv, {}) == analyse.argv
    assert resolve_argv(encode.argv, {"a0.input_i": "-27.61"}) == [
        "-filter:a:0",
        "loudnorm=I=-23:measured_I=-27.61:linear=true",
        "out.part.mkv",
    ]
    with pytest.raises(KeyError):
        resolve_argv(encode.argv, {})
    with pytest.raises(ValidationError):
        ValueRef(ref="no-dot")


def test_use_bundled_fix_applies_to_app_settings(tmp_path: Path) -> None:
    settings = AppSettings(tools=ToolPaths(ffmpeg=tmp_path / "missing" / "ffmpeg"))
    located = locate_tools(settings.tools, environ={}, bundled_roots=[], search_path=str(tmp_path))
    (fix,) = located["ffmpeg"].fixes
    assert fix.target == "settings"
    patched = apply_patch(settings.model_dump(mode="json"), fix.patch)
    assert AppSettings.model_validate(patched).tools.ffmpeg is None


@pytest.mark.needs_ffmpeg
def test_disposition_has_every_ffprobe_flag(fixture_media: Any) -> None:
    from reframe_testing import media

    info = media.probe(fixture_media("multitrack"))
    for stream in info["streams"]:
        # FFmpeg 8.1 and 9.0 print the same 19 flags; older builds may print fewer.
        assert set(stream["disposition"]) <= set(Disposition.model_fields)
    assert len(Disposition.model_fields) == 19


def test_rational() -> None:
    assert float(Rational(num=24000, den=1001)) == pytest.approx(23.976, abs=1e-3)
    assert str(Rational(num=32, den=27)) == "32/27"
    assert Rational.square() == Rational(num=1, den=1)
    with pytest.raises(ValidationError):
        Rational(num=0, den=0)


def test_capability_snapshot_lookups() -> None:
    snapshot = CapabilitySnapshot(
        encoders={"libx265": EncoderStatus(id="libx265", state=EncoderState.AVAILABLE)},
        filters=["zscale"],
    )
    assert snapshot.status("libx265").state is EncoderState.AVAILABLE
    assert snapshot.status("hevc_nvenc") == EncoderStatus(id="hevc_nvenc")
    assert snapshot.has_filter("zscale") is True
    assert snapshot.has_filter("libplacebo") is False
    assert CapabilitySnapshot().has_filter("zscale") is None
