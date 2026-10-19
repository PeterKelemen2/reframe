"""Safe file names. Pure: no file-system access.

Windows rules apply on every OS, because files move between systems. Each path part is at most
255 bytes of UTF-8, the size ``os.fsencode`` writes once the text has no surrogates. The file
part keeps room for the ``.part`` suffix that the queue inserts while it writes, so the name
still fits after the rename. The limit holds after every change, including the ``_`` that a
reserved name gets.
"""

from __future__ import annotations

from dataclasses import dataclass

from reframe.models.text import UNDECODABLE_REPLACEMENT, replace_undecodable

__all__ = [
    "MAX_PART_BYTES",
    "PARTIAL_SUFFIX",
    "REPLACEMENTS",
    "RESERVED_NAMES",
    "UNDECODABLE_NOTE",
    "UNDECODABLE_REPLACEMENT",
    "Piece",
    "is_reserved",
    "replace_forbidden",
    "replace_undecodable",
    "sanitize_segments",
]

MAX_PART_BYTES = 255
#: Inserted before the extension of a partial output file (``<name>.part.<ext>``).
PARTIAL_SUFFIX = ".part"
#: Characters Windows does not allow in a file name, and what replaces them.
REPLACEMENTS = {
    ":": "-",
    "/": "-",
    "\\": "-",
    "|": "-",
    '"': "'",
    "<": "",
    ">": "",
    "?": "",
    "*": "",
}
RESERVED_NAMES = frozenset(
    {"CON", "PRN", "AUX", "NUL"}
    | {f"{device}{n}" for device in ("COM", "LPT") for n in "0123456789¹²³"}
)
#: Template variables shortened (in this order) when a part is too long.
SHORTEN_ORDER = ("sub_title", "main_title")
_UNDECODABLE_CHANGE = f"bytes that are not UTF-8 → '{UNDECODABLE_REPLACEMENT}'"
#: The note of a name in which bytes that are not UTF-8 were replaced.
UNDECODABLE_NOTE = (
    f"Replaced bytes that are not UTF-8 with '{UNDECODABLE_REPLACEMENT}' (such a name cannot "
    "be written on Windows or in JSON)."
)


@dataclass(frozen=True, slots=True)
class Piece:
    """A piece of a rendered path part: literal template text (``var`` ``None``) or the
    value of a variable."""

    text: str
    var: str | None = None


def replace_forbidden(text: str) -> tuple[str, list[str]]:
    """``text`` with the Windows-forbidden characters and the bytes that are not UTF-8
    replaced, and what was replaced (``"':' → '-'"``, in order of first appearance)."""
    changes: list[str] = []
    cleaned = replace_undecodable(text)
    if cleaned != text:
        text = cleaned
        changes.append(_UNDECODABLE_CHANGE)
    if ": " in text:
        text = text.replace(": ", " - ")
        changes.append("':' → '-'")
    out: list[str] = []
    for char in text:
        if char in REPLACEMENTS:
            replacement = REPLACEMENTS[char]
            change = f"'{char}' → '{replacement}'" if replacement else f"'{char}' removed"
        elif ord(char) < 32:
            replacement = ""
            change = "control characters removed"
        else:
            out.append(char)
            continue
        out.append(replacement)
        if change not in changes:
            changes.append(change)
    return "".join(out), changes


def is_reserved(name: str) -> bool:
    """A Windows device name, with or without an extension (``nul``, ``CON.mkv``)."""
    base = name.split(".", 1)[0].rstrip(" ")
    return base.upper() in RESERVED_NAMES


def _size(text: str) -> int:
    return len(text.encode("utf-8"))


def _cut(text: str, limit: int) -> str:
    """The longest prefix of ``text`` that fits in ``limit`` UTF-8 bytes."""
    return text.encode("utf-8")[: max(limit, 0)].decode("utf-8", errors="ignore")


def _tidy(text: str) -> str:
    return text.lstrip(" ").rstrip(". ")


def _join(pieces: list[Piece]) -> str:
    return _tidy("".join(piece.text for piece in pieces))


def _shorten(pieces: list[Piece], limit: int) -> tuple[list[Piece], list[str]]:
    shortened: list[str] = []
    for var in SHORTEN_ORDER:
        for index in reversed([i for i, piece in enumerate(pieces) if piece.var == var]):
            if _size(_join(pieces)) <= limit:
                return pieces, shortened
            # Cut by the excess of the untidied text: the piece may hold the trailing dots
            # that the tidied text does not count.
            excess = _size("".join(piece.text for piece in pieces)) - limit
            piece = pieces[index]
            text = _cut(piece.text, _size(piece.text) - excess).rstrip(" ._-")
            pieces = [*pieces[:index], Piece(text, var), *pieces[index + 1 :]]
            if var not in shortened:
                shortened.append(var)
    return pieces, shortened


def _fit(text: str, limit: int) -> str:
    return _tidy(_cut(text, limit)) if _size(text) > limit else text


def _unreserve(text: str, limit: int) -> str:
    """A reserved name with a ``_`` after the device name (``CON.x`` → ``CON_.x``), cut to
    ``limit`` bytes again: the ``_`` comes after the cut. The cut keeps ``CON_``, so the
    result is never reserved."""
    base, dot, rest = text.partition(".")
    return _fit(f"{base.rstrip(' ')}_{dot}{rest}", limit)


def sanitize_segments(
    segments: list[list[Piece]], *, extension: str, fallback: str
) -> tuple[list[str], list[str]]:
    """Make the rendered path parts safe. The last segment is the file name; ``extension``
    (without the dot) is added to it. ``fallback`` is ``{file_name}``.

    Returns the path parts and the notes of what was changed.
    """
    notes: list[str] = []
    replaced: list[str] = []
    parts: list[str] = []
    suffix = f".{extension}" if extension else ""
    last = len(segments) - 1
    for index, segment in enumerate(segments):
        is_file = index == last
        limit = MAX_PART_BYTES - (_size(PARTIAL_SUFFIX) + _size(suffix) if is_file else 0)
        pieces: list[Piece] = []
        for piece in segment:
            text, changes = replace_forbidden(piece.text)
            replaced.extend(change for change in changes if change not in replaced)
            pieces.append(Piece(text, piece.var))
        raw = "".join(piece.text for piece in pieces).strip(" ")
        text = _join(pieces)
        if raw.endswith("."):
            notes.append(f"Removed trailing dots from '{raw}'.")
        if _size(text) > limit:
            pieces, shortened = _shorten(pieces, limit)
            text = _join(pieces)
            for var in shortened:
                notes.append(f"Shortened {{{var}}} so that '{text}' fits in {limit} bytes.")
            if _size(text) > limit:
                text = _fit(text, limit)
                notes.append(f"Cut a path part to {limit} bytes: '{text}'.")
        if text and is_reserved(text):
            fixed = _unreserve(text, limit)
            notes.append(f"'{text}' is a reserved name on Windows: renamed to '{fixed}'.")
            text = fixed
        if not text:
            if not is_file:
                notes.append("Dropped an empty folder level.")
                continue
            text, changes = replace_forbidden(fallback)
            replaced.extend(change for change in changes if change not in replaced)
            text = _fit(_tidy(text), limit)
            if is_reserved(text):
                text = _unreserve(text, limit)
            text = text or "output"
            notes.append(f"The file name was empty: used the source file name '{text}'.")
        parts.append(text + suffix if is_file else text)
    windows = [change for change in replaced if change != _UNDECODABLE_CHANGE]
    if windows:
        notes.insert(
            0, "Replaced characters that Windows does not allow: " + ", ".join(windows) + "."
        )
    if _UNDECODABLE_CHANGE in replaced:
        notes.insert(0, UNDECODABLE_NOTE)
    return parts, notes
