"""Output naming options (03 §Output naming → Options; C-16).

The defaults live in Settings → Output; a preset can override them (``JobTemplate.naming``),
and one job can use a manual name (``JobSettings.output.naming``). C-16 adds the parse-result
models (name source, parsed fields) next to these.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from reframe.models.base import DocumentModel
from reframe.models.job import NameSource

__all__ = ["Mp4Extension", "NamingOptions", "OutputFolderMode", "WordSeparator"]

WordSeparator = Literal["keep", "space", "dot", "underscore"]
Mp4Extension = Literal["mp4", "m4v", "auto"]
OutputFolderMode = Literal["fixed", "same_as_source"]


class NamingOptions(DocumentModel):
    """The options table of 03 §Output naming, with its defaults."""

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
