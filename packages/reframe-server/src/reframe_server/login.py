"""Password login: the scrypt hash in ``<config dir>/auth.json``, the sessions of this run and
the login rate limit. Sessions live in memory only, so a restart ends every one of them."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import ipaddress
import logging
import math
import secrets
import time
import unicodedata
from collections import OrderedDict, deque
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ValidationError
from starlette.requests import HTTPConnection

from reframe import paths
from reframe.settings import JsonDocumentFile
from reframe_server.errors import ProblemError

__all__ = [
    "AUTH_FILE",
    "MAX_PASSWORD",
    "SESSION_TTL",
    "LoginService",
    "PasswordHash",
    "auth_path",
    "get_login",
    "load_password",
    "password_problem",
    "save_password",
]

log = logging.getLogger(__name__)

AUTH_FILE = "auth.json"
SCRYPT_N = 2**17
"""scrypt cost of a new hash: OWASP's minimum (128 MiB, about 0.3 s). Tests lower it."""
SCRYPT_R = 8
SCRYPT_P = 1
_MAX_MEMORY = 2**28
"""``maxmem`` of ``hashlib.scrypt``: OpenSSL's default (32 MiB) refuses the cost above."""
MIN_PASSWORD = 8
MAX_PASSWORD = 1024
SESSION_TTL = 30 * 24 * 3600
"""Seconds a session lasts after its login."""
MAX_SESSIONS = 1000
LOGIN_ATTEMPTS = 5
"""Wrong passwords a client may send per :data:`LOGIN_WINDOW`."""
LOGIN_WINDOW = 60.0
MAX_CLIENTS = 4096

_clock = time.monotonic


def auth_path(config_dir: Path | None) -> Path:
    return (config_dir if config_dir is not None else paths.config_dir()) / AUTH_FILE


def _encode(password: str) -> bytes:
    # One password typed on two systems may arrive composed or decomposed; a lone surrogate
    # from a JSON string must not make encoding fail.
    return unicodedata.normalize("NFC", password).encode("utf-8", "surrogatepass")


class PasswordHash(BaseModel):
    """The ``password`` object of ``auth.json``."""

    algorithm: Literal["scrypt"]
    n: int
    r: int
    p: int
    salt: str
    hash: str

    def matches(self, password: str) -> bool:
        """Raises ``ValueError`` for a cost or a base64 text that is not valid."""
        expected = base64.b64decode(self.hash, validate=True)
        derived = hashlib.scrypt(
            _encode(password),
            salt=base64.b64decode(self.salt, validate=True),
            n=self.n,
            r=self.r,
            p=self.p,
            maxmem=_MAX_MEMORY,
            dklen=len(expected),
        )
        return hmac.compare_digest(derived, expected)


def load_password(path: Path) -> PasswordHash | str | None:
    """The hash in ``path``; ``None`` when no password is set; or why the file is unusable.
    Blocking."""
    read = JsonDocumentFile(path).read()
    entry = read.data.get("password") if read.data is not None else None
    if read.status == "missing" or (read.status == "ok" and entry is None):
        return None
    try:
        return PasswordHash.model_validate(entry)
    except ValidationError:
        return f"{path} cannot be used: {read.detail or 'the password entry is damaged'}"


def password_problem(password: str) -> str | None:
    """Why ``password`` cannot be the new password, or ``None``."""
    if len(password) < MIN_PASSWORD:
        return f"The password must have at least {MIN_PASSWORD} characters."
    return None


def save_password(path: Path, password: str) -> str | None:
    """Write the hash of ``password`` to ``path`` atomically (mode 0600 on POSIX: ``mkstemp``),
    keeping the file's other fields. Returns ``None``, or why it was not written. Blocking."""
    file = JsonDocumentFile(path)
    read = file.read()
    data = read.data if read.status == "ok" and read.data is not None else {}
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(
        _encode(password), salt=salt, n=SCRYPT_N, r=SCRYPT_R, p=SCRYPT_P, maxmem=_MAX_MEMORY
    )
    data.setdefault("schema_version", 1)
    data["password"] = PasswordHash(
        algorithm="scrypt",
        n=SCRYPT_N,
        r=SCRYPT_R,
        p=SCRYPT_P,
        salt=base64.b64encode(salt).decode("ascii"),
        hash=base64.b64encode(digest).decode("ascii"),
    ).model_dump()
    return file.write(data)


class Sessions:
    """Session tokens of this run. Only their SHA-256 is kept."""

    def __init__(self) -> None:
        self._expiry: OrderedDict[bytes, float] = OrderedDict()

    @staticmethod
    def _key(token: str) -> bytes:
        return hashlib.sha256(token.encode("utf-8", "surrogatepass")).digest()

    def create(self) -> str:
        """A new token; the oldest session ends when there are too many (they also expire
        oldest first)."""
        while len(self._expiry) >= MAX_SESSIONS:
            self._expiry.popitem(last=False)
        token = secrets.token_urlsafe(32)
        self._expiry[self._key(token)] = _clock() + SESSION_TTL
        return token

    def valid(self, token: str | None) -> bool:
        if not token:
            return False
        expiry = self._expiry.get(self._key(token))
        return expiry is not None and expiry > _clock()

    def end(self, token: str | None) -> None:
        if token:
            self._expiry.pop(self._key(token), None)

    def end_all(self) -> None:
        self._expiry.clear()


def _client_key(host: str | None) -> str:
    """The rate-limit bucket of a client address: one per IPv4 address, one per IPv6 /64
    (a client can pick any address of its /64)."""
    try:
        address = ipaddress.ip_address(host or "")
    except ValueError:
        return host or ""
    if isinstance(address, ipaddress.IPv6Address):
        if address.ipv4_mapped is not None:
            return str(address.ipv4_mapped)
        return str(ipaddress.ip_network(f"{address}/64", strict=False))
    return str(address)


class _Limiter:
    """Wrong passwords per client within :data:`LOGIN_WINDOW`."""

    def __init__(self) -> None:
        self._failures: OrderedDict[str, deque[float]] = OrderedDict()

    def retry_after(self, client: str) -> int | None:
        failures = self._failures.get(client)
        if failures is None or len(failures) < LOGIN_ATTEMPTS:
            return None
        wait = failures[0] + LOGIN_WINDOW - _clock()
        return math.ceil(wait) if wait > 0 else None

    def failed(self, client: str) -> None:
        failures = self._failures.setdefault(client, deque(maxlen=LOGIN_ATTEMPTS))
        failures.append(_clock())
        self._failures.move_to_end(client)
        while len(self._failures) > MAX_CLIENTS:
            self._failures.popitem(last=False)

    def succeeded(self, client: str) -> None:
        self._failures.pop(client, None)


def _no_password(detail: str) -> ProblemError:
    return ProblemError(503, "auth.no_password", "No password is set", detail)


class LoginService:
    """The password, the sessions and the rate limit of one app. Password checks run in a
    worker thread, one at a time, so parallel guesses cannot pass the limit together."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.sessions = Sessions()
        self._limiter = _Limiter()
        self._lock = asyncio.Lock()

    async def _matches(self, password: str, client: str | None) -> bool:
        """Call with the lock held. Raises a 429 or 503 :class:`ProblemError`."""
        key = _client_key(client)
        wait = self._limiter.retry_after(key)
        if wait is not None:
            raise ProblemError(
                429,
                "auth.rate_limited",
                "Too many wrong passwords",
                f"Try again in {wait} seconds.",
                headers={"Retry-After": str(wait)},
            )
        record = await asyncio.to_thread(load_password, self.path)
        if not isinstance(record, PasswordHash):
            raise _no_password(record or "Set one with: reframe-server --set-password")
        try:
            matches = await asyncio.to_thread(record.matches, password)
        except ValueError as exc:
            log.error("%s cannot be used: %s", self.path, exc)
            raise _no_password(f"{self.path} cannot be used: the hash is damaged") from None
        if matches:
            self._limiter.succeeded(key)
        else:
            self._limiter.failed(key)
        return matches

    async def login(self, password: str, client: str | None) -> str:
        """A new session token for the right password. Raises a 401, 429 or 503
        :class:`ProblemError`."""
        async with self._lock:
            if not await self._matches(password, client):
                raise ProblemError(401, "auth.invalid", "The password is wrong")
            return self.sessions.create()

    def logout(self, token: str | None) -> None:
        self.sessions.end(token)

    async def change_password(
        self, current: str, new: str, client: str | None, *, new_session: bool
    ) -> str | None:
        """Replace the password and end every session. Returns a new session token when
        ``new_session``. Raises a 403 (``current`` is wrong), 422, 429, 500 or 503
        :class:`ProblemError`."""
        weak = password_problem(new)
        if weak is not None:
            raise ProblemError(422, "auth.weak_password", weak)
        async with self._lock:
            if not await self._matches(current, client):
                raise ProblemError(403, "auth.wrong_password", "The current password is wrong")
            error = await asyncio.to_thread(save_password, self.path, new)
            if error is not None:
                log.error("the password was not saved to %s: %s", self.path, error)
                raise ProblemError(500, "auth.not_saved", "The password was not saved")
            self.sessions.end_all()
            return self.sessions.create() if new_session else None


def get_login(conn: HTTPConnection) -> LoginService:
    service: LoginService = conn.app.state.login
    return service
