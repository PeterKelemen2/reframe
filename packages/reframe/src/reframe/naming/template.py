"""Naming templates: parse, check and render (03 §Output naming → Template syntax; C-16).

=================  =====================================================================
``{variable}``     Insert the value
``{variable:spec}`` Numbers: ``{season:02}``. Dates: ``{date:%Y-%m-%d}``. Text: ``:upper``,
                   ``:lower``, ``:title`` (or a Python string format such as ``:.20``)
``<…>``            Optional group: dropped when a variable directly inside it is empty.
                   Groups nest; an inner group that is dropped does not drop the outer one
``/``              A subfolder under the output folder
``{{`` ``}}``      Literal braces
=================  =====================================================================

A bad template is never an exception: :func:`parse_template` collects syntax errors and
:func:`check_template` turns them, unknown variables (with a "did you mean" fix) and bad
format specs into :class:`~reframe.models.issues.ValidationIssue`.
"""

from __future__ import annotations

import difflib
import re
import unicodedata
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from datetime import date, datetime
from functools import lru_cache

from reframe.jsonpatch import format_pointer
from reframe.models.issues import AddOp, Fix, FixTarget, Severity, ValidationIssue
from reframe.naming.clean import title_case
from reframe.naming.sanitize import Piece
from reframe.naming.variables import DATE_FORMATS, VARIABLE_KINDS

__all__ = [
    "MAX_SPEC_NUMBER",
    "Group",
    "Slash",
    "Template",
    "TemplateError",
    "Text",
    "Value",
    "Var",
    "check_template",
    "format_value",
    "parse_template",
    "render",
    "template_variables",
]

#: A variable's value before formatting. ``None`` (and ``""``) is empty.
Value = str | int | float | date | None

_NAME = re.compile(r"^[A-Za-z0-9_-]+$")
_TEXT_SPECS = ("upper", "lower", "title")
#: The largest width or precision of a number or text format spec (``{name:.20}``,
#: ``{season:03}``). A path part has at most 255 bytes, so a wider value is never needed;
#: and without a limit ``{season:999999999999}`` makes ``format`` build a 1 TB string.
#: (``strftime`` limits its own output, so date specs need no limit.)
MAX_SPEC_NUMBER = 255
#: Decimal digits of any script: ``format`` reads them all (``\d`` of a ``str`` pattern).
_SPEC_DIGITS = re.compile(r"\d+")
#: Names people type for a variable that has another name here.
_ALIASES = {
    "episode_title": "sub_title",
    "episode_name": "sub_title",
    "show": "name",
    "show_name": "name",
    "series": "name",
    "movie": "name",
    "group": "release_group",
    "res": "resolution",
    "ep": "episode",
    "quality": "quality_bitrate",
    "ext": "container",
}


@dataclass(frozen=True, slots=True)
class Text:
    text: str


@dataclass(frozen=True, slots=True)
class Var:
    name: str
    spec: str | None
    start: int
    """Position of ``{`` in the template."""
    end: int
    """Position after ``}``."""


@dataclass(frozen=True, slots=True)
class Slash:
    pass


@dataclass(frozen=True, slots=True)
class Group:
    nodes: tuple[Node, ...]
    start: int


type Node = Text | Var | Slash | Group


@dataclass(frozen=True, slots=True)
class TemplateError:
    message: str
    position: int


@dataclass(frozen=True, slots=True)
class Template:
    text: str
    nodes: tuple[Node, ...]
    errors: tuple[TemplateError, ...]


class _Builder:
    def __init__(self) -> None:
        self.stack: list[tuple[list[Node], int]] = [([], 0)]
        self.buffer: list[str] = []

    def flush(self) -> None:
        if self.buffer:
            self.stack[-1][0].append(Text("".join(self.buffer)))
            self.buffer = []

    def add(self, node: Node) -> None:
        self.flush()
        self.stack[-1][0].append(node)


@lru_cache(maxsize=512)
def parse_template(text: str) -> Template:
    """Parse a template. Syntax errors are collected; the parse goes on after each one."""
    errors: list[TemplateError] = []
    b = _Builder()
    i = 0
    while i < len(text):
        char = text[i]
        if char == "{":
            if text.startswith("{{", i):
                b.buffer.append("{")
                i += 2
                continue
            close = text.find("}", i + 1)
            reopen = text.find("{", i + 1)
            if close == -1 or (reopen != -1 and reopen < close):
                errors.append(TemplateError("'{' is not closed (write '{{' for a brace)", i))
                b.buffer.append("{")
                i += 1
                continue
            body = text[i + 1 : close]
            name, colon, spec = body.partition(":")
            if not name:
                errors.append(TemplateError("A variable has no name: '{}'", i))
            elif not _NAME.match(name):
                errors.append(TemplateError(f"'{{{body}}}' is not a variable name", i))
            else:
                b.add(Var(name, spec if colon else None, i, close + 1))
            i = close + 1
        elif char == "}":
            if text.startswith("}}", i):
                b.buffer.append("}")
                i += 2
                continue
            errors.append(TemplateError("'}' without '{' (write '}}' for a brace)", i))
            i += 1
        elif char == "<":
            b.flush()
            b.stack.append(([], i))
            i += 1
        elif char == ">":
            if len(b.stack) == 1:
                errors.append(TemplateError("'>' without '<'", i))
            else:
                b.flush()
                nodes, start = b.stack.pop()
                b.add(Group(tuple(nodes), start))
            i += 1
        elif char == "/":
            b.add(Slash())
            i += 1
        else:
            b.buffer.append(char)
            i += 1
    b.flush()
    while len(b.stack) > 1:
        nodes, start = b.stack.pop()
        errors.append(TemplateError("'<' is not closed", start))
        b.add(Group(tuple(nodes), start))
    return Template(text, tuple(b.stack[0][0]), tuple(errors))


def template_variables(nodes: tuple[Node, ...]) -> Iterator[Var]:
    """Every variable of a template, groups included, in order."""
    for node in nodes:
        if isinstance(node, Var):
            yield node
        elif isinstance(node, Group):
            yield from template_variables(node.nodes)


def _check_spec_size(spec: str) -> None:
    """Raise ``ValueError`` when a number in ``spec`` (a width or precision) is more than
    :data:`MAX_SPEC_NUMBER`, before ``format`` builds the string.

    Every run of decimal digits counts, in any script: ``format`` reads Arabic-Indic and
    full-width digits too (U+0662 U+0665 U+0666 is 256). A digit fill character (``0>3``) is
    a run of one digit, so it never fails.
    """
    for match in _SPEC_DIGITS.finditer(spec):
        digits = "".join(str(unicodedata.decimal(char)) for char in match.group()).lstrip("0")
        if len(digits) > len(str(MAX_SPEC_NUMBER)) or int(digits or "0") > MAX_SPEC_NUMBER:
            raise ValueError(
                f"a width or precision of more than {MAX_SPEC_NUMBER} cannot be used "
                f"(a file name has at most {MAX_SPEC_NUMBER} bytes)"
            )


def format_value(name: str, value: Value, spec: str | None) -> str:
    """Format a variable's value. ``""`` for an empty value. A bad spec raises
    ``ValueError`` (:func:`check_template` reports it before rendering), and so does a width
    or precision over :data:`MAX_SPEC_NUMBER`."""
    if value is None:
        return ""
    if isinstance(value, date):
        fmt = spec or DATE_FORMATS.get(name, "%Y-%m-%d")
        if "%" not in fmt:
            raise ValueError(f"'{fmt}' is not a date format (use % codes such as %Y-%m-%d)")
        return value.strftime(fmt)
    if isinstance(value, int | float):
        if spec:
            _check_spec_size(spec)
            try:
                return format(value, spec)
            except OverflowError as exc:  # ``{episode:c}`` of a number that is no character
                raise ValueError(str(exc)) from exc
        if isinstance(value, float) and value.is_integer():
            return str(int(value))
        return str(value)
    if not value or spec is None:
        return value
    if spec == "upper":
        return value.upper()
    if spec == "lower":
        return value.lower()
    if spec == "title":
        return title_case(value)
    _check_spec_size(spec)
    return format(value, spec)


def _check_spec(name: str, spec: str) -> str | None:
    """Why ``spec`` does not fit the variable's kind, or ``None``."""
    kind = VARIABLE_KINDS.get(name, "text")
    try:
        if kind == "date":
            format_value(name, datetime(2026, 1, 2, 3, 4, 5), spec)
        elif kind == "number":
            format_value(name, 1, spec)
        elif spec not in _TEXT_SPECS:
            format_value(name, "text", spec)
    except ValueError as exc:
        return str(exc)
    return None


def render(template: Template, values: Mapping[str, Value]) -> list[list[Piece]]:
    """Render a parsed template into path segments (split at ``/``). The last segment is the
    file name (without extension). A value that cannot be formatted with its spec is
    rendered with its default format."""
    items, _ = _render(template.nodes, values)
    segments: list[list[Piece]] = [[]]
    for item in items:
        if isinstance(item, Slash):
            segments.append([])
        else:
            segments[-1].append(item)
    return segments


def _render(
    nodes: tuple[Node, ...], values: Mapping[str, Value]
) -> tuple[list[Piece | Slash], bool]:
    items: list[Piece | Slash] = []
    empty = False
    for node in nodes:
        if isinstance(node, Text):
            items.append(Piece(node.text))
        elif isinstance(node, Slash):
            items.append(node)
        elif isinstance(node, Var):
            value = values.get(node.name)
            try:
                text = format_value(node.name, value, node.spec)
            except ValueError:
                text = format_value(node.name, value, None)
            empty = empty or not text
            items.append(Piece(text, node.name))
        else:
            inner, inner_empty = _render(node.nodes, values)
            if not inner_empty:
                items.extend(inner)
    return items, empty


def _pointer(field: str) -> str:
    """``output.naming.template`` → ``/output/naming/template``; ``a[2].b`` → ``/a/2/b``."""
    parts = re.sub(r"\[(\d+)\]", r".\1", field).split(".")
    return format_pointer(part for part in parts if part)


def _suggestions(name: str) -> list[str]:
    names = list(VARIABLE_KINDS)
    found: list[str] = []
    lower = name.lower()
    for candidate in (lower, lower.replace("_", "-"), lower.replace("-", "_"), _ALIASES.get(lower)):
        if candidate in VARIABLE_KINDS and candidate not in found:
            found.append(candidate)
    for candidate in difflib.get_close_matches(lower, names, n=3, cutoff=0.6):
        if candidate not in found:
            found.append(candidate)
    return found[:3]


def check_template(
    template: str,
    *,
    field: str = "output.naming.template",
    target: FixTarget = "job",
) -> list[ValidationIssue]:
    """Syntax errors, unknown variables (with "did you mean" fixes) and bad format specs.

    ``field`` is the dotted path of the template in the ``target`` document; the fixes
    replace the whole template there. The default is a job's own template
    (``JobSettings.output.naming.template``), which overrides the preset's for this job.
    """
    parsed = parse_template(template)
    pointer = _pointer(field)
    issues: list[ValidationIssue] = []

    def fix(label: str, value: str) -> Fix:
        return Fix(label=label, patch=[AddOp(path=pointer, value=value)], target=target)

    if not template.strip():
        issues.append(
            ValidationIssue(
                severity=Severity.WARNING,
                code="naming.empty_template",
                path=field,
                message="The naming template is empty: the source file name is used.",
                fixes=[fix("Use {main_title}", "{main_title}")],
            )
        )
    for error in parsed.errors:
        issues.append(
            ValidationIssue(
                severity=Severity.ERROR,
                code="naming.template_syntax",
                path=field,
                message=f"{error.message} (position {error.position + 1}).",
            )
        )
    for var in template_variables(parsed.nodes):
        if var.name not in VARIABLE_KINDS:
            spec = f":{var.spec}" if var.spec is not None else ""
            suggestions = _suggestions(var.name)
            fixes = [
                fix(
                    f"Use {{{name}}}",
                    template[: var.start] + "{" + name + spec + "}" + template[var.end :],
                )
                for name in suggestions
            ]
            hint = f" Did you mean {{{suggestions[0]}}}?" if suggestions else ""
            issues.append(
                ValidationIssue(
                    severity=Severity.ERROR,
                    code="naming.unknown_variable",
                    path=field,
                    message=f"Unknown variable {{{var.name}}} (position {var.start + 1}).{hint}",
                    fixes=fixes,
                )
            )
        elif var.spec is not None:
            problem = _check_spec(var.name, var.spec)
            if problem is not None:
                issues.append(
                    ValidationIssue(
                        severity=Severity.ERROR,
                        code="naming.bad_format_spec",
                        path=field,
                        message=f"{{{var.name}:{var.spec}}}: {problem}.",
                        fixes=[
                            fix(
                                f"Use {{{var.name}}}",
                                template[: var.start] + "{" + var.name + "}" + template[var.end :],
                            )
                        ],
                    )
                )
    if "\\" in template:
        issues.append(
            ValidationIssue(
                severity=Severity.WARNING,
                code="naming.backslash",
                path=field,
                message="'\\' is not a folder separator in a naming template: use '/'.",
                fixes=[fix("Use / for subfolders", template.replace("\\", "/"))],
            )
        )
    return issues
