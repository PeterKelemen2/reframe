"""The language list of the language picker."""

from __future__ import annotations

import asyncio
import functools

from fastapi import Request, Response
from pydantic import BaseModel, ConfigDict

from reframe.languages import language_list
from reframe_server.api import api_router
from reframe_server.routers.definitions import StaticBody

router = api_router("languages")


class Language(BaseModel):
    """One language of the picker."""

    model_config = ConfigDict(extra="forbid", use_attribute_docstrings=True, from_attributes=True)

    tag: str
    """Canonical BCP 47 tag (``hu``, ``pt-BR``): the value a job stores."""
    iso639_1: str | None
    """ISO 639-1 code (``hu``); ``null`` when the language has none."""
    iso639_2b: str
    """ISO 639-2/B code that MKV and WebM are written with (``hun``, ``ger``)."""
    iso639_2t: str
    """ISO 639-2/T code that MP4 is written with (``hun``, ``deu``)."""
    iso639_3: str
    """ISO 639-3 code of the base language."""
    english_name: str
    native_name: str
    """The language's name for itself (``magyar``); the English name when none is known."""
    variant: bool
    """A region or script variant of a base language (``pt-BR``)."""


class LanguageList(BaseModel):
    model_config = ConfigDict(extra="forbid", use_attribute_docstrings=True)

    languages: list[Language]
    """Ordered by English name."""


@functools.cache
def _body() -> StaticBody:
    entries = [Language.model_validate(entry) for entry in language_list()]
    return StaticBody.of(LanguageList(languages=entries))


@router.get(
    "/languages",
    name="list",
    response_model=LanguageList,
    responses={304: {"description": "The client's copy (``If-None-Match``) is current"}},
)
async def list_languages(request: Request) -> Response:
    """Every language of the picker. Send the ``ETag`` back in ``If-None-Match``: the answer
    is a ``304`` while the list is the same."""
    return (await asyncio.to_thread(_body)).respond(request)
