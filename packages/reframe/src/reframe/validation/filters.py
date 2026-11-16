"""Filter rules: unknown filters, implementations, presets and tunes, implementations this build
cannot run, and HDR that the filter chain would mishandle. A filter is usable when
``CapabilitySnapshot.usable_filter`` is ``True``; while the build's filter list is unread,
every filter counts as usable.
"""

from __future__ import annotations

from collections.abc import Iterator

from reframe.definitions import Definitions, FilterDef, FilterImplementation
from reframe.models.capabilities import CapabilitySnapshot
from reframe.models.issues import Fix, ValidationIssue
from reframe.models.job import FilterConfig, FilterSettings
from reframe.models.media import HdrFormat, VideoStream
from reframe.validation.common import add, error, fix, remove, replace, warning
from reframe.validation.context import JobContext, TemplateContext
from reframe.validation.registry import job_rule, template_rule
from reframe.validation.video import ten_bit_patch

CODES = (
    "filter.unknown",
    "filter.implementation_unknown",
    "filter.implementation_unavailable",
    "filter.implementation_untested",
    "filter.unavailable",
    "filter.preset_unknown",
    "filter.tune_unknown",
    "filter.tune_required",
    "filter.custom_missing",
)
#: Colorspace presets that convert to an SDR transfer (BT.2020 uses ``bt2020-10``, SDR).
_SDR_PRESETS = frozenset({"bt709", "bt2020", "bt601-6-525", "bt601-6-625"})
#: Transfer characteristics of HDR video (ffprobe ``color_transfer``).
_HDR_TRANSFERS = frozenset({"smpte2084", "arib-std-b67"})


def _available(caps: CapabilitySnapshot, definitions: Definitions) -> dict[str, bool] | None:
    """``FilterImplementation.runs_with`` input: ``None`` (assume all) until the list is read."""
    if caps.filters is None:
        return None
    names = {
        name
        for definition in definitions.filters.values()
        for impl in definition.implementations
        for name in impl.filters
    }
    return {name: caps.usable_filter(name) is True for name in names}


def _plain_preset(impl: FilterImplementation) -> str | None:
    """The default preset, or the first one, that needs no custom parameters."""
    default = impl.preset(impl.default_preset)
    if default is not None and not default.custom:
        return default.id
    return next((p.id for p in impl.presets if not p.custom), None)


def _check_preset(
    filter_id: str,
    config: FilterConfig,
    impl: FilterImplementation,
    off: Fix,
) -> Iterator[ValidationIssue]:
    base = f"filters.{filter_id}"
    plain = _plain_preset(impl)
    use_plain = (
        fix(f"Use the {plain} preset", replace(f"{base}.preset", plain))
        if plain is not None
        else off
    )
    preset = impl.preset(config.preset)
    if preset is None:
        yield error(
            "filter.preset_unknown",
            f"{base}.preset",
            f"{impl.label} has no preset {config.preset!r}.",
            use_plain,
        )
        return
    tune_ids = [t.id for t in impl.tunes]
    if config.tune is not None and config.tune not in tune_ids:
        yield error(
            "filter.tune_unknown",
            f"{base}.tune",
            f"{impl.label} has no tune {config.tune!r}.",
            fix("No tune", replace(f"{base}.tune", None)),
        )
    elif preset.chain_for(config.tune) is None:
        tune = next((t for t in tune_ids if t in preset.tune_chains), None)
        fixes = [fix(f"Use the {tune} tune", replace(f"{base}.tune", tune))]
        yield error(
            "filter.tune_required",
            f"{base}.tune",
            f"The {preset.label} preset of {impl.label} needs a tune.",
            *(fixes if tune is not None else []),
        )
    if preset.custom and not (config.custom or "").strip():
        yield error(
            "filter.custom_missing",
            f"{base}.custom",
            f"The custom preset of {impl.label} needs its parameters.",
            use_plain,
        )


def _check_filter(
    filter_id: str,
    config: FilterConfig,
    definition: FilterDef,
    caps: CapabilitySnapshot,
    available: dict[str, bool] | None,
) -> Iterator[ValidationIssue]:
    base = f"filters.{filter_id}"
    remove_filter = fix(f"Turn off {definition.label}", remove(base))
    if config.implementation is not None:
        impl = definition.implementation(config.implementation)
        if impl is None:
            known = ", ".join(i.id for i in definition.implementations)
            yield error(
                "filter.implementation_unknown",
                f"{base}.implementation",
                f"{definition.label} has no implementation {config.implementation!r} ({known}).",
                fix(
                    "Use the default implementation",
                    replace(f"{base}.implementation", None),
                ),
            )
            return
        states = {name: caps.usable_filter(name) for name in impl.filters}
        failed = [name for name, usable in states.items() if usable is False]
        untested = [name for name, usable in states.items() if usable is None]
        fallback = definition.implementation_for(
            config.model_copy(update={"implementation": None}), available
        )
        use_default: list[Fix] = []
        if fallback is not None and fallback.id != impl.id:
            use_default.append(
                fix(f"Use {fallback.label}", replace(f"{base}.implementation", None))
            )
        if failed and available is not None:
            reasons = "; ".join(
                f"{name}: {caps.filter_failures.get(name, 'not in this FFmpeg build')}"
                for name in failed
            )
            yield error(
                "filter.implementation_unavailable",
                f"{base}.implementation",
                f"{definition.label} with {impl.label} cannot run ({reasons}).",
                *use_default,
                remove_filter,
            )
            return
        if untested and caps.filters is not None:
            yield warning(
                "filter.implementation_untested",
                f"{base}.implementation",
                f"{impl.label} has not been tested on this computer ({', '.join(untested)} "
                "needs a GPU test, which runs with the hardware tests): the encode fails if "
                "it cannot run.",
                *use_default,
            )
        yield from _check_preset(filter_id, config, impl, remove_filter)
        return
    impl = definition.implementation_for(config, available)
    if impl is not None:
        yield from _check_preset(filter_id, config, impl, remove_filter)
        return
    with_preset = [i for i in definition.implementations if i.preset(config.preset) is not None]
    if not with_preset:
        default = definition.implementations[0]
        yield from _check_preset(filter_id, config, default, remove_filter)
        return
    yield error(
        "filter.unavailable",
        base,
        f"{definition.label}: no implementation with the {config.preset!r} preset can run in "
        f"this FFmpeg build ({', '.join(i.label for i in with_preset)}).",
        remove_filter,
    )


def filter_issues(
    filters: FilterSettings,
    caps: CapabilitySnapshot,
    definitions: Definitions,
) -> Iterator[ValidationIssue]:
    available = _available(caps, definitions)
    for filter_id, config in filters.root.items():
        definition = definitions.filters.get(filter_id)  # type: ignore[call-overload]
        if definition is None:
            yield error(
                "filter.unknown",
                f"filters.{filter_id}",
                f"Unknown filter {filter_id!r}.",
                fix(f"Remove {filter_id}", remove(f"filters.{filter_id}")),
            )
            continue
        yield from _check_filter(filter_id, config, definition, caps, available)


@job_rule("filters", *CODES)
def filters(ctx: JobContext) -> Iterator[ValidationIssue]:
    if ctx.job.video.passthrough:
        return
    yield from filter_issues(ctx.job.filters, ctx.caps, ctx.definitions)


@template_rule("filters", *CODES)
def template_filters(ctx: TemplateContext) -> Iterator[ValidationIssue]:
    if ctx.template.video.passthrough:
        return
    yield from filter_issues(ctx.template.filters, ctx.caps, ctx.definitions)


def is_hdr(stream: VideoStream) -> bool:
    """PQ (HDR10, HDR10+, Dolby Vision with a PQ base layer) or HLG."""
    if stream.hdr is not None and stream.hdr.formats:
        return True
    return stream.color.transfer in _HDR_TRANSFERS


def _hdr_label(stream: VideoStream) -> str:
    """``HDR10``, ``HDR10, Dolby Vision``; ``HDR (PQ)`` when only the transfer says it."""
    if stream.hdr is not None and stream.hdr.formats:
        return ", ".join(f.label for f in stream.hdr.formats)
    return f"HDR ({_transfer(stream)})"


def _transfer(stream: VideoStream) -> str:
    hlg = stream.color.transfer == "arib-std-b67" or (
        stream.hdr is not None and HdrFormat.HLG in stream.hdr.formats
    )
    return "HLG" if hlg else "PQ"


@job_rule("filters", "filter.hdr_without_tonemap")
def hdr_to_sdr(ctx: JobContext) -> Iterator[ValidationIssue]:
    """Only a Colorspace conversion to an SDR transfer tags the output SDR. Without one the
    output stays HDR, which ``filter.hdr_8bit`` covers when the output is 8-bit."""
    stream = ctx.video_stream
    if ctx.job.video.passthrough or stream is None or not is_hdr(stream):
        return
    colorspace = ctx.job.filters.root.get("colorspace")
    if colorspace is None or colorspace.preset not in _SDR_PRESETS:
        return
    if "tonemap" in ctx.job.filters.root:
        return
    yield warning(
        "filter.hdr_without_tonemap",
        "filters.colorspace",
        f"Colorspace converts HDR ({_transfer(stream)}) to SDR without tone mapping: the "
        "picture will look washed out.",
        fix("Enable tone mapping", add("filters.tonemap", {"preset": "default"})),
    )


@job_rule("filters", "filter.hdr_8bit")
def hdr_to_8bit(ctx: JobContext) -> Iterator[ValidationIssue]:
    """An HDR source encoded to 8-bit with neither tone mapping nor a Colorspace conversion.

    The builder changes only the pixel format, so the output stays HDR, and 8 bits are too few
    for it: gradients band. Fixes: tone mapping (SDR output), or 10-bit (the builder keeps HDR)
    when the encoder can do it."""
    video = ctx.job.video
    stream = ctx.video_stream
    if video.passthrough or video.bit_depth == 10 or stream is None or not is_hdr(stream):
        return
    filters = ctx.job.filters.root
    if "tonemap" in filters or "colorspace" in filters:
        return  # tone mapped, or filter.hdr_without_tonemap
    fixes: list[Fix] = []
    tonemap = ctx.definitions.filters.get("tonemap")
    available = _available(ctx.caps, ctx.definitions)
    if tonemap is not None and tonemap.implementation_for(FilterConfig(), available) is not None:
        fixes.append(
            fix(
                "Turn on tone mapping (SDR output)",
                add("filters.tonemap", {"preset": "default"}),
            )
        )
    ten_bit = ten_bit_patch(video, ctx.caps, ctx.definitions)
    if ten_bit is not None:
        fixes.append(fix("Encode 10-bit (keep HDR)", *ten_bit))
    yield warning(
        "filter.hdr_8bit",
        "video.bit_depth",
        f"{_hdr_label(stream)} source encoded in 8 bits without tone mapping: the output "
        f"stays HDR (BT.2020 {_transfer(stream)}), but 8 bits are too few for HDR and "
        "gradients show banding. Tone map it to SDR, or encode 10-bit to keep HDR.",
        *fixes,
    )
