"""Shell quoting for the command preview (:attr:`reframe.models.EncodePlan.display`).

The runner never uses a shell: it passes the argv list to the process. ``display`` is only
for people (the command preview drawer, the job log, bug reports), so it must paste into a
terminal and run:

- ``posix``: :func:`shlex.quote` (bash, zsh, fish for these characters).
- ``windows``: the quoting of the Microsoft C runtime (``CommandLineToArgvW``), which every
  Windows program uses to split its command line, plus quotes around any argument with a
  character that ``cmd.exe`` treats specially (``& | < > ^ ( ) % !``), so it pastes into
  ``cmd.exe`` and PowerShell. ``%`` inside quotes still expands in ``cmd.exe``; no argument
  the builder writes contains ``%name%``.

A measured value (:class:`~reframe.models.ValueRef`) shows as ``<a0.input_i>``.
"""

from __future__ import annotations

import os
import shlex
from collections.abc import Sequence
from typing import Literal

from reframe.models import PlanArg

__all__ = [
    "Shell",
    "command_line",
    "default_shell",
    "display_arg",
    "quote_posix",
    "quote_windows",
]

Shell = Literal["posix", "windows"]

#: Characters that make a Windows argument need quotes: whitespace, the quote itself, and the
#: characters ``cmd.exe`` interprets outside quotes.
_WINDOWS_SPECIAL = frozenset(' \t\n\v"&|<>^()%!')


def default_shell() -> Shell:
    """The quoting style of this OS (``os.name`` is a constant of the interpreter)."""
    return "windows" if os.name == "nt" else "posix"


def display_arg(arg: PlanArg) -> str:
    """The text of an argument, with measured values as ``<id.key>``."""
    if isinstance(arg, str):
        return arg
    return "".join(part if isinstance(part, str) else f"<{part.ref}>" for part in arg.parts)


def quote_posix(arg: str) -> str:
    return shlex.quote(arg)


def quote_windows(arg: str) -> str:
    """Quote one argument so that ``CommandLineToArgvW`` gives it back unchanged.

    Backslashes are literal unless they come before a ``"``: then they are doubled, and the
    quote is written ``\\"``. Backslashes at the end of a quoted argument are doubled too.
    """
    if arg and not any(c in _WINDOWS_SPECIAL for c in arg):
        return arg
    out: list[str] = ['"']
    backslashes = 0
    for char in arg:
        if char == "\\":
            backslashes += 1
            continue
        if char == '"':
            out.append("\\" * (2 * backslashes + 1) + '"')
        else:
            out.append("\\" * backslashes + char)
        backslashes = 0
    out.append("\\" * (2 * backslashes) + '"')
    return "".join(out)


def command_line(program: str, argv: Sequence[PlanArg], shell: Shell) -> str:
    """One step as a command line: the program and its arguments, quoted for ``shell``."""
    quote = quote_posix if shell == "posix" else quote_windows
    return " ".join(quote(display_arg(a)) for a in [program, *argv])
