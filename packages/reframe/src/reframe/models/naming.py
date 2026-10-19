"""Output naming: the options, and the result of naming one file.

The options (:class:`NamingOptions`) are a document model: a preset can override them
(``JobTemplate.naming``), and one job can use a manual name or its own template
(``JobSettings.output.naming``).

The result models (:class:`NameResult` and the models it holds) are runtime models: what
:func:`reframe.naming.resolve_output_name` returns, what the naming preview of the UI shows, and
what ``reframe name`` prints. They are never stored.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import Field

from reframe.models.base import DocumentModel, NonNegativeInt, ReframeModel
from reframe.models.issues import ValidationIssue
from reframe.models.job import NameSource

__all__ = [
    "MediaKind",
    "Mp4Extension",
    "NameCandidate",
    "NameKind",
    "NameResult",
    "NameSpan",
    "NamingOptions",
    "NamingVariable",
    "OutputFolderMode",
    "ParsedName",
    "TemplateKind",
    "VariableGroup",
    "VariableKind",
    "WordSeparator",
]

WordSeparator = Literal["keep", "space", "dot", "underscore"]
Mp4Extension = Literal["mp4", "m4v", "auto"]
OutputFolderMode = Literal["fixed", "same_as_source"]


class NamingOptions(DocumentModel):
    """The naming options, with their defaults."""

    movie_template: str = "{main_title}"
    episode_template: str = "{main_title}"
    """Used when a season and episode are recognised."""
    name_source: NameSource = "auto"
    word_separator: WordSeparator = "keep"
    """Applies to text that comes from the name."""
    title_case: bool = False
    replace_underscores: bool = False
    remove_punctuation: bool = False
    """Remove dashes, periods and commas (HandBrake)."""
    mp4_extension: Mp4Extension = "mp4"
    """``auto``: ``.m4v`` with AC-3 passthru, chapters or 3GPP subtitles."""
    output_folder_mode: OutputFolderMode = "same_as_source"
    output_folder: Path | None = None
    """The fixed output folder (``output_folder_mode="fixed"``)."""


VariableGroup = Literal["handbrake", "name", "media"]
"""``handbrake``: the HandBrake variables. ``name``: parsed from the name source.
``media``: the output media, from the job settings."""
VariableKind = Literal["text", "number", "date"]
"""How a format spec applies: text (``:upper``, ``:lower``, ``:title``), a Python number
format (``:02``) or a ``strftime`` format (``:%d.%m.%Y``)."""


class NamingVariable(ReframeModel):
    """One template variable, for the naming editor (autocomplete, chips) and the docs."""

    name: str
    """Without braces: ``main_title``, ``creation-date``."""
    group: VariableGroup
    kind: VariableKind
    description: str


NameKind = Literal["file", "folder"]
"""Which candidate a name was parsed from: the file name or its folder name."""
MediaKind = Literal["movie", "episode"]
"""``episode`` when a season, an episode or an air date is recognised."""
TemplateKind = Literal["movie", "episode", "manual"]
"""Which template made the name: the movie or episode template (or the job's own template),
or the job's manual name."""


class NameSpan(ReframeModel):
    """One recognised part of a name, with its position (for the coloured spans of the
    naming editor). ``text`` is ``candidate.text[start:end]``."""

    field: str
    """The ``ParsedName`` field the part belongs to, or a guessit property name for other
    release tags."""
    start: NonNegativeInt
    end: NonNegativeInt
    text: str


class ParsedName(ReframeModel):
    """The name parts of a file. Text keeps its original spelling and separators; ``None``
    means not recognised."""

    kind: MediaKind = "movie"
    main_title: str | None = None
    """The leading part of the name, cut at the first release tag. For an episode, the
    episode code and title stay (and a year between the show name and the code)."""
    name: str | None = None
    """Movie title or show name only."""
    sub_title: str | None = None
    """Episode title."""
    season: NonNegativeInt | None = None
    episode: NonNegativeInt | None = None
    """The first episode number (an absolute number when there is no season)."""
    episodes: list[NonNegativeInt] = Field(default_factory=list)
    """Every episode number of a multi-episode code (``S03E02E03`` → ``[2, 3]``)."""
    episode_code: str | None = None
    """As written in the name: ``S03E02``, ``S03E02E03``, ``1x01``, ``E1071``, ``001``."""
    year: NonNegativeInt | None = None
    edition: str | None = None
    source_type: str | None = None
    """``BluRay``, ``UHD.BluRay``, ``WEB-DL``, ``WEBRip``… as written."""
    release_group: str | None = None
    resolution: str | None = None
    """The resolution written in the name (``2160p``); not the output resolution."""
    separator: str | None = None
    """The word separator of the name (`` ``, ``.``, ``_`` or ``-``); ``None`` if none."""


class NameCandidate(ReframeModel):
    """The file name or the folder name, parsed and scored."""

    kind: NameKind
    text: str
    """What was parsed: the file name without its extension, or the folder name."""
    path: Path
    """The file, or the folder."""
    score: int
    """+1 for each recognised field, +2 when the title has word separators."""
    recognised: list[str] = Field(default_factory=list)
    """The scored fields found."""
    word_separators: bool = False
    """The title has word separators (``Hacksaw.Ridge``, not ``hacksawridge``)."""
    fields: ParsedName = Field(default_factory=ParsedName)
    spans: list[NameSpan] = Field(default_factory=list)


class NameResult(ReframeModel):
    """The output name of one source file (:func:`reframe.naming.resolve_output_name`)."""

    source: NameKind
    """The chosen name source."""
    reason: str
    """Why, for example ``Folder name: 8 fields recognised, title with word separators
    (10 points); file name: 3 fields recognised (3 points)``."""
    season_pack: bool = False
    """The file's folder holds several episode files."""
    candidates: list[NameCandidate] = Field(default_factory=list)
    """The file name first, then the folder name (when there is a usable folder)."""
    skipped_folders: list[str] = Field(default_factory=list)
    """Generic folders (``Season 03``, ``BDMV``…) skipped to find the folder name."""
    fields: ParsedName = Field(default_factory=ParsedName)
    """The fields used for the name: the chosen candidate's, plus folder fields for a season
    pack, plus the job's per-file overrides."""
    template: str
    """The template that made the name (or the manual name)."""
    template_kind: TemplateKind
    relative_path: str
    """The rendered name, relative to the output folder: subfolders separated by ``/``, and
    the extension (``The.Sopranos/Season 03/The.Sopranos.S03E02.Proshai.Livushka.mkv``)."""
    path: Path | None = None
    """The full output path, when the output folder is known."""
    extension: str
    """Without the dot: ``mkv``, ``mp4``, ``m4v``, ``webm``."""
    variables: dict[str, str] = Field(default_factory=dict)
    """Every variable's value for this file (default format), for the variable chips."""
    notes: list[str] = Field(default_factory=list)
    """What naming changed: skipped folders, merged fields, replaced characters, shortened
    parts, fallbacks."""
    issues: list[ValidationIssue] = Field(default_factory=list)
