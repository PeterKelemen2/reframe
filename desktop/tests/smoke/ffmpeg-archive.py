"""Keep the archive of a pinned FFmpeg build (``tools/ffmpeg.toml``) in a cache folder and print
its path, for the tests that install FFmpeg from a file as a user would.

A cached archive is used when its size and SHA-256 are the pin's; otherwise it is downloaded
and checked again. ``--extract DIR`` also extracts it into the new folder ``DIR`` and prints the
folder that holds ``ffmpeg`` instead (for the test media). Run it in the project environment::

    uv run python desktop/tests/smoke/ffmpeg-archive.py CACHE_DIR [--extract DIR]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path, PurePosixPath

from reframe.tools import fetch
from reframe.tools.runner import CancelToken

MANIFEST = Path(__file__).resolve().parents[3] / "tools" / "ffmpeg.toml"


def cached_archive(cache: Path, build: str, platform: str, manifest: Path = MANIFEST) -> Path:
    """The checked archive of ``build`` for ``platform`` in ``cache``; other archives there are
    removed, so that the cache holds only the pin's. :raises FetchError:"""
    pbuild = fetch.load_manifest(manifest)[build].platforms[platform]
    cache.mkdir(parents=True, exist_ok=True)
    archive = cache / (pbuild.file_name or f"ffmpeg-{build}-{platform}.{pbuild.format}")
    for other in cache.iterdir():
        if other != archive and other.is_file():
            other.unlink()
    try:
        fetch.verify_file(archive, pbuild.sha256, pbuild.size)
        return archive
    except (fetch.FetchError, OSError):
        pass
    partial = archive.with_name(archive.name + ".part")
    print(f"ffmpeg-archive: downloading {pbuild.url}", file=sys.stderr)
    fetch.download(pbuild.url, partial, size=pbuild.size, cancel=CancelToken())
    fetch.verify_file(partial, pbuild.sha256, pbuild.size)
    partial.replace(archive)
    return archive


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.add_argument("cache", type=Path)
    parser.add_argument("--build", default="default")
    parser.add_argument("--platform", default=fetch.host_platform())
    parser.add_argument("--extract", type=Path, metavar="DIR")
    args = parser.parse_args(argv)
    try:
        archive = cached_archive(args.cache.absolute(), args.build, args.platform)
        if args.extract is None:
            print(archive)
            return 0
        pbuild = fetch.load_manifest(MANIFEST)[args.build].platforms[args.platform]
        args.extract.mkdir(parents=True)
        fetch.safe_extract(archive, pbuild.format, pbuild.root, args.extract, CancelToken())
        root = args.extract / pbuild.root if pbuild.root else args.extract
        ffmpeg = root.joinpath(*PurePosixPath(pbuild.ffmpeg).parts)
        print(ffmpeg.parent.absolute())
    except (fetch.FetchError, OSError, KeyError) as e:
        print(f"ffmpeg-archive: error: {e!r}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
