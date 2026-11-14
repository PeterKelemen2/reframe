"""Stamp the core's ``__version__`` into every other version field, or check that they agree.

``reframe.__version__`` (PEP 440) is the one source. The npm packages, the Tauri config and the
Cargo package take its SemVer spelling (``1.1.0rc1`` → ``1.1.0-rc.1``); ``reframe-server``
reads the core's file itself. A file is written only when a field in it changes, and each edit
replaces one value in place, so the rest of the file keeps its bytes. The script uses only the
standard library, so it runs before ``uv sync``.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import tomllib
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
CORE_INIT = Path("packages/reframe/src/reframe/__init__.py")

# The forms the SemVer spelling can keep in order: X.Y.Z, X.Y.Z{a,b,rc}N, X.Y.Z.devN.
_PEP440_RE = re.compile(r"^(\d+)\.(\d+)\.(\d+)(?:(a|b|rc)(\d+)|\.dev(\d+))?$")
_PRE_RELEASE = {"a": "alpha", "b": "beta", "rc": "rc"}
_CORE_VERSION_RE = re.compile(r'^__version__ = "([^"]*)"', re.MULTILINE)


class StampError(Exception):
    """A version the other tools cannot take, or a file whose field is not where it should be."""


def to_semver(version: str) -> str:
    """The SemVer spelling of a PEP 440 version, for npm, Tauri and Cargo."""
    match = _PEP440_RE.match(version)
    if match is None:
        raise StampError(
            f"{version!r} is not a version this script can stamp: use X.Y.Z, X.Y.ZaN, X.Y.ZbN, "
            "X.Y.ZrcN or X.Y.Z.devN (PEP 440, normalized, no leading zeros)"
        )
    major, minor, patch, pre, pre_number, dev = match.groups()
    numbers = (major, minor, patch, pre_number, dev)
    if any(n is not None and len(n) > 1 and n.startswith("0") for n in numbers):
        raise StampError(f"{version!r} has a number with a leading zero, which SemVer refuses")
    core = f"{major}.{minor}.{patch}"
    if pre is not None:
        return f"{core}-{_PRE_RELEASE[pre]}.{pre_number}"
    if dev is not None:
        return f"{core}-dev.{dev}"
    return core


def read_core_version(root: Path) -> str:
    match = _CORE_VERSION_RE.search(_read(root / CORE_INIT))
    if match is None:
        raise StampError(f'{CORE_INIT}: no line `__version__ = "..."`')
    return match.group(1)


def write_core_version(root: Path, version: str) -> None:
    to_semver(version)
    path = root / CORE_INIT
    text = _read(path)
    new, count = _CORE_VERSION_RE.subn(f'__version__ = "{version}"', text, count=1)
    if count != 1:
        raise StampError(f'{CORE_INIT}: no line `__version__ = "..."`')
    if new != text:
        path.write_bytes(new.encode("utf-8"))


def _read(path: Path) -> str:
    # Bytes, not text mode: a CRLF checkout keeps its line ends when a field is written.
    return path.read_bytes().decode("utf-8")


Getter = Callable[[Any], Any]
Setter = Callable[[Any, str], None]


@dataclass(frozen=True)
class Field:
    """One version value in a JSON or TOML file."""

    path: Path
    name: str
    get: Getter
    put: Setter

    @property
    def label(self) -> str:
        return f"{self.path.as_posix()}: {self.name}"


def _parse(path: Path, text: str) -> Any:
    if path.suffix == ".json":
        return json.loads(text)
    return tomllib.loads(text)


def _key(*keys: str) -> tuple[Getter, Setter]:
    def get(doc: Any) -> Any:
        for key in keys:
            doc = doc[key]
        return doc

    def set_(doc: Any, value: str) -> None:
        for key in keys[:-1]:
            doc = doc[key]
        doc[keys[-1]] = value

    return get, set_


def _cargo_lock_package(name: str) -> tuple[Getter, Setter]:
    def entry(doc: Any) -> dict[str, Any]:
        found = [p for p in doc["package"] if p["name"] == name and "source" not in p]
        if len(found) != 1:
            raise KeyError(name)
        package: dict[str, Any] = found[0]
        return package

    def set_(doc: Any, value: str) -> None:
        entry(doc)["version"] = value

    return lambda doc: entry(doc)["version"], set_


def _field(path: str, name: str, accessors: tuple[Getter, Setter]) -> Field:
    return Field(Path(path), name, accessors[0], accessors[1])


FIELDS = (
    _field("frontend/package.json", "version", _key("version")),
    _field("frontend/package-lock.json", "version", _key("version")),
    _field("frontend/package-lock.json", 'packages[""].version', _key("packages", "", "version")),
    _field("desktop/package.json", "version", _key("version")),
    _field("desktop/package-lock.json", "version", _key("version")),
    _field("desktop/package-lock.json", 'packages[""].version', _key("packages", "", "version")),
    _field("desktop/src-tauri/tauri.conf.json", "version", _key("version")),
    _field("desktop/src-tauri/Cargo.toml", "package.version", _key("package", "version")),
    _field(
        "desktop/src-tauri/Cargo.lock",
        'package "reframe-desktop" version',
        _cargo_lock_package("reframe-desktop"),
    ),
)


def read_field(root: Path, field: Field) -> Any:
    text = _read(root / field.path)
    try:
        return field.get(_parse(field.path, text))
    except (KeyError, IndexError, TypeError) as error:
        raise StampError(f"{field.label}: not found") from error


def _replace(field: Field, text: str, value: str) -> str:
    doc = _parse(field.path, text)
    old = field.get(doc)
    if old == value:
        return text
    field.put(doc, value)
    # Of the places where the old value is written as a version, the one whose edit parses to
    # the expected document is the field: other packages may have the same version.
    pattern = re.compile(r'(\bversion"?\s*[:=]\s*")' + re.escape(str(old)) + '"')
    for match in pattern.finditer(text):
        candidate = f'{text[: match.start()]}{match.group(1)}{value}"{text[match.end() :]}'
        if _parse(field.path, candidate) == doc:
            return candidate
    raise StampError(f"{field.label}: cannot find where {old!r} is written")


def stamp(root: Path) -> str:
    """Write the core's version into every field, and return it."""
    version = read_core_version(root)
    semver = to_semver(version)
    for path in dict.fromkeys(field.path for field in FIELDS):
        file = root / path
        text = _read(file)
        new = text
        for field in FIELDS:
            if field.path == path:
                try:
                    new = _replace(field, new, semver)
                except (KeyError, IndexError, TypeError) as error:
                    raise StampError(f"{field.label}: not found") from error
        if new != text:
            file.write_bytes(new.encode("utf-8"))
    return version


def mismatches(root: Path) -> tuple[str, list[str]]:
    """The core's version, and one line for each field that differs from it."""
    version = read_core_version(root)
    semver = to_semver(version)
    problems = []
    for field in FIELDS:
        found = read_field(root, field)
        if found != semver:
            problems.append(f"{field.label} is {found!r}, expected {semver!r}")
    return version, problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    action = parser.add_mutually_exclusive_group()
    action.add_argument(
        "--check",
        action="store_true",
        help="change nothing; print the version, or name each field that differs and exit 1",
    )
    action.add_argument(
        "--set", metavar="VERSION", help="write VERSION (PEP 440) as __version__, then stamp"
    )
    action.add_argument(
        "--print-semver", action="store_true", help="print the SemVer spelling of the version"
    )
    parser.add_argument("--root", type=Path, default=REPO_ROOT, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    root: Path = args.root

    try:
        if args.check:
            version, problems = mismatches(root)
            if problems:
                print(
                    f"These version fields differ from __version__ {version!r} "
                    "(run scripts/stamp-version.py):",
                    file=sys.stderr,
                )
                for problem in problems:
                    print(f"  {problem}", file=sys.stderr)
                return 1
            print(version)
        elif args.print_semver:
            print(to_semver(read_core_version(root)))
        else:
            if args.set is not None:
                write_core_version(root, args.set)
            print(stamp(root))
    except (StampError, OSError, ValueError) as error:
        print(f"stamp-version: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
