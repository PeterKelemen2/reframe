"""Track metadata rules: a language that is not a known language or BCP 47 tag would be
written as ``und``, a track name template with a variable it does not have, a re-encoded
track whose name names the source's codec or layout, and several output tracks of one kind
marked default."""

from __future__ import annotations

import difflib
import re
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from types import MappingProxyType

from reframe import languages
from reframe.command.metadata import dispositions
from reframe.command.subtitles import written_subtitle_codec
from reframe.definitions import ContainerDef
from reframe.models.issues import Fix, ValidationIssue
from reframe.models.job import AudioOutputTrack, SubtitleOutputTrack, TrackMetadata
from reframe.models.text import shown
from reframe.naming.context import audio_channels_label
from reframe.naming.template import parse_template, template_variables
from reframe.naming.track_names import TRACK_NAME_VARIABLES, is_track_name_template
from reframe.probe.names import audio_name_codecs, codec_name, subtitle_display_name
from reframe.validation.common import add, error, fix, replace, warning
from reframe.validation.context import JobContext
from reframe.validation.registry import job_rule
from reframe.validation.tracks import (
    encoded_audio,
    subtitle_input,
    track_encoder,
    track_stream,
    written_channels,
    written_layout,
)


def metadata_blocks(
    ctx: JobContext, *, written_only: bool = False
) -> Iterator[tuple[str, TrackMetadata]]:
    """The metadata of each output track and its path; ``written_only`` skips burned-in
    subtitles, which have no track to write it to."""
    yield "video.metadata", ctx.job.video.metadata
    for index, audio in enumerate(ctx.job.audio):
        yield f"audio[{index}].metadata", audio.metadata
    for index, subtitle in enumerate(ctx.job.subtitles):
        if not (written_only and subtitle.action == "burn"):
            yield f"subtitles[{index}].metadata", subtitle.metadata


@job_rule("metadata", "metadata.language_invalid")
def track_languages(ctx: JobContext) -> Iterator[ValidationIssue]:
    for prefix, metadata in metadata_blocks(ctx):
        if metadata.language is None:
            continue
        problem = languages.validate(metadata.language)
        if problem is None:
            continue
        yield warning(
            "metadata.language_invalid",
            f"{prefix}.language",
            f"{problem} It would be written as 'und' (undetermined).",
            fix(
                "Keep the source language",
                replace(f"{prefix}.language", None),
            ),
        )


@job_rule("metadata", "metadata.nul_character")
def track_names(ctx: JobContext) -> Iterator[ValidationIssue]:
    """A track name is a process argument, which cannot hold a NUL character."""
    names = [(f"{prefix}.name", metadata.name) for prefix, metadata in metadata_blocks(ctx)]
    names += [
        (f"subtitles[{index}].source.name", track.source.name)
        for index, track in enumerate(ctx.job.subtitles)
        if not isinstance(track.source, int)
    ]
    for at, name in names:
        if name is not None and "\0" in name:
            yield error(
                "metadata.nul_character",
                at,
                "The track name has a NUL character, which FFmpeg cannot be given: the job "
                "would fail.",
                fix(
                    "Remove the NUL characters",
                    replace(at, name.replace("\0", "")),
                ),
            )


def _track_variable(name: str) -> str | None:
    """The track name variable that ``name`` is most likely a typo of."""
    lower = name.lower()
    if lower in TRACK_NAME_VARIABLES:
        return lower
    close = difflib.get_close_matches(lower, sorted(TRACK_NAME_VARIABLES), n=1, cutoff=0.75)
    return close[0] if close else None


@job_rule("metadata", "metadata.name_variable_unknown")
def track_name_variables(ctx: JobContext) -> Iterator[ValidationIssue]:
    """A track name with a variable that track names do not have is written as typed. A name
    with no track variable and nothing close to one is a title (``Signs {Karaoke}``)."""
    for prefix, metadata in metadata_blocks(ctx, written_only=True):
        name = metadata.name
        if name is None or ("{" not in name and "}" not in name):
            continue
        template = parse_template(name)
        if template.errors:
            continue
        found = list(template_variables(template.nodes))
        unknown = [var for var in found if var.name not in TRACK_NAME_VARIABLES]
        guesses = {var.name: _track_variable(var.name) for var in unknown}
        if not unknown or (len(unknown) == len(found) and not any(guesses.values())):
            continue
        listed = list(dict.fromkeys(f"{{{var.name}}}" for var in unknown))
        verb = (
            "is not a track name variable" if len(listed) == 1 else "are not track name variables"
        )
        message = (
            f"{' and '.join(listed)} {verb}, so the track name is written as typed, braces and all."
        )
        fixed, used = name, list[str]()
        for var in reversed(unknown):
            guess = guesses[var.name]
            if guess is not None:
                spec = f":{var.spec}" if var.spec is not None else ""
                fixed = f"{fixed[: var.start]}{{{guess}{spec}}}{fixed[var.end :]}"
                used.insert(0, f"{{{guess}}}")
        fixes: list[Fix] = []
        if len(used) == len(unknown):
            label = " and ".join(dict.fromkeys(used))
            message += f" Did you mean {label}?"
            fixes.append(fix(f"Use {label}", replace(f"{prefix}.name", fixed)))
        else:
            variables = ", ".join(f"{{{v}}}" for v in sorted(TRACK_NAME_VARIABLES))
            message += f" The variables of a track name are {variables}."
        yield warning("metadata.name_variable_unknown", f"{prefix}.name", message, *fixes)


#: ``5.1``, ``2.0``; not ``7.1.4`` or ``DD5.1``.
_CHANNELS = r"\d\.\d"
_BEFORE = r"(?<![\w\-:+./])"
_AFTER = r"(?![\w\-:+/]|\.\d)"


@dataclass(frozen=True, slots=True)
class _Written:
    """What an output track is written as, for the codec and layout words of its name."""

    codecs: Mapping[str, str | None]
    """Codec words of a name → the codec they name; the codec is ``codec`` when the word fits."""
    codec: str | None
    codec_label: str
    channels: int = 0
    """0: the name's layout words are not checked."""
    layouts: Mapping[str, int] = MappingProxyType({})
    """Layout words (``Stereo``) → their channel count."""
    numeric: str = ""
    """The written layout as ``N.M``, which replaces ``5.1``."""
    word: str = ""
    """The written layout as a word, which replaces ``Stereo``."""

    def describe(self) -> str:
        return f"{self.codec_label} {self.word}" if self.channels else self.codec_label


def _channel_count(token: str, written: _Written) -> int | None:
    if re.fullmatch(_CHANNELS, token):
        return int(token[0]) + int(token[2])
    return written.layouts.get(token)


def _restated(name: str, written: _Written) -> tuple[list[str], str] | None:
    """The codec and layout words of ``name`` that the written track contradicts, and ``name``
    with the first of each kind replaced by the written value and the others removed."""
    words = sorted(
        [*written.codecs, *(written.layouts if written.channels else ())], key=len, reverse=True
    )
    choices = [re.escape(word) for word in words]
    if written.channels:
        choices.append(_CHANNELS)
    if not choices:
        return None
    matches = list(re.finditer(f"{_BEFORE}(?:{'|'.join(choices)}){_AFTER}", name))

    def fits(token: str) -> tuple[bool, bool]:
        """(is a codec word, fits the written track)."""
        if token in written.codecs:
            return True, written.codecs[token] == written.codec
        return False, _channel_count(token, written) == written.channels

    done = {kind for kind, ok in map(fits, (m[0] for m in matches)) if ok}
    stale: list[str] = []
    pieces: list[str] = []
    last = 0
    for match in matches:
        token = match[0]
        codec, ok = fits(token)
        pieces.append(name[last : match.start()])
        last = match.end()
        if ok:
            pieces.append(token)
            continue
        stale.append(token)
        if codec not in done:
            done.add(codec)
            if codec:
                pieces.append(written.codec_label)
            else:
                pieces.append(written.numeric if re.fullmatch(_CHANNELS, token) else written.word)
    if not stale:
        return None
    pieces.append(name[last:])
    renamed = re.sub(r"\(\s*\)|\[\s*\]", "", "".join(pieces))
    return stale, re.sub(r"\s{2,}", " ", renamed).strip(" -\u2013·,/|+&")


def _audio_written(ctx: JobContext, track: AudioOutputTrack) -> _Written | None:
    """``None`` for a copied track, or one that other rules refuse."""
    encoder_id = track_encoder(ctx, track)
    stream = track_stream(ctx, track)
    encoder = ctx.definitions.audio_encoders.get(encoder_id) if encoder_id else None
    if encoder is None or stream is None:
        return None
    defs = ctx.definitions
    planned = encoded_audio(track, stream, encoder, defs)
    channels = written_channels(defs, planned)
    numeric = audio_channels_label(channels, planned.layout)
    word = (
        written_layout(defs, planned)
        if planned.mixdown is not None
        else next(
            (
                mixdown.label
                for mixdown in defs.mixdowns.values()
                if mixdown.channels == channels and mixdown.matrix_encoding is None
            ),
            numeric,
        )
    )
    return _Written(
        codecs=audio_name_codecs(),
        codec=encoder.codec,
        codec_label=codec_name(encoder.codec),
        channels=channels,
        layouts={mixdown.label: mixdown.channels for mixdown in defs.mixdowns.values()},
        numeric=numeric,
        word=word,
    )


def _subtitle_written(ctx: JobContext, track: SubtitleOutputTrack) -> _Written | None:
    """``None`` for a track whose format does not change."""
    found = subtitle_input(ctx, track)
    if track.action == "burn" or found is None or found.codec is None:
        return None
    written = written_subtitle_codec(track, found.codec, ctx.container)
    label = subtitle_display_name(written)
    if label is None or label == subtitle_display_name(found.codec):
        return None
    formats = {
        name
        for container in ctx.definitions.containers.values()
        for codec in [*container.subtitles.copy_codecs, *container.subtitles.encode]
        if codec != "*" and (name := subtitle_display_name(codec)) is not None
    }
    return _Written(codecs={name: name for name in formats}, codec=label, codec_label=label)


def _written_names(ctx: JobContext) -> Iterator[tuple[str, int, str, _Written]]:
    """(list, index, name, written) of each re-encoded track with a name that is not a
    template. A track without a name of its own writes its source's title."""
    for index, audio in enumerate(ctx.job.audio):
        written = _audio_written(ctx, audio)
        stream = track_stream(ctx, audio)
        name = audio.metadata.name
        if name is None and stream is not None:
            name = stream.title
        if written is not None and name and not is_track_name_template(name):
            yield "audio", index, name, written
    for index, subtitle in enumerate(ctx.job.subtitles):
        written = _subtitle_written(ctx, subtitle)
        name = subtitle.metadata.name
        if name is None:
            if isinstance(subtitle.source, int):
                found = ctx.subtitle_streams.get(subtitle.source)
                name = found.title if found is not None else None
            else:
                name = subtitle.source.name
        if written is not None and name and not is_track_name_template(name):
            yield "subtitles", index, name, written


@job_rule("metadata", "metadata.name_stale")
def stale_track_names(ctx: JobContext) -> Iterator[ValidationIssue]:
    """A re-encoded track whose name still names the source's codec or layout (a source title
    ``DTS-HD MA 5.1`` on an AAC stereo track). A warning, with a fix that names the written
    codec and layout instead."""
    for kind, index, name, written in _written_names(ctx):
        found = _restated(name, written)
        if found is None:
            continue
        stale, renamed = found
        at = f"{kind}[{index}].metadata.name"
        *others, last = dict.fromkeys(stale)
        words = f"{', '.join(others)} and {last}" if others else last
        what = "Audio" if kind == "audio" else "Subtitle"
        yield warning(
            "metadata.name_stale",
            at,
            f"{what} track {index + 1} is written as {written.describe()}, but its name "
            f"{shown(name)} says {words}.",
            fix(f"Rename it to {shown(renamed)}", add(at, renamed)),
        )


def _written_default(ctx: JobContext, container: ContainerDef, metadata: TrackMetadata) -> bool:
    """The default flag as the plan writes it: an FFmpeg disposition."""
    if not metadata.default:
        return False
    disposition = ctx.definitions.track_flags["default"].disposition
    return disposition in dispositions(metadata, container, ctx.definitions).split("+")


@job_rule("metadata", "metadata.several_defaults")
def default_tracks(ctx: JobContext) -> Iterator[ValidationIssue]:
    """More than one output track of a kind marked default is allowed, so a warning, with a fix
    that keeps only the first one default. A burned-in subtitle is not an output track."""
    container = ctx.container
    audio = [
        index
        for index, track in enumerate(ctx.job.audio)
        if _written_default(ctx, container, track.metadata)
    ]
    subtitles = [
        index
        for index, sub in enumerate(ctx.job.subtitles)
        if sub.action != "burn" and _written_default(ctx, container, sub.metadata)
    ]
    for field, kind, marked in (("audio", "audio", audio), ("subtitles", "subtitle", subtitles)):
        if len(marked) < 2:
            continue
        first, *others = marked
        numbers = [str(index + 1) for index in marked]
        names = ", ".join(numbers[:-1]) + " and " + numbers[-1]
        yield warning(
            "metadata.several_defaults",
            f"{field}[{others[0]}].metadata.default",
            f"{kind.capitalize()} tracks {names} are {'both' if len(marked) == 2 else 'all'} "
            f"marked default; usually only one {kind} track is.",
            fix(
                f"Keep only {kind} track {first + 1} default",
                *(replace(f"{field}[{index}].metadata.default", False) for index in others),
            ),
        )
