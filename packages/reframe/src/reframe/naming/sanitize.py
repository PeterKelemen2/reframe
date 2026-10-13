"""Safe file names (03 §Output naming → Safe file names; C-16).

Windows rules apply on every OS, because files move between systems:

- The characters ``< > : " / \\ | ? *`` and control characters are replaced (table
  :data:`REPLACEMENTS`; ``": "`` becomes ``" - "``, so ``Mission: Impossible`` reads
  ``Mission - Impossible``).
- Reserved device names (``CON``, ``PRN``, ``AUX``, ``NUL``, ``COM0`` to ``COM9``,
  ``LPT0`` to ``LPT9``, also with an extension: ``CON.mkv``) get a ``_`` (``CON_.mkv``).
- Trailing dots and spaces are removed (and leading spaces).
- Each path part is at most 255 bytes (UTF-8). The file part keeps room for the ``.part``
  that the queue inserts while it writes (``<name>.part.<ext>``, 03 §Queue). ``{sub_title}`` is
  shortened first, then ``{main_title}``; then the part is cut.
- An empty file part falls back to ``{file_name}``; an empty folder part is dropped.

Pure: no file-system access.
"""

from __future__ import annotations

from dataclasses import dataclass

__all__ = [
    "MAX_PART_BYTES",
    "PARTIAL_SUFFIX",
    "REPLACEMENTS",
    "RESERVED_NAMES",
    "Piece",
    "is_reserved",
    "replace_forbidden",
    "sanitize_segments",
]

MAX_PART_BYTES = 255
#: The queue writes ``<name>.part.<ext>`` and renames it when the job succeeds.
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


@dataclass(frozen=True, slots=True)
class Piece:
    """A piece of a rendered path part: literal template text (``var`` ``None``) or the
    value of a variable."""

    text: str
    var: str | None = None


def replace_forbidden(text: str) -> tuple[str, list[str]]:
    """``text`` with the Windows-forbidden characters replaced, and what was replaced
    (``"':' → '-'"``, in order of first appearance)."""
    changes: list[str] = []
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
    """Leading spaces, trailing dots and spaces removed."""
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
            # that the tidied text no longer counts.
            excess = _size("".join(piece.text for piece in pieces)) - limit
            piece = pieces[index]
            text = _cut(piece.text, _size(piece.text) - excess).rstrip(" ._-")
            pieces = [*pieces[:index], Piece(text, var), *pieces[index + 1 :]]
            if var not in shortened:
                shortened.append(var)
    return pieces, shortened


def _fit(text: str, limit: int) -> str:
    return _tidy(_cut(text, limit)) if _size(text) > limit else text


def sanitize_segments(
    segments: list[list[Piece]], *, extension: str, fallback: str
) -> tuple[list[str], list[str]]:
    """Make the rendered path parts safe. The last segment is the file name; ``extension``
    (without the dot) is added to it. ``fallback`` is ``{file_name}``.

    Returns the path parts and the notes (what was changed, for :class:`NameResult`).
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
            base, dot, rest = text.partition(".")
            fixed = f"{base.rstrip(' ')}_{dot}{rest}"
            notes.append(f"'{text}' is a reserved name on Windows: renamed to '{fixed}'.")
            text = fixed
        if not text:
            if not is_file:
                notes.append("Dropped an empty folder level.")
                continue
            text = _fit(_tidy(replace_forbidden(fallback)[0]), limit)
            if is_reserved(text):
                base, dot, rest = text.partition(".")
                text = f"{base.rstrip(' ')}_{dot}{rest}"
            text = text or "output"
            notes.append(f"The file name was empty: used the source file name '{text}'.")
        parts.append(text + suffix if is_file else text)
    if replaced:
        notes.insert(
            0, "Replaced characters that Windows does not allow: " + ", ".join(replaced) + "."
        )
    return parts, notes
