"""``display`` quoting (POSIX and Windows), tested on every OS."""

from __future__ import annotations

import json
import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from hypothesis import given
from hypothesis import strategies as st

from reframe.command import command_line, quote_posix, quote_windows, quoting
from reframe.models import ArgTemplate, PlanArg, ValueRef


def split_windows(line: str) -> list[str]:
    """``CommandLineToArgvW`` / MS C runtime argument splitting (the rules of
    "Parsing C command-line arguments", Microsoft Learn), for the round trip."""
    args: list[str] = []
    current: list[str] = []
    in_quotes = False
    have_arg = False
    i = 0
    while i < len(line):
        char = line[i]
        if char == "\\":
            j = i
            while j < len(line) and line[j] == "\\":
                j += 1
            count = j - i
            if j < len(line) and line[j] == '"':
                current.append("\\" * (count // 2))
                if count % 2:
                    current.append('"')
                    i = j + 1
                else:
                    i = j
                have_arg = True
                continue
            current.append("\\" * count)
            have_arg = True
            i = j
            continue
        if char == '"':
            if in_quotes and i + 1 < len(line) and line[i + 1] == '"':
                current.append('"')
                i += 2
                continue
            in_quotes = not in_quotes
            have_arg = True
            i += 1
            continue
        if char in " \t" and not in_quotes:
            if have_arg:
                args.append("".join(current))
                current, have_arg = [], False
            i += 1
            continue
        current.append(char)
        have_arg = True
        i += 1
    if have_arg:
        args.append("".join(current))
    return args


@pytest.mark.parametrize(
    ("arg", "quoted"),
    [
        ("-map", "-map"),
        ("0:t?", "0:t?"),
        ("", '""'),
        ("with space", '"with space"'),
        ('say "hi"', '"say \\"hi\\""'),
        ("C:\\path with space\\", '"C:\\path with space\\\\"'),
        ("C:\\no_space\\", "C:\\no_space\\"),
        ('a\\\\"b', '"a\\\\\\\\\\"b"'),
        ("measured_I=<a0.input_i>", '"measured_I=<a0.input_i>"'),
        ("x&y", '"x&y"'),
        ("100%", '"100%"'),
        ("caret^", '"caret^"'),
        ("(group)", '"(group)"'),
        ("Director's", "Director's"),
    ],
)
def test_quote_windows(arg: str, quoted: str) -> None:
    assert quote_windows(arg) == quoted
    assert split_windows(quoted) == [arg]


@given(
    st.lists(st.text(alphabet=st.characters(exclude_characters="\x00"), max_size=20), max_size=6)
)
def test_windows_quoting_round_trips(args: list[str]) -> None:
    assert split_windows(" ".join(quote_windows(a) for a in args)) == args


@given(
    st.lists(st.text(alphabet=st.characters(exclude_characters="\x00"), max_size=20), max_size=6)
)
def test_posix_quoting_round_trips(args: list[str]) -> None:
    assert shlex.split(" ".join(quote_posix(a) for a in args)) == args


def test_command_line_shows_measured_values() -> None:
    template = ArgTemplate(parts=["loudnorm=measured_I=", ValueRef(ref="a0.input_i"), ":x=1"])
    argv: list[PlanArg] = ["-filter:a:0", template, "-f", "null", "-"]
    assert command_line("ffmpeg", argv, "posix") == (
        "ffmpeg -filter:a:0 'loudnorm=measured_I=<a0.input_i>:x=1' -f null -"
    )
    assert command_line("C:\\Program Files\\ffmpeg.exe", argv, "windows") == (
        '"C:\\Program Files\\ffmpeg.exe" -filter:a:0 "loudnorm=measured_I=<a0.input_i>:x=1" '
        "-f null -"
    )


#: Arguments that the shells read differently (fish: ``\\`` and ``\'`` inside single quotes;
#: zsh: ``=word``; all: ``$``, globs, ``~``, ``{,}``, ``#``, ``;``, ``&``, newline).
AWKWARD = [
    "",
    " ",
    "plain",
    "it's",
    "C:\\",
    "C:\\path\\",
    "a\\\\b",
    "a\\'b",
    "\\",
    "'",
    "''",
    '"',
    "$HOME",
    "${x}",
    "*",
    "?",
    "[ab]",
    "~",
    "~user",
    "{a,b}",
    "%self",
    "100%",
    "=ls",
    "a=b",
    "#c",
    ";",
    "&",
    "|",
    "a b",
    "line\nbreak",
    "tab\there",
    "`x`",
    "(x)",
    "!x",
    "Árvíz ❤",
    "subtitles=filename='C\\:/x.srt'",
    "-",
]


@pytest.mark.parametrize("shell", ["bash", "zsh", "fish", "sh"])
def test_posix_display_pastes_into_bash_zsh_and_fish(shell: str, tmp_path: Path) -> None:
    """A POSIX display with ``'`` or ``\\`` did not paste into fish (inside single
    quotes fish reads ``\\\\`` and ``\\'`` as escapes)."""
    program = shutil.which(shell)
    if program is None:
        pytest.skip(f"{shell} is not installed")
    script = tmp_path / "argv.py"
    script.write_text("import json, sys\nprint(json.dumps(sys.argv[1:]))\n", encoding="utf-8")
    line = command_line(sys.executable, [str(script), *AWKWARD], "posix")
    proc = subprocess.run([program, "-c", line], capture_output=True, text=True, check=True,
                          env={**os.environ, "HOME": "/home/x"}, timeout=30)  # fmt: skip
    assert json.loads(proc.stdout) == AWKWARD


def test_default_shell_follows_the_os(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(quoting, "os", SimpleNamespace(name="nt"))
    assert quoting.default_shell() == "windows"
    monkeypatch.setattr(quoting, "os", SimpleNamespace(name="posix"))
    assert quoting.default_shell() == "posix"
