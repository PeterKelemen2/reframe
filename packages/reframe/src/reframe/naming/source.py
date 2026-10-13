"""The name source: the file name or its folder name (03 §Where the name comes from; C-16).

**Auto** (the default):

1. Skip generic folders (``Season 03``, ``S03``, ``Specials``, ``Extras``, ``Featurettes``,
   ``Disc 1``, ``CD1``, ``BDMV``, ``STREAM``, ``VIDEO_TS``) and look one level higher, at most
   two levels, never above the opened folder or media root.
2. If the folder holds several episode files (a season pack), the file name is the source,
   because only it has the episode number and title. The same holds when only the file name
   has an episode number (decision 0012: a folder that names a season, such as
   ``The.Sopranos.S03.1080p…``, or a show folder). The folder then fills the fields that the
   file name does not have (year, edition, source, group, season, and the show name).
3. Otherwise the candidate with the higher score wins: +1 for each recognised field (title,
   year, resolution, source, video codec, audio codec, HDR, edition, release group), +2 if
   the title has word separators. A tie goes to the file name.

**File name** / **Folder name**: forced (in the naming options, or per job).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from reframe.models.job import NameSource
from reframe.models.naming import NameCandidate, NameKind, ParsedName
from reframe.naming.clean import convert_separator
from reframe.naming.fs import NamingFs
from reframe.naming.parse import NameParse, parse_name

__all__ = [
    "DISC_FOLDERS",
    "MAX_SKIPPED_FOLDERS",
    "VIDEO_EXTENSIONS",
    "SourceChoice",
    "choose_source",
    "find_folder",
    "is_generic_folder",
    "split_extension",
]

#: Generic folder names (whole name, case-insensitive).
_GENERIC = re.compile(
    r"^(?:season[ ._-]*\d{1,4}|s\d{1,4}|specials?|extras?|featurettes?"
    r"|dis[ck][ ._-]*\d{1,2}|cd[ ._-]*\d{1,2}|bdmv|stream|video_ts)$",
    re.IGNORECASE,
)
#: Disc structure folders hold title files (``00001.m2ts``, ``VTS_01_1.VOB``), not episodes.
DISC_FOLDERS = frozenset({"bdmv", "stream", "video_ts"})
MAX_SKIPPED_FOLDERS = 2
#: Media file extensions: stripped from ``{file_name}``, counted as episode files.
VIDEO_EXTENSIONS = frozenset(
    {
        "3gp", "asf", "avi", "divx", "flv", "m2t", "m2ts", "m4v", "mkv", "mov", "mp4", "mpeg",
        "mpg", "mts", "mxf", "ogm", "ogv", "rm", "rmvb", "ts", "vob", "webm", "wmv", "y4m",
    }
)  # fmt: skip
#: Fields the folder fills in for the file name (season packs).
_MERGED = ("year", "edition", "source_type", "release_group", "resolution", "season")
_FIELD_LABELS = {
    "name": "name",
    "year": "year",
    "edition": "edition",
    "source_type": "source",
    "release_group": "release group",
    "resolution": "resolution",
    "season": "season",
}


def is_generic_folder(name: str) -> bool:
    return bool(_GENERIC.match(name.strip()))


def split_extension(file_name: str) -> tuple[str, str]:
    """``(stem, extension)``; the extension (lower case, no dot) only when it is a known media
    extension, so ``…REMUX-Kataklysm`` without an extension keeps its last part."""
    stem, dot, ext = file_name.rpartition(".")
    if dot and stem and ext.lower() in VIDEO_EXTENSIONS:
        return stem, ext.lower()
    return file_name, ""


def _within(path: Path, root: Path) -> bool:
    return path == root or root in path.parents


def find_folder(file: Path, root: Path | None) -> tuple[Path | None, list[str]]:
    """The folder candidate (after skipping generic folders) and the generic folder names
    passed. ``None`` when there is no usable folder name (also when the last folder looked
    at is still generic)."""
    folder = file.parent
    if root is not None and not _within(folder, root):
        root = None  # the file is not under the root: no limit
    skipped: list[str] = []
    while folder.name and is_generic_folder(folder.name):
        skipped.append(folder.name)
        parent = folder.parent
        if len(skipped) > MAX_SKIPPED_FOLDERS or folder == root or not parent.name:
            return None, skipped
        folder = parent
    if not folder.name:
        return None, skipped
    return folder, skipped


def _count_episode_files(folder: Path, fs: NamingFs) -> int | None:
    names = fs.list_files(folder)
    if names is None:
        return None
    count = 0
    for name in names:
        stem, ext = split_extension(name)
        if ext and parse_name(stem).has_episode:
            count += 1
    return count


@dataclass(slots=True)
class SourceChoice:
    """The chosen name source, the candidates and the merged fields."""

    kind: NameKind
    reason: str
    file_parse: NameParse
    folder_parse: NameParse | None
    folder: Path | None
    candidates: list[NameCandidate]
    fields: ParsedName
    """The chosen candidate's fields (merged with the folder's for a season pack)."""
    skipped: list[str] = field(default_factory=list)
    season_pack: bool = False
    notes: list[str] = field(default_factory=list)

    @property
    def text(self) -> str:
        """The chosen candidate's text (``{source}``)."""
        if self.kind == "folder" and self.folder_parse is not None:
            return self.folder_parse.text
        return self.file_parse.text

    @property
    def separator(self) -> str | None:
        if self.kind == "folder" and self.folder_parse is not None:
            return self.folder_parse.fields.separator
        return self.file_parse.fields.separator


def _candidate(kind: NameKind, parse: NameParse, path: Path) -> NameCandidate:
    return NameCandidate(
        kind=kind,
        text=parse.text,
        path=path,
        score=parse.score,
        recognised=list(parse.recognised),
        word_separators=parse.word_separators,
        fields=parse.fields.model_copy(deep=True),
        spans=list(parse.spans),
    )


def _describe(label: str, parse: NameParse) -> str:
    count = len(parse.recognised)
    fields = f"{count} field{'' if count == 1 else 's'} recognised"
    extra = ", title with word separators" if parse.word_separators else ""
    points = f"{parse.score} point{'' if parse.score == 1 else 's'}"
    return f"{label}: {fields}{extra} ({points})"


def merge_folder_fields(file: ParsedName, folder: ParsedName) -> tuple[ParsedName, list[str]]:
    """The file's fields, with the folder's for the fields the file does not have. Folder
    text gets the file's word separator. Returns the merged fields and what was filled."""
    merged = file.model_copy(deep=True)
    target = file.separator or folder.separator
    filled: list[str] = []
    for name in _MERGED:
        mine, theirs = getattr(merged, name), getattr(folder, name)
        if mine is None and theirs is not None:
            if name in ("edition", "source_type"):
                theirs = convert_separator(theirs, folder.separator, target)
            setattr(merged, name, theirs)
            filled.append(name)
    if merged.name is None and folder.name is not None:
        show = convert_separator(folder.name, folder.separator, target)
        merged.name = show
        joiner = " - " if target == " " else (target or " ")
        merged.main_title = f"{show}{joiner}{merged.main_title}" if merged.main_title else show
        filled.insert(0, "name")
    return merged, filled


def choose_source(
    file: Path,
    mode: NameSource,
    *,
    root: Path | None,
    fs: NamingFs,
    forced_by: str = "the naming options",
) -> SourceChoice:
    """Parse the file name and the folder name, and pick the name source."""
    stem, _ = split_extension(file.name)
    file_parse = parse_name(stem)
    folder, skipped = find_folder(file, root)
    folder_parse = parse_name(folder.name) if folder is not None else None
    candidates = [_candidate("file", file_parse, file)]
    if folder is not None and folder_parse is not None:
        candidates.append(_candidate("folder", folder_parse, folder))
    notes = [f"Skipped the generic folder '{name}'." for name in skipped]

    # Season packs (rule 2), also used to merge folder fields in the forced File mode.
    pack_reason: str | None = None
    if folder_parse is not None and file.parent.name.lower() not in DISC_FOLDERS:
        count = _count_episode_files(file.parent, fs)
        if count is not None and count >= 2:
            pack_reason = (
                f"Season pack: the folder holds {count} episode files, so the file name is "
                "used (only it has the episode number and title)"
            )
        elif file_parse.has_episode and not folder_parse.has_episode:
            code = file_parse.fields.episode_code or str(file_parse.fields.episode)
            pack_reason = f"Only the file name has an episode number ({code}), so it is used"

    def choice(kind: NameKind, reason: str, *, pack: bool = False) -> SourceChoice:
        fields = (folder_parse if kind == "folder" and folder_parse else file_parse).fields
        fields = fields.model_copy(deep=True)
        if kind == "file" and pack and folder_parse is not None:
            fields, filled = merge_folder_fields(fields, folder_parse.fields)
            if filled:
                labels = ", ".join(_FIELD_LABELS[name] for name in filled)
                notes.append(f"The folder name fills: {labels}.")
        return SourceChoice(
            kind=kind,
            reason=reason,
            file_parse=file_parse,
            folder_parse=folder_parse,
            folder=folder,
            candidates=candidates,
            fields=fields,
            skipped=skipped,
            season_pack=pack,
            notes=notes,
        )

    if folder_parse is None:
        why = "the folder is generic" if skipped else "there is no folder name"
        if mode == "folder":
            return choice("file", f"Folder name is set in {forced_by}, but {why}: file name")
        return choice("file", f"File name: {why}")
    if mode == "file":
        return choice("file", f"File name (set in {forced_by})", pack=pack_reason is not None)
    if mode == "folder":
        return choice("folder", f"Folder name (set in {forced_by})")
    if pack_reason is not None:
        return choice("file", pack_reason, pack=True)
    if folder_parse.score > file_parse.score:
        reason = f"{_describe('Folder name', folder_parse)}; {_describe('file name', file_parse)}"
        return choice("folder", reason)
    reason = f"{_describe('File name', file_parse)}; {_describe('folder name', folder_parse)}"
    if folder_parse.score == file_parse.score:
        reason += ". A tie goes to the file name"
    return choice("file", reason)
