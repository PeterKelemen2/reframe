"""Validation (C-8): every problem of a job or a preset as a :class:`ValidationIssue`.

- :func:`validate` checks a job against its source, the encoder capabilities, the tools, the
  file system (through a :class:`FileSystemView`) and the settings. It never raises for a bad
  job: everything is an issue. ``error`` blocks *Add to queue*; ``warning`` and ``info`` do
  not (03 §Validation and error display).
- :func:`validate_template` checks what a preset alone can be checked for: encoder
  availability (with the closest-match fix, quality converted), container ↔ codecs of the
  video encoder and the audio codec rules, filters, the naming templates (M2 demo item 4), and
  C-12's defaults lint (``reframe.batch.lint_defaults``). Its fixes target ``"template"``.
- Each fix is a JSON patch (``Fix.patch``) on the document ``Fix.target`` names (``job``,
  ``template``, or ``settings``); applied with :func:`reframe.jsonpatch.apply_patch`, it
  removes its issue.

The rules are small functions registered by area (:mod:`reframe.validation.registry`):
``tools``, ``source``, ``encoder``, ``container``, ``dimensions``, ``filters``, ``audio``,
``subtitles``, ``metadata``, ``range``, ``output``, ``naming``. Each rule declares the codes it
can give; ``CASES`` in ``tests/validation/test_rules.py`` has a positive and a negative case
for each.

A rule that fails with an exception (a bug) does not stop the others: it gives a
``validation.rule_failed`` error, so a job is never queued unchecked.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable

from reframe.batch.lint import lint_defaults
from reframe.definitions import Definitions, load_definitions
from reframe.models.capabilities import CapabilitySnapshot
from reframe.models.issues import ValidationIssue
from reframe.models.job import JobSettings
from reframe.models.media import MediaSource
from reframe.models.naming import NamingOptions
from reframe.models.preset import Preset
from reframe.models.settings import AppSettings
from reframe.models.template import JobTemplate
from reframe.models.tools import ToolSet

# Importing a rule module registers its rules (the order of the areas is fixed by AREAS).
from reframe.validation import audio as _audio  # noqa: F401
from reframe.validation import container as _container  # noqa: F401
from reframe.validation import dimensions as _dimensions  # noqa: F401
from reframe.validation import encoder as _encoder  # noqa: F401
from reframe.validation import filters as _filters  # noqa: F401
from reframe.validation import inplace as _inplace  # noqa: F401
from reframe.validation import levels as _levels  # noqa: F401
from reframe.validation import metadata as _metadata  # noqa: F401
from reframe.validation import naming as _naming  # noqa: F401
from reframe.validation import output as _output  # noqa: F401
from reframe.validation import range as _range  # noqa: F401
from reframe.validation import source as _source  # noqa: F401
from reframe.validation import subtitles as _subtitles  # noqa: F401
from reframe.validation import tools as _tools  # noqa: F401
from reframe.validation.common import error
from reframe.validation.context import JobContext, TemplateContext
from reframe.validation.fs import FileSystemView, LocalFileSystem
from reframe.validation.output import estimate_output_bytes, next_free_path
from reframe.validation.registry import JOB_RULES, TEMPLATE_RULES, Rule, ordered
from reframe.validation.video import switch_video_encoder

__all__ = [
    "JOB_RULES",
    "TEMPLATE_RULES",
    "FileSystemView",
    "JobContext",
    "LocalFileSystem",
    "Rule",
    "TemplateContext",
    "estimate_output_bytes",
    "next_free_path",
    "switch_video_encoder",
    "validate",
    "validate_template",
]

log = logging.getLogger(__name__)


def _run[C](rules: Iterable[Rule[C]], context: C) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    for rule in ordered(rules):
        try:
            issues.extend(rule.check(context))
        except Exception as exc:  # a bug in a rule must not hide the other issues
            log.exception("validation rule %s failed", rule.name)
            issues.append(
                error(
                    "validation.rule_failed",
                    "",
                    f"Validation could not check {rule.area} ({rule.name}: "
                    f"{type(exc).__name__}: {exc}). Please report this.",
                )
            )
    return issues


def validate(
    job: JobSettings,
    source: MediaSource,
    caps: CapabilitySnapshot,
    tools: ToolSet,
    fs: FileSystemView,
    *,
    settings: AppSettings | None = None,
    definitions: Definitions | None = None,
    naming: NamingOptions | None = None,
    rules: Iterable[Rule[JobContext]] | None = None,
) -> list[ValidationIssue]:
    """Every issue of ``job`` (see the module doc).

    :param settings: the collision policy (``output.collision``) and the naming options;
        ``None`` = ``AppSettings()`` defaults.
    :param naming: the effective naming options when they differ from Settings → Output (a
        preset's ``JobTemplate.naming``); ``None`` = ``settings.output.naming``.
    :param rules: only these rules (tests); ``None`` = all of :data:`JOB_RULES`.
    """
    settings = settings if settings is not None else AppSettings()
    context = JobContext(
        job=job,
        source=source,
        caps=caps,
        tools=tools,
        fs=fs,
        settings=settings,
        definitions=definitions if definitions is not None else load_definitions(),
        naming=naming if naming is not None else settings.output.naming,
    )
    return _run(JOB_RULES if rules is None else rules, context)


def validate_template(
    template: JobTemplate,
    caps: CapabilitySnapshot,
    *,
    subject: str | None = None,
    definitions: Definitions | None = None,
    rules: Iterable[Rule[TemplateContext]] | None = None,
) -> list[ValidationIssue]:
    """The issues a preset or batch template has without a source (fixes target
    ``"template"``).

    :param subject: names the template in messages (``Preset "H.265 NVENC 1080p"``); for a
        :class:`~reframe.models.Preset` the default is built from its name.
    """
    if subject is None and isinstance(template, Preset):
        subject = f'Preset "{template.name}"'
    defs = definitions if definitions is not None else load_definitions()
    context = TemplateContext(template=template, caps=caps, definitions=defs, subject=subject)
    issues = _run(TEMPLATE_RULES if rules is None else rules, context)
    if rules is None:
        # C-12's defaults lint (shadowed and unreachable codec rules, bitrates out of range).
        issues += lint_defaults(
            template.audio_defaults, container=template.output.container, definitions=defs
        )
    return issues
