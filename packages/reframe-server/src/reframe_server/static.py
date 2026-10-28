"""The frontend's files in web mode: hashed assets cached for good, ``index.html`` for any
other path outside ``/api``. Desktop mode serves none: the shell bundles the frontend."""

from __future__ import annotations

from fastapi import FastAPI

from reframe_server.config import ServerConfig

__all__ = ["install"]


def install(app: FastAPI, config: ServerConfig) -> None:
    """Add the static routes; called after every API router, so that they come last."""
