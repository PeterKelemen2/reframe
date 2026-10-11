"""Base classes and shared field types for every Reframe model.

Two base classes:

- :class:`ReframeModel` — runtime and API models (events, issues, tool and encoder status,
  plans, progress). Unknown fields are an error (``extra="forbid"``), so a typo in code or in
  a request is caught at once.
- :class:`DocumentModel` — models that are part of a **persisted document**: the presets file,
  the settings file, the job settings stored in the queue, the probe cache. Every model that
  can appear inside such a document is a document model, also when an API model uses it too
  (for example :class:`Rational`). Unknown fields are
  **kept** (``extra="allow"``) and written back unchanged, so a file written by a newer
  Reframe is not damaged by an older one (02 §Cross-cutting rules, rule 4). The JSON Schema of
  a document model does not say ``additionalProperties: true``: that is the JSON Schema default
  anyway, and it keeps the generated TypeScript types strict.

Both serialise by alias and accept the field name or the alias on input (only
:class:`~reframe.models.issues.JsonPatchOp` uses an alias: ``from``). Floats must be finite
(``allow_inf_nan=False``): JSON has no NaN or infinity. The docstring under a field becomes
its ``description`` in the JSON Schema (``use_attribute_docstrings``), so the frontend's
generated types carry the same documentation.
"""

from __future__ import annotations

from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

__all__ = [
    "DocumentModel",
    "LanguageTag",
    "NonNegativeFloat",
    "NonNegativeInt",
    "PositiveInt",
    "Rational",
    "ReframeModel",
]


def _drop_additional_properties(schema: dict[str, Any], cls: type[Any]) -> None:
    """``json_schema_extra`` hook: remove ``additionalProperties: true`` from the schema."""
    if schema.get("additionalProperties") is True:
        del schema["additionalProperties"]


class ReframeModel(BaseModel):
    """Base of runtime and API models: unknown fields are rejected."""

    model_config = ConfigDict(
        extra="forbid",
        validate_by_name=True,
        validate_by_alias=True,
        serialize_by_alias=True,
        allow_inf_nan=False,
        use_attribute_docstrings=True,
    )


class DocumentModel(BaseModel):
    """Base of persisted-document models: unknown fields are kept and written back."""

    model_config = ConfigDict(
        extra="allow",
        validate_by_name=True,
        validate_by_alias=True,
        serialize_by_alias=True,
        allow_inf_nan=False,
        use_attribute_docstrings=True,
        json_schema_extra=_drop_additional_properties,
    )


#: A BCP 47 language tag (``en``, ``hun``, ``pt-BR``, ``zh-Hans``, ``und``). Only the shape is
#: checked here. Normalisation and the ISO 639-2/B and /T forms are in ``reframe.languages``
#: (C-6). ISO 639-2 three-letter codes are valid BCP 47 primary subtags.
LanguageTag = Annotated[
    str,
    StringConstraints(pattern=r"^[A-Za-z]{2,8}(-[A-Za-z0-9]{1,8})*$", max_length=64),
]

NonNegativeInt = Annotated[int, Field(ge=0)]
PositiveInt = Annotated[int, Field(ge=1)]
NonNegativeFloat = Annotated[float, Field(ge=0.0)]


class Rational(DocumentModel):
    """An exact fraction ``num/den``: frame rates (``24000/1001``) and aspect ratios (``32:27``).

    ffprobe's ``0/0`` ("unknown") is never stored as a ``Rational``: the field is ``None``.
    A document model, because job settings and probe results contain it.
    """

    num: int
    den: Annotated[int, Field(ge=1)] = 1

    @classmethod
    def square(cls) -> Rational:
        """``1/1`` (square pixels)."""
        return cls(num=1, den=1)

    def __float__(self) -> float:
        return self.num / self.den

    def __str__(self) -> str:
        return f"{self.num}/{self.den}"
