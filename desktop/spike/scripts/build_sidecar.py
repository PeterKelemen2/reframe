"""Build the frozen ``reframe-server`` as a PyInstaller onedir in ``desktop/spike/dist/``.

Each entry of :data:`OPTIONS` is a PyInstaller option with what goes wrong without it.
``--without NAME`` leaves one out, so its error can be seen again.
"""

from __future__ import annotations

import argparse
import importlib.util
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from desktop.spike.scripts.spike_paths import SIDECAR_DIST, SIDECAR_ONEDIR, SPIKE

ENTRY = SPIKE / "scripts" / "sidecar_entry.py"
WORK = SPIKE / "build"


@dataclass(frozen=True)
class Option:
    name: str
    options: tuple[str, ...]
    without: str
    """What happens without it: the frozen server's error (the last line of its traceback), or
    what it costs."""


def _libmediainfo() -> tuple[str, ...]:
    spec = importlib.util.find_spec("pymediainfo")
    if spec is None or spec.origin is None:
        return ()
    libraries = sorted(Path(spec.origin).parent.glob("libmediainfo.so*"))
    return tuple(
        part for library in libraries for part in ("--add-binary", f"{library}:pymediainfo")
    )


OPTIONS = (
    Option(
        "babelfish-data",
        ("--collect-data", "babelfish"),
        "FileNotFoundError: [Errno 2] No such file or directory: "
        "'…/_internal/babelfish/data/iso-3166-1.txt'",
    ),
    Option(
        "babelfish-converters",
        ("--collect-submodules", "babelfish"),
        "ModuleNotFoundError: No module named 'babelfish.converters.alpha2'",
    ),
    Option(
        "builtin-presets",
        ("--collect-data", "reframe.presets"),
        "FileNotFoundError: [Errno 2] No such file or directory: "
        "'…/_internal/reframe/presets/data/builtin.json' (application startup failed, exit 3)",
    ),
    Option(
        "language-data",
        ("--collect-data", "language_data"),
        "FileNotFoundError: [Errno 2] No such file or directory: "
        "'…/_internal/language_data/data/language-subtag-registry.txt' "
        "(GET /api/languages: 500)",
    ),
    Option(
        "definitions-data",
        ("--collect-data", "reframe.definitions"),
        "no error at start-up: the loader reads a missing data file as empty, so "
        "GET /api/definitions has 0 video encoders and POST /api/jobs/draft fails "
        "(500, KeyError: 'mkv' in reframe/batch/audio_rules.py apply_codec_rules)",
    ),
    Option(
        "tools-manifest",
        ("--collect-data", "reframe.tools"),
        "POST /api/system/tools/fetch: the task fails with 'cannot read the manifest "
        "…/_internal/reframe/tools/ffmpeg.toml: No such file or directory'",
    ),
    Option(
        "guessit-data",
        ("--collect-data", "guessit"),
        "no error: guessit raises FileNotFoundError: [Errno 2] No such file or directory: "
        "'…/_internal/guessit/config/options.json', the core reads a guessit failure as no "
        "match, so every name parses to its whole stem (Show.Name.S01E02.1080p.BluRay.x264-GRP: "
        "no season, episode, resolution, source or group)",
    ),
    Option(
        "pymediainfo",
        ("--hidden-import", "pymediainfo"),
        "no error: the core imports pymediainfo with importlib.import_module, so it is not "
        "collected and the frozen probe runs without MediaInfo (vfr.mkv: video bitrate "
        "unknown instead of 483043 from mediainfo)",
    ),
    Option(
        "libmediainfo",
        _libmediainfo(),
        "the build warns 'MediaInfo shared library not found - pymediainfo will likely fail to "
        "work!' (the hook's default patterns miss libmediainfo.so.0 of the wheel), and the "
        "frozen probe runs without MediaInfo as above",
    ),
    Option(
        "no-mypy",
        ("--exclude-module", "mypy"),
        "pydantic's hook collects pydantic.mypy, which pulls in mypy, ast_serialize and librt",
    ),
    Option(
        "no-hypothesis",
        ("--exclude-module", "hypothesis"),
        "pydantic's hook collects pydantic.v1, which pulls in hypothesis",
    ),
)


def pyinstaller_argv(without: set[str], dist: Path) -> list[str]:
    argv = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--onedir",
        "--name",
        "reframe-server",
        "--distpath",
        str(dist),
        "--workpath",
        str(WORK / dist.name),
        "--specpath",
        str(WORK / dist.name),
    ]
    for option in OPTIONS:
        if option.name not in without:
            argv += option.options
    return [*argv, str(ENTRY)]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--without",
        action="append",
        default=[],
        choices=[option.name for option in OPTIONS],
        help="leave this option out (to see its error again)",
    )
    parser.add_argument("--bare", action="store_true", help="leave every option out")
    parser.add_argument(
        "--dist",
        type=Path,
        default=SIDECAR_DIST,
        help="build into this folder instead (the frozen server is DIST/reframe-server/)",
    )
    args = parser.parse_args(argv)
    without = {option.name for option in OPTIONS} if args.bare else set(args.without)
    onedir = args.dist.absolute() / SIDECAR_ONEDIR.name
    shutil.rmtree(onedir, ignore_errors=True)
    started = time.monotonic()
    result = subprocess.run(pyinstaller_argv(without, args.dist.absolute()), check=False)
    if result.returncode != 0:
        return result.returncode
    print(f"built {onedir} in {time.monotonic() - started:.0f} s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
