"""Server configuration: environment variables with the ``REFRAME_`` prefix, then the command
line. A config that would expose an unauthenticated API beyond this machine, or the server's own
files as the frontend, is refused."""

from __future__ import annotations

import ipaddress
import secrets
from pathlib import Path
from typing import Literal, Self

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from reframe import paths

__all__ = ["AuthMode", "ServerConfig", "ServerMode", "is_loopback"]

ServerMode = Literal["web", "desktop"]
AuthMode = Literal["none", "token", "password"]

_LOOPBACK_NAMES = frozenset({"localhost", "localhost."})


def is_loopback(host: str) -> bool:
    """``host`` (a name or an address, IPv6 with or without brackets) is this machine only."""
    name = host.strip().lower()
    if name in _LOOPBACK_NAMES:
        return True
    try:
        return ipaddress.ip_address(name.strip("[]")).is_loopback
    except ValueError:
        return False


class ServerConfig(BaseSettings):
    """How one server process runs."""

    model_config = SettingsConfigDict(
        env_prefix="REFRAME_", extra="ignore", use_attribute_docstrings=True
    )

    host: str = "127.0.0.1"
    port: int = Field(default=0, ge=0, le=65535)
    """0: a free port chosen by the OS (desktop mode prints it in the ready line)."""
    mode: ServerMode = "web"
    auth: AuthMode | None = None
    """``None``: ``token`` in desktop mode; in web mode ``none`` on a loopback host, else an
    error (set it)."""
    token: SecretStr | None = None
    """The bearer token of this run (``REFRAME_TOKEN``); a random one when not set."""
    media_roots: list[Path] = Field(default_factory=list)
    """Web mode: folders the client may read from. Empty: none."""
    output_roots: list[Path] = Field(default_factory=list)
    """Web mode: folders the client may write to. Empty: none."""
    static_dir: Path | None = None
    """Web mode: the frontend build, served without a login. It must hold ``index.html`` and
    none of the server's folders, media roots or output roots. ``None``: no frontend."""
    cors_origins: list[str] = Field(default_factory=list)
    config_dir: Path | None = None
    """``None``: the core's default (``REFRAME_CONFIG_DIR`` or the platform folder)."""
    data_dir: Path | None = None
    """``None``: the core's default (``REFRAME_DATA_DIR`` or the platform folder)."""
    endpoint_file: Path | None = None
    """Where ``server.json`` is written (blanks around it are cut). ``None`` or blank:
    ``<data dir>/server.json``."""
    idle_exit: float | None = Field(default=None, gt=0)
    """Exit after this many idle seconds. ``None``: never."""
    owner_only: bool = False
    """Exit with code 75 when another process owns the queue."""
    allowed_hosts: list[str] | None = None
    """``Host`` names accepted besides the loopback names. ``None``: the defaults."""
    parent_pid: int | None = Field(default=None, gt=0)
    """Stop when this process ends (the desktop shell's pid). ``None``: no watch."""

    @field_validator("endpoint_file", mode="before")
    @classmethod
    def _blank_is_unset(cls, value: object) -> object:
        # The client reads REFRAME_ENDPOINT_FILE by the same rule, or it would wait for a file
        # that this server writes elsewhere.
        if isinstance(value, str):
            return value.strip() or None
        return value

    @model_validator(mode="after")
    def _resolve(self) -> Self:
        if self.mode == "desktop":
            if self.auth not in (None, "token"):
                raise ValueError("desktop mode always uses token auth")
            self.auth = "token"
        elif self.auth is None:
            if not is_loopback(self.host):
                raise ValueError(f"auth must be set when the server binds {self.host}")
            self.auth = "none"
        if self.auth == "none" and not is_loopback(self.host):
            raise ValueError("auth none is allowed only on a loopback host")
        if self.token is None or not self.token.get_secret_value():
            self.token = SecretStr(secrets.token_urlsafe(32))
        return self

    @model_validator(mode="after")
    def _check_static_dir(self) -> Self:
        if self.mode != "web" or self.static_dir is None:
            return self
        if not (self.static_dir / "index.html").is_file():
            raise ValueError(f"static_dir {self.static_dir} has no index.html")
        served = self.static_dir.resolve()
        kept = [
            ("config folder", self.config_dir or paths.config_dir()),
            ("data folder", self.data_dir or paths.data_dir()),
            ("cache folder", paths.cache_dir()),
            *(("media root", root) for root in self.media_roots),
            *(("output root", root) for root in self.output_roots),
        ]
        if self.endpoint_file is not None:
            kept.append(("endpoint file", self.endpoint_file))
        for name, path in kept:
            if path.resolve().is_relative_to(served):
                raise ValueError(
                    f"static_dir {self.static_dir} holds the {name} {path}: "
                    "every file in it would be served without a login"
                )
        return self

    @property
    def auth_mode(self) -> AuthMode:
        """The resolved auth mode (never ``None`` after validation)."""
        assert self.auth is not None
        return self.auth

    @property
    def secret_token(self) -> str:
        assert self.token is not None
        return self.token.get_secret_value()
