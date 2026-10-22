"""Who may call the API and which files a call may touch: the auth modes, the ``Host`` /
``Origin`` checks, signed media URLs and the path jail."""

from __future__ import annotations

import base64
import getpass
import hashlib
import hmac
import ipaddress
import logging
import os
import socket
import sys
import time
from collections.abc import Iterator, Mapping
from pathlib import Path, PurePath
from typing import Literal
from urllib.parse import urlsplit

from fastapi import FastAPI, Request, WebSocket
from pydantic import BaseModel
from starlette.datastructures import Headers, MutableHeaders
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import HTTPConnection
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from reframe.definitions import load_definitions
from reframe.models import JobSettings
from reframe_server import filtertext, login
from reframe_server.config import ServerConfig, is_loopback
from reframe_server.errors import ProblemError, problem_response

__all__ = [
    "SESSION_COOKIE",
    "TAURI_ORIGINS",
    "authenticated",
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

log = logging.getLogger(__name__)

TAURI_ORIGINS = ("tauri://localhost", "http://tauri.localhost")
SESSION_COOKIE = "reframe_session"

_UNSAFE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
_CHALLENGE = {"WWW-Authenticate": 'Bearer realm="reframe"'}

APP_CSP = (
    "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data: blob:; media-src 'self' blob:; connect-src 'self'; "
    "object-src 'none'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'"
)
"""Inline styles stay allowed: a Vue build may insert static template parts, with their
``style`` attributes, as HTML text."""
DOCS_CSP = (
    "default-src 'none'; script-src 'unsafe-inline' https://cdn.jsdelivr.net; "
    "style-src https://cdn.jsdelivr.net; img-src 'self' data: https://fastapi.tiangolo.com; "
    "connect-src 'self'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'"
)
"""FastAPI's Swagger UI page loads its script and style from jsDelivr, its icon from
fastapi.tiangolo.com, and starts with an inline script."""


def install(app: FastAPI, config: ServerConfig) -> None:
    """Add the middleware (the ``Host`` and ``Origin`` check, CORS, the security headers) and
    the login service, and warn when nobody needs to log in or password login cannot work.
    Called once by ``create_app``."""
    app.state.login = login.LoginService(login.auth_path(config.config_dir))
    if config.auth_mode == "none":
        log.warning(
            "authentication is off (auth none): every user and program on this machine can "
            "use the API"
        )
    elif config.auth_mode == "password":
        record = login.load_password(app.state.login.path)
        if not isinstance(record, login.PasswordHash):
            log.warning(
                "password login is not possible: %s",
                record or "no password is set (reframe-server --set-password sets one)",
            )
    origins = [*(TAURI_ORIGINS if config.mode == "desktop" else ()), *config.cors_origins]
    if origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=origins,
            allow_methods=["*"],
            allow_headers=["Authorization", "Content-Type"],
            expose_headers=["Location", "Retry-After"],
        )
    app.add_middleware(_RequestGuard, config=config)
    docs = {path for path in (app.docs_url, app.swagger_ui_oauth2_redirect_url) if path}
    app.add_middleware(_SecurityHeaders, docs_paths=frozenset(docs))


class _RequestGuard:
    """Refuses a request or WebSocket upgrade with a foreign ``Host`` (DNS rebinding), and a
    WebSocket or a state-changing request whose ``Origin`` is another site's (CSRF). A client
    that sends no ``Origin`` is not a browser."""

    def __init__(self, app: ASGIApp, config: ServerConfig) -> None:
        self.app = app
        self.config = config

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return
        headers = Headers(scope=scope)
        host = headers.get("host")
        origin = headers.get("origin")
        refusal: ProblemError | None = None
        if not check_host(self.config, host):
            refusal = ProblemError(
                400, "request.host", "The Host header names a host this server does not serve"
            )
        elif (
            origin is not None
            and (scope["type"] == "websocket" or scope["method"] in _UNSAFE_METHODS)
            and not _origin_allowed(self.config, origin, host)
        ):
            refusal = ProblemError(403, "request.origin", "Requests from this origin are refused")
        if refusal is None:
            await self.app(scope, receive, send)
        elif scope["type"] == "websocket":
            await send({"type": "websocket.close", "code": 1008})  # uvicorn answers 403
        else:
            await problem_response(refusal.problem)(scope, receive, send)


class _SecurityHeaders:
    def __init__(self, app: ASGIApp, docs_paths: frozenset[str]) -> None:
        self.app = app
        self.docs_paths = docs_paths

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        csp = DOCS_CSP if scope["path"] in self.docs_paths else APP_CSP

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                headers.setdefault("Content-Security-Policy", csp)
                headers.setdefault("X-Content-Type-Options", "nosniff")
                headers.setdefault("X-Frame-Options", "DENY")
                headers.setdefault("Referrer-Policy", "no-referrer")
            await send(message)

        await self.app(scope, receive, send_with_headers)


def _bare_host(host: str) -> str:
    """``host`` without port, brackets and trailing dot, in lower case."""
    host = host.strip().lower()
    if host.startswith("["):
        name = host[1:].partition("]")[0]
    elif host.count(":") == 1:
        name = host.partition(":")[0]
    else:
        name = host
    return name.rstrip(".")


def _is_address(name: str) -> bool:
    try:
        ipaddress.ip_address(name)
    except ValueError:
        return False
    return True


def check_host(config: ServerConfig, host: str | None) -> bool:
    """``host`` (a ``Host`` header, with or without a port) is a loopback name or allowed.

    ``allowed_hosts`` ``None``: a server bound to another address also accepts that address
    and the machine's host name; bound to every address (``0.0.0.0``, ``::``), any IP address,
    since a DNS rebinding attack always sends the attacker's host name.
    """
    if not host:
        return False
    name = _bare_host(host)
    if is_loopback(name):
        return True
    if config.allowed_hosts is not None:
        return name in {_bare_host(allowed) for allowed in config.allowed_hosts}
    bound = _bare_host(config.host)
    if is_loopback(bound):
        return False
    machine = socket.gethostname().lower()
    short = machine.partition(".")[0]
    if name in (bound, machine, short, f"{short}.local"):
        return True
    return _is_address(bound) and ipaddress.ip_address(bound).is_unspecified and _is_address(name)


def _origin_allowed(config: ServerConfig, origin: str, host: str | None) -> bool:
    """``origin`` is the Tauri shell, a CORS origin, this server's own (the ``Host`` the
    request names), or a page of an allowed host (a reverse proxy may send its own ``Host``)."""
    origin = origin.strip().lower().rstrip("/")
    if origin in {o.lower().rstrip("/") for o in (*TAURI_ORIGINS, *config.cors_origins)}:
        return True
    netloc = urlsplit(origin).netloc
    allowed = {_bare_host(name) for name in config.allowed_hosts or ()}
    return netloc == (host or "").strip().lower() or _bare_host(netloc) in allowed


def _same_secret(given: str, secret: str) -> bool:
    return hmac.compare_digest(
        given.encode("utf-8", "surrogatepass"), secret.encode("utf-8", "surrogatepass")
    )


def _bearer(conn: HTTPConnection) -> str | None:
    scheme, _, token = conn.headers.get("authorization", "").partition(" ")
    return token.strip() if scheme.lower() == "bearer" else None


def _credentials(conn: HTTPConnection) -> Literal["ok", "missing", "invalid"]:
    """What the run's token (``Authorization: Bearer``, every mode) or, in password mode, the
    session cookie of ``conn`` is worth."""
    config: ServerConfig = conn.app.state.config
    if config.auth_mode == "none":
        return "ok"
    result: Literal["missing", "invalid"] = "missing"
    token = _bearer(conn)
    if token is not None:
        if _same_secret(token, config.secret_token):
            return "ok"
        result = "invalid"
    if config.auth_mode == "password" and SESSION_COOKIE in conn.cookies:
        if login.get_login(conn).sessions.valid(conn.cookies[SESSION_COOKIE]):
            return "ok"
        result = "invalid"
    return result


def authenticated(conn: HTTPConnection) -> bool:
    """``conn`` carries credentials that :func:`require_auth` accepts."""
    return _credentials(conn) == "ok"


def _unauthorized(result: str) -> ProblemError:
    if result == "missing":
        return ProblemError(401, "auth.required", "Credentials are required", headers=_CHALLENGE)
    return ProblemError(401, "auth.invalid", "The credentials are not valid", headers=_CHALLENGE)


async def require_auth(request: Request) -> None:
    """Dependency of every API route but health, login and the media URLs: a bearer token
    (the run's token, in every mode) or, in password mode, the session cookie. Raises a
    401 :class:`~reframe_server.errors.ProblemError`."""
    result = _credentials(request)
    if result != "ok":
        raise _unauthorized(result)


async def require_media_access(request: Request) -> None:
    """Dependency of the frame and clip URLs: what :func:`require_auth` accepts, or a valid
    unexpired ``sig`` query parameter from :func:`sign_media_url`."""
    result = _credentials(request)
    if result == "ok":
        return
    query = request.query_params
    if "sig" in query or "exp" in query:
        config: ServerConfig = request.app.state.config
        if verify_media_sig(config, request.url.path, query.get("exp"), query.get("sig")):
            return
        result = "invalid"
    raise _unauthorized(result)


def ws_authenticated(config: ServerConfig, websocket: WebSocket, token: str | None) -> bool:
    """The first WebSocket message's ``token`` (or, in password mode, the upgrade's session
    cookie) lets this connection in."""
    if config.auth_mode == "none":
        return True
    if token is not None and _same_secret(token, config.secret_token):
        return True
    return config.auth_mode == "password" and login.get_login(websocket).sessions.valid(
        websocket.cookies.get(SESSION_COOKIE)
    )


def _bad_path(path: str, reason: str) -> ProblemError:
    return ProblemError(400, "path.invalid", "The path is not valid", f"{path!r}: {reason}")


def _jail(config: ServerConfig, path: str | os.PathLike[str], roots: list[Path], use: str) -> Path:
    text = os.fspath(path)
    given = Path(text)
    if not given.is_absolute():
        raise _bad_path(text, "the path is not absolute")
    try:
        resolved = given.resolve(strict=False)
    except ValueError as exc:  # a NUL, or a character the file system cannot encode
        raise _bad_path(text, str(exc)) from None
    if config.mode == "desktop":
        return resolved
    for root in roots:
        if resolved.is_relative_to(Path(root).resolve(strict=False)):
            return resolved
    # The resolved path is not shown: it would tell where a link points.
    raise ProblemError(
        403,
        "path.outside_roots",
        "The path is outside the allowed folders",
        f"{text} is not inside a folder that this server may {use}.",
    )


def jail_read(config: ServerConfig, path: str | os.PathLike[str]) -> Path:
    """``path`` resolved (links followed). Web mode: it must be inside ``media_roots``, else a
    403 ``path.outside_roots`` :class:`~reframe_server.errors.ProblemError`. A path that is
    not absolute or holds a NUL is a 400 ``path.invalid`` in every mode."""
    return _jail(config, path, config.media_roots, "read from")


def jail_write(config: ServerConfig, path: str | os.PathLike[str]) -> Path:
    """As :func:`jail_read`, inside ``output_roots``."""
    return _jail(config, path, config.output_roots, "write to")


def _paths(
    value: object, where: tuple[str | int, ...]
) -> Iterator[tuple[tuple[str | int, ...], PurePath]]:
    if isinstance(value, PurePath):
        yield where, value
    elif isinstance(value, BaseModel):
        for name in type(value).model_fields:
            yield from _paths(getattr(value, name), (*where, name))
    elif isinstance(value, Mapping):
        for key, item in value.items():
            yield from _paths(item, (*where, str(key)))
    elif isinstance(value, (list, tuple, set, frozenset)):
        for index, item in enumerate(value):
            yield from _paths(item, (*where, index))


def jail_job(config: ServerConfig, job: JobSettings) -> None:
    """Every path ``job`` reads must pass :func:`jail_read`, every path it writes
    :func:`jail_write`; raises the first failure. Every ``Path`` in the model counts: those
    under ``output`` are written, the others read; an in-place edit also writes its source.

    Web mode: free filter text (``filters.*.custom``) may name only allowed filters, else a
    403 ``filter.not_allowed``."""
    for where, path in _paths(job, ()):
        if where[0] == "output":
            jail_write(config, path)
        else:
            jail_read(config, path)
            if job.output.edit_in_place and where == ("source", "path"):
                jail_write(config, path)
    if config.mode == "web":
        problem = filtertext.free_text_problem(job.filters.root, load_definitions())
        if problem is not None:
            raise ProblemError(
                403, "filter.not_allowed", "The free filter text is not allowed", problem
            )


def _media_key(config: ServerConfig) -> bytes:
    return hmac.new(
        config.secret_token.encode("utf-8", "surrogatepass"), b"reframe media url", hashlib.sha256
    ).digest()


def _media_sig(config: ServerConfig, url_path: str, exp: str) -> str:
    message = f"{url_path}\n{exp}".encode("utf-8", "surrogatepass")
    mac = hmac.new(_media_key(config), message, hashlib.sha256).digest()
    return base64.urlsafe_b64encode(mac).rstrip(b"=").decode("ascii")


def sign_media_url(config: ServerConfig, url_path: str, *, ttl: float = 300.0) -> str:
    """``url_path`` (the path a route sees, without a query) with a signature that
    :func:`require_media_access` accepts for ``ttl`` seconds (``<img>`` and ``<video>``
    cannot send a header). The key comes from the run's token, so a restart ends it."""
    exp = str(int(time.time() + ttl))
    return f"{url_path}?exp={exp}&sig={_media_sig(config, url_path, exp)}"


def verify_media_sig(config: ServerConfig, url_path: str, exp: str | None, sig: str | None) -> bool:
    if exp is None or sig is None:
        return False
    try:
        expires = int(exp)
    except ValueError:
        return False
    if expires <= time.time():
        return False
    return _same_secret(sig, _media_sig(config, url_path, exp))


def set_password_interactive(config: ServerConfig) -> int:
    """``reframe-server --set-password``: ask for a password and write ``<config dir>/auth.json``
    (mode 0600). Returns the exit code. A terminal is asked twice without echo; from a pipe
    the first line is the password."""
    path = login.auth_path(config.config_dir)
    try:
        if sys.stdin.isatty():
            password = getpass.getpass("New password: ")
            if getpass.getpass("Repeat the password: ") != password:
                print("reframe-server: the passwords differ; nothing was changed", file=sys.stderr)
                return 1
        else:
            password = sys.stdin.readline().removesuffix("\n").removesuffix("\r")
    except KeyboardInterrupt:
        return 130
    except EOFError:
        password = ""
    problem = login.password_problem(password)
    if problem is not None:
        print(f"reframe-server: {problem} Nothing was changed.", file=sys.stderr)
        return 1
    error = login.save_password(path, password)
    if error is not None:
        print(f"reframe-server: the password was not saved to {path}: {error}", file=sys.stderr)
        return 1
    print(
        f"The password is saved in {path}. A running server keeps its sessions until it restarts.",
        file=sys.stderr,
    )
    return 0
