"""Encoder, filter and container definitions; option search."""

from __future__ import annotations

import asyncio
import hashlib
from dataclasses import dataclass

from fastapi import Request, Response
from pydantic import BaseModel, ConfigDict

from reframe.definitions import Definitions, EncoderOption
from reframe.models import NamingVariable, json_text
from reframe.naming import VARIABLES
from reframe_server.api import api_router
from reframe_server.deps import ReframeDep
from reframe_server.errors import ProblemError

router = api_router("definitions")


@dataclass(frozen=True, slots=True)
class StaticBody:
    """A JSON answer that never changes while the server runs, with its ETag."""

    content: bytes
    etag: str

    @classmethod
    def of(cls, value: BaseModel) -> StaticBody:
        return cls.of_content(json_text(value).encode("ascii"))

    @classmethod
    def of_content(cls, content: bytes) -> StaticBody:
        return cls(content, f'"{hashlib.sha256(content).hexdigest()[:32]}"')

    def respond(self, request: Request) -> Response:
        """The body, or ``304`` when the client's ``If-None-Match`` names this ETag."""
        headers = {"ETag": self.etag, "Cache-Control": "no-cache"}
        if self._matches(request.headers.get("if-none-match")):
            return Response(status_code=304, headers=headers)
        return Response(self.content, media_type="application/json", headers=headers)

    def _matches(self, header: str | None) -> bool:
        if header is None:
            return False
        tags = {tag.strip().removeprefix("W/") for tag in header.split(",")}
        return "*" in tags or self.etag in tags


class DefinitionsDocument(BaseModel):
    model_config = ConfigDict(extra="forbid", use_attribute_docstrings=True)

    definitions: Definitions
    """Encoders with their option schemas, filters, containers, mixdowns, passthru codecs and
    track flags."""
    naming_variables: list[NamingVariable]
    """The variables of a naming template."""


_rendered: tuple[Definitions, StaticBody] | None = None


def _definitions_body(definitions: Definitions) -> StaticBody:
    global _rendered
    if _rendered is None or _rendered[0] is not definitions:
        document = DefinitionsDocument(definitions=definitions, naming_variables=list(VARIABLES))
        _rendered = (definitions, StaticBody.of(document))
    return _rendered[1]


@router.get(
    "/definitions",
    response_model=DefinitionsDocument,
    responses={304: {"description": "The client's copy (``If-None-Match``) is current"}},
)
async def get(request: Request, reframe: ReframeDep) -> Response:
    """Everything the editor builds its forms from. Send the ``ETag`` back in
    ``If-None-Match``: the answer is a ``304`` while the definitions are the same."""
    body = await asyncio.to_thread(lambda: _definitions_body(reframe.jobs.definitions))
    return body.respond(request)


@router.get("/definitions/encoders/{encoder_id}/options")
async def search_options(encoder_id: str, reframe: ReframeDep, q: str = "") -> list[EncoderOption]:
    """The video encoder's advanced options that match ``q`` (label, key, CLI name or help
    text), best match first; an empty ``q`` gives every option in definition order."""
    if encoder_id not in reframe.jobs.definitions.video_encoders:
        raise ProblemError(404, "definitions.unknown_encoder", f"No video encoder {encoder_id}")
    return reframe.jobs.search_options(encoder_id, q)
