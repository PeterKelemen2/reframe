"""Shell quoting for the command preview (:attr:`reframe.models.EncodePlan.display`).

The runner never uses a shell, so ``display`` only has to paste into a terminal: ``posix`` for
bash, zsh, fish and ``sh``, ``windows`` for ``cmd.exe``. The windows style is not for
PowerShell, which reads ``,`` and ``;`` outside quotes.
"""

from __future__ import annotations

import os
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
    """The quoting style of this OS."""
    return "windows" if os.name == "nt" else "posix"


def display_arg(arg: PlanArg) -> str:
    """The text of an argument, with measured values as ``<id.key>``."""
    if isinstance(arg, str):
        return arg
    return "".join(part if isinstance(part, str) else f"<{part.ref}>" for part in arg.parts)


#: Characters an argument may have and stay bare in bash, zsh and fish.
_POSIX_SAFE = frozenset("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_@%+=:,./-")


def quote_posix(arg: str) -> str:
    """Quote one argument for bash, zsh and fish. A leading ``=`` or ``%`` is quoted too (zsh
    expands ``=ls``, fish ``%self``). Not :func:`shlex.quote`, whose output fish and zsh read
    differently."""
    if arg and arg[0] not in "=%" and all(c in _POSIX_SAFE for c in arg):
        return arg
    out: list[str] = []
    run: list[str] = []
    for char in arg:
        if char in "'\\":
            if run:
                out.append("'" + "".join(run) + "'")
                run = []
            out.append('"\'"' if char == "'" else '"\\\\"')
        else:
            run.append(char)
    if run or not out:
        out.append("'" + "".join(run) + "'")
    return "".join(out)


def quote_windows(arg: str) -> str:
    """Quote one argument so that ``CommandLineToArgvW`` gives it back unchanged.

    Backslashes are literal unless they come before a ``"``: then they are doubled, and the
    quote is written ``\\"``. Backslashes at the end of a quoted argument are doubled too.
    ``cmd.exe`` expands ``%name%`` even inside quotes; quoting does not prevent that.
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
