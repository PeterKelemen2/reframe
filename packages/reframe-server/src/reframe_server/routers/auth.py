"""Login, logout and the password (password mode)."""

from __future__ import annotations

from fastapi import Depends, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from reframe_server import security
from reframe_server.api import api_router
from reframe_server.config import AuthMode, ServerConfig
from reframe_server.deps import ConfigDep
from reframe_server.errors import ProblemError
from reframe_server.login import MAX_PASSWORD, SESSION_TTL, get_login

router = api_router("auth")


class AuthStatus(BaseModel):
    """How this server checks callers, and whether this request passed."""

    model_config = ConfigDict(extra="forbid", use_attribute_docstrings=True)

    mode: AuthMode
    """``password``: log in with ``POST /api/auth/login``; ``token``: send the run's token as
    ``Authorization: Bearer``; ``none``: no credentials needed."""
    authenticated: bool
    """The request carried credentials that the other routes accept."""


class Login(BaseModel):
    model_config = ConfigDict(extra="forbid", use_attribute_docstrings=True)

    password: str = Field(max_length=MAX_PASSWORD)


class PasswordChange(BaseModel):
    model_config = ConfigDict(extra="forbid", use_attribute_docstrings=True)

    current: str = Field(max_length=MAX_PASSWORD)
    new: str = Field(max_length=MAX_PASSWORD)
    """At least 8 characters."""


def _status(request: Request, config: ServerConfig) -> AuthStatus:
    return AuthStatus(mode=config.auth_mode, authenticated=security.authenticated(request))


def _set_session(request: Request, response: Response, token: str) -> None:
    response.set_cookie(
        security.SESSION_COOKIE,
        token,
        max_age=SESSION_TTL,
        path="/api",
        secure=request.url.scheme == "https",
        httponly=True,
        samesite="strict",
    )


def _client(request: Request) -> str | None:
    return request.client.host if request.client is not None else None


@router.get("/auth/status")
async def status(request: Request, config: ConfigDep) -> AuthStatus:
    """The auth mode, and whether this request is logged in. Needs no credentials."""
    return _status(request, config)


@router.post("/auth/login")
async def login(body: Login, request: Request, response: Response, config: ConfigDep) -> AuthStatus:
    """Password mode: check the password and set the session cookie. Wrong passwords are
    rate limited per client (429 with ``Retry-After``)."""
    if config.auth_mode != "password":
        raise ProblemError(409, "auth.not_password_mode", "This server has no password login")
    token = await get_login(request).login(body.password, _client(request))
    _set_session(request, response, token)
    return AuthStatus(mode="password", authenticated=True)


@router.post("/auth/logout")
async def logout(request: Request, response: Response, config: ConfigDep) -> AuthStatus:
    """End this session and remove its cookie."""
    get_login(request).logout(request.cookies.get(security.SESSION_COOKIE))
    response.delete_cookie(security.SESSION_COOKIE, path="/api", httponly=True, samesite="strict")
    return _status(request, config)


@router.put("/auth/password", dependencies=[Depends(security.require_auth)])
async def change_password(
    body: PasswordChange, request: Request, response: Response, config: ConfigDep
) -> AuthStatus:
    """Replace the password in ``auth.json``; needs the current one. Every session ends; a
    caller that used the session cookie gets a new one."""
    cookie = security.SESSION_COOKIE in request.cookies
    token = await get_login(request).change_password(
        body.current, body.new, _client(request), new_session=cookie
    )
    if token is not None:
        _set_session(request, response, token)
    return AuthStatus(mode=config.auth_mode, authenticated=True)
