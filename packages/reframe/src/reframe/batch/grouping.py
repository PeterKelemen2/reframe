"""Grouping files by structure (04 §Grouping; 05 §C-12, M7).

Files whose fingerprints are equal at the chosen level form a group. A file that differs
from a larger group (or an equal one that comes first in episode order) by at most
:data:`NEAR_MAX_DIFFERENCES` tracks is a **near** member of that group, with one line per
difference ("1 extra track (eng AC-3 2.0 "Commentary")", "1 track missing (eng DTS-HD MA
5.1 "English Dub")"): 04 shows E05 with an extra commentary track and E11 without the dub in
the season's group, so they get the group's template and their own warnings, not a group of
their own (decision 0040).

- **Episode order**: the season and episode numbers parsed from the file name (C-16's
  parser; the folder name when the file name has none), then the natural order of the path.
  Files without an episode number come after the episodes.
- **Group name**: the show name and season most members share (``Anime Show S01``).
- **Representative**: the first exact member in episode order; its fingerprint is the
  group's.

Pure: no I/O (the parser reads no files).
"""

from __future__ import annotations

import difflib
import hashlib
import os
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from reframe.batch.descriptors import fingerprint, track_key, video_key
from reframe.models.batch import BatchGroup, Fingerprint, GroupMember, MatchLevel
from reframe.models.media import MediaSource
from reframe.naming.context import resolution_label
from reframe.naming.parse import parse_name
from reframe.naming.source import split_extension
from reframe.probe.folder import natural_key

__all__ = [
    "NEAR_MAX_DIFFERENCES",
    "Comparison",
    "EpisodeInfo",
    "compare",
    "episode_info",
    "episode_key",
    "episode_label",
    "group_name",
    "group_sources",
]

#: A file that differs from a group by at most this many tracks (an extra track, a missing
#: track, a changed one; a different video size or HDR type counts as one) is a near member
#: of it (decision 0040).
NEAR_MAX_DIFFERENCES = 2


@dataclass(frozen=True, slots=True)
class EpisodeInfo:
    """What the file name says about the episode."""

    name: str | None
    """The show name, words separated by spaces (``Anime Show``)."""
    season: int | None
    episode: int | None


def episode_info(path: Path) -> EpisodeInfo:
    """The show name, season and episode of ``path`` from its file name (C-16's parser),
    with the folder's name and season when the file name has none (``S01E01.mkv`` in
    ``Show.S01.1080p``)."""
    stem, _ = split_extension(path.name)
    fields = parse_name(stem).fields
    name, season = fields.name, fields.season
    if name is None or season is None:
        folder = parse_name(path.parent.name).fields if path.parent.name else None
        if folder is not None:
            name = name or folder.name
            season = season if season is not None else folder.season
    if name is not None:
        separator = fields.separator if fields.name else None
        if separator and separator != " ":
            name = name.replace(separator, " ")
        name = " ".join(name.split()) or None
    return EpisodeInfo(name, season, fields.episode)


EpisodeKey = tuple[bool, int, int, tuple[tuple[int, int | str], ...]]


def episode_key(path: Path) -> EpisodeKey:
    """Episode order: season, then episode, then the natural order of the path; files
    without an episode number after the episodes."""
    info = episode_info(path)
    return (
        info.episode is None,
        info.season if info.season is not None else -1,
        info.episode if info.episode is not None else -1,
        natural_key(os.path.normcase(str(path))),
    )


def episode_label(path: Path, *, season: bool = False) -> str:
    """``E05`` (``S01E05`` with ``season``), else the file name."""
    info = episode_info(path)
    if info.episode is None:
        return path.name
    if season and info.season is not None:
        return f"S{info.season:02d}E{info.episode:02d}"
    return f"E{info.episode:02d}"


def group_name(paths: Sequence[Path]) -> str:
    """``Anime Show S01``: the show name and season that most files share (the first file's
    on a tie); the folder name when no name is found."""
    infos = [episode_info(path) for path in paths]
    counted = Counter((info.name, info.season) for info in infos if info.name)
    if counted:
        best = max(counted.values())
        name, season = next(
            (info.name, info.season)
            for info in infos
            if info.name and counted[(info.name, info.season)] == best
        )
        assert name is not None
        return f"{name} S{season:02d}" if season is not None else name
    return paths[0].parent.name or paths[0].name


# --------------------------------------------------------------------------- comparing


@dataclass(frozen=True, slots=True)
class Comparison:
    """How a file's fingerprint differs from a group's (at the group's level)."""

    count: int
    """Differing tracks (an extra, a missing or a changed track counts as one; a different
    video size or HDR type counts as one)."""
    lines: list[str]
    """One line per kind of difference, for :attr:`GroupMember.differences`."""


def _plural(count: int, one: str, many: str) -> str:
    return one if count == 1 else many


def _listed(count: int, one: str, many: str, labels: Sequence[str]) -> str:
    return f"{count} {_plural(count, one, many)} ({'; '.join(labels)})"


def compare(group: Fingerprint, file: Fingerprint) -> Comparison:
    """The differences of ``file`` from ``group`` at the group's level: extra, missing and
    changed tracks (in stream order; at the loose level as a multiset), and the video."""
    level = group.level
    left = [track_key(d, level) for d in group.tracks]
    right = [track_key(d, level) for d in file.tracks]
    extra: list[str] = []
    missing: list[str] = []
    changed: list[str] = []
    if level == "loose":
        wanted = Counter(left)
        for d, key in zip(file.tracks, right, strict=True):
            if wanted[key] > 0:
                wanted[key] -= 1
            else:
                extra.append(d.label)
        have = Counter(right)
        for d, key in zip(group.tracks, left, strict=True):
            if have[key] > 0:
                have[key] -= 1
            else:
                missing.append(d.label)
    else:
        matcher = difflib.SequenceMatcher(a=left, b=right, autojunk=False)
        for op, a1, a2, b1, b2 in matcher.get_opcodes():
            if op == "equal":
                continue
            # A replaced block: a track of one kind that took the place of a track of the same
            # kind "differs"; the others are missing or extra.
            unused = list(file.tracks[b1:b2])
            for old in group.tracks[a1:a2]:
                new = next((n for n in unused if n.kind == old.kind), None)
                if new is None:
                    missing.append(old.label)
                else:
                    unused.remove(new)
                    changed.append(f"{old.label} → {new.label}")
            extra.extend(n.label for n in unused)
    lines: list[str] = []
    if extra:
        lines.append(_listed(len(extra), "extra track", "extra tracks", extra))
    if missing:
        lines.append(_listed(len(missing), "track missing", "tracks missing", missing))
    if changed:
        lines.append(_listed(len(changed), "track differs", "tracks differ", changed))
    count = len(extra) + len(missing) + len(changed)
    group_size, group_hdr = video_key(group)
    file_size, file_hdr = video_key(file)
    if group_size != file_size:
        lines.append(f"video {_size(file)} (the group: {_size(group)})")
        count += 1
    if group_hdr != file_hdr:
        lines.append(f"{_hdr(file)} (the group: {_hdr(group)})")
        count += 1
    return Comparison(count, lines)


def _size(fp: Fingerprint) -> str:
    if fp.width is None or fp.height is None:
        return "none"
    if fp.level == "loose":
        return resolution_label(fp.width, fp.height)
    return f"{fp.width}x{fp.height}"


def _hdr(fp: Fingerprint) -> str:
    names = {"hdr10": "HDR10", "hdr10plus": "HDR10+", "hlg": "HLG", "dolby_vision": "Dolby Vision"}
    return names[fp.hdr.value] if fp.hdr is not None else "SDR"


# --------------------------------------------------------------------------- grouping


@dataclass(slots=True)
class _Bucket:
    """Files with one fingerprint digest, in episode order once every file is in."""

    members: list[tuple[EpisodeKey, MediaSource, Fingerprint]]
    near: list[tuple[MediaSource, Comparison]]

    @property
    def fingerprint(self) -> Fingerprint:
        """The fingerprint of the first file in episode order (the representative)."""
        return self.members[0][2]

    @property
    def first(self) -> EpisodeKey:
        return self.members[0][0]


def group_sources(sources: Sequence[MediaSource], level: MatchLevel) -> list[BatchGroup]:
    """Group ``sources`` by their fingerprints at ``level`` (04 §Grouping): equal
    fingerprints form a group; a file within :data:`NEAR_MAX_DIFFERENCES` of a group with at
    least as many files (the larger group, then the one first in episode order) joins it as a
    near member. Groups are in episode order of their first member; members in episode
    order."""
    buckets: dict[str, _Bucket] = {}
    for source in sources:
        fp = fingerprint(source, level)
        entry = (episode_key(source.ref.path), source, fp)
        bucket = buckets.get(fp.digest)
        if bucket is None:
            buckets[fp.digest] = _Bucket([entry], [])
        else:
            bucket.members.append(entry)
    for bucket in buckets.values():
        bucket.members.sort(key=lambda entry: entry[0])
    ordered = sorted(buckets.values(), key=lambda b: (-len(b.members), b.first))
    anchors: list[_Bucket] = []
    for bucket in ordered:
        best: tuple[_Bucket, Comparison] | None = None
        for anchor in anchors:
            found = compare(anchor.fingerprint, bucket.fingerprint)
            if found.count > NEAR_MAX_DIFFERENCES:
                continue
            if best is None or found.count < best[1].count:
                best = (anchor, found)
        if best is None:
            anchors.append(bucket)
            continue
        anchor = best[0]
        for _, source, fp in bucket.members:
            anchor.near.append((source, compare(anchor.fingerprint, fp)))
    groups = [_group(anchor, level) for anchor in anchors]
    return sorted(groups, key=lambda g: episode_key(g.members[0].path))


def _group(anchor: _Bucket, level: MatchLevel) -> BatchGroup:
    members = [GroupMember(path=s.ref.path) for _, s, _ in anchor.members]
    members += [
        GroupMember(path=s.ref.path, match="near", differences=found.lines)
        for s, found in anchor.near
    ]
    members.sort(key=lambda m: episode_key(m.path))
    members = [_with_episode(member) for member in members]
    representative = anchor.members[0][1].ref.path
    seed = f"{level}\0{anchor.fingerprint.digest}\0{os.path.normcase(str(representative))}"
    return BatchGroup(
        id=hashlib.sha256(seed.encode("utf-8", "surrogatepass")).hexdigest()[:16],
        name=group_name([m.path for m in members]),
        level=level,
        representative=representative,
        fingerprint=anchor.fingerprint,
        members=members,
    )


def _with_episode(member: GroupMember) -> GroupMember:
    info = episode_info(member.path)
    return member.model_copy(update={"season": info.season, "episode": info.episode})
