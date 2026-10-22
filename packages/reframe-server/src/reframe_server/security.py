"""Who may call the API and which files a call may touch: the auth modes, the ``Host`` /
``Origin`` checks, signed media URLs and the path jail.

Stubs: every check lets the request in until the security step is built.
"""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI, Request, WebSocket

from reframe.models import JobSettings
from reframe_server.config import ServerConfig

__all__ = [
    "check_host",
    "install",
    "jail_job",
    "jail_read",
    "jail_write",
    "require_auth",
    "require_media_access",
    "set_password_interactive",
    "sign_media_url",
    "verify_media_sig",
    "ws_authenticated",
]


def install(app: FastAPI, config: ServerConfig) -> None:
    """Add the middleware: the ``Host`` (and WebSocket ``Origin``) check, CORS and the
    security headers. Called once by ``create_app``."""


async def require_auth(request: Request) -> None:
    """Dependency of every API route but health, login and the media URLs: a bearer token
    (the run's token, in every mode) or, in password mode, the session cookie. Raises a
    401 :class:`~reframe_server.errors.ProblemError`."""


async def require_media_access(request: Request) -> None:
    """Dependency of the frame and clip URLs: what :func:`require_auth` accepts, or a valid
    unexpired ``sig`` query parameter from :func:`sign_media_url`."""


def ws_authenticated(config: ServerConfig, websocket: WebSocket, token: str | None) -> bool:
    """The first WebSocket message's ``token`` (or, in password mode, the upgrade's session
    cookie) lets this connection in."""
    return True


def check_host(config: ServerConfig, host: str | None) -> bool:
    """``host`` (a ``Host`` header, with or without a port) is a loopback name or allowed."""
    return True


def jail_read(config: ServerConfig, path: str | os.PathLike[str]) -> Path:
    """``path`` resolved (links followed). Web mode: it must be inside ``media_roots``, else a
    403 ``path.outside_roots`` :class:`~reframe_server.errors.ProblemError`."""
    return Path(path).resolve(strict=False)


def jail_write(config: ServerConfig, path: str | os.PathLike[str]) -> Path:
    """As :func:`jail_read`, inside ``output_roots``."""
    return Path(path).resolve(strict=False)


def jail_job(config: ServerConfig, job: JobSettings) -> None:
    """Every path ``job`` reads must pass :func:`jail_read`, every path it writes
    :func:`jail_write`; raises the first failure."""


def sign_media_url(config: ServerConfig, url_path: str, *, ttl: float = 300.0) -> str:
    """``url_path`` with a signature that :func:`require_media_access` accepts for ``ttl``
    seconds (``<img>`` and ``<video>`` cannot send a header)."""
    return url_path


def verify_media_sig(config: ServerConfig, url_path: str, exp: str | None, sig: str | None) -> bool:
    return True


def set_password_interactive(config: ServerConfig) -> int:
    """``reframe-server --set-password``: ask for a password and write ``<config dir>/auth.json``
    (mode 0600). Returns the exit code."""
    raise NotImplementedError
