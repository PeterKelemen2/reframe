"""Base classes and shared field types for every Reframe model.

:class:`ReframeModel` is for runtime and API models. It rejects unknown fields
(``extra="forbid"``), so a typo in code or in a request fails at once. :class:`DocumentModel`
is for models inside a persisted document (presets, settings, queued job settings, the probe
cache). It keeps unknown fields and writes them back unchanged (``extra="allow"``), so an older
Reframe does not damage a file from a newer one. A model that can appear in such a document is
a document model, even when an API model uses it too (:class:`Rational`). Both serialise by
alias and accept the field name or the alias on input. Floats must be finite
(``allow_inf_nan=False``), because JSON has no NaN or infinity.
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
    """``json_schema_extra`` hook: drop the ``additionalProperties: true`` that ``extra="allow"``
    adds, so the generated TypeScript types stay strict."""
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
#: checked here; normalisation is in ``reframe.languages``. ISO 639-2 three-letter codes are
#: valid BCP 47 primary subtags.
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
