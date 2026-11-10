# PyInstaller spec of the sidecar: one onedir with two executables, `reframe-server` and the
# `reframe` CLI, that share one `_internal/`. Run it through build.py.
import importlib.util
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

# Without each of these the frozen build fails. See decision 0001.
DATA_PACKAGES = (
    "babelfish",
    "guessit",  # silent: every name parses to its whole stem
    "language_data",
    "reframe.definitions",  # silent: no encoders, every job draft fails
    "reframe.presets",
    "reframe.tools",
    "reframe_server",  # GET /api/languages answers 500
)


def mediainfo_libraries():
    # The pymediainfo hook's patterns miss the wheel's libmediainfo.so.0.
    folder = Path(importlib.util.find_spec("pymediainfo").origin).parent
    found = [*folder.glob("libmediainfo.so*"), *folder.glob("MediaInfo.dll")]
    return [(str(library), "pymediainfo") for library in sorted(found)]


def analysis(script):
    return Analysis(
        [str(Path(SPECPATH) / script)],
        datas=[item for package in DATA_PACKAGES for item in collect_data_files(package)],
        binaries=mediainfo_libraries(),
        # babelfish loads its converters from entry-point strings; the core imports pymediainfo
        # with importlib (silent: probes run without MediaInfo).
        hiddenimports=[*collect_submodules("babelfish"), "pymediainfo"],
        # pydantic's hook pulls them in through pydantic.mypy and pydantic.v1.
        excludes=["mypy", "hypothesis"],
    )


def executable(name, built):
    return EXE(
        PYZ(built.pure),
        built.scripts,
        [],
        exclude_binaries=True,
        name=name,
        console=True,
        upx=False,
    )


server = analysis("server_entry.py")
cli = analysis("cli_entry.py")
COLLECT(
    executable("reframe-server", server),
    server.binaries,
    server.datas,
    executable("reframe", cli),
    cli.binaries,
    cli.datas,
    name="sidecar",
    upx=False,
)
