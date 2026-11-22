# PyInstaller spec of the sidecar: one onedir with two executables, `reframe-server` and the
# `reframe` CLI, that share one `_internal/`. Run it through build.py.
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

# Without each of these the frozen build fails. See decision 0001.
DATA_PACKAGES = (
    "babelfish",
    "guessit",  # silent: every name parses to its whole stem
    "reframe.definitions",  # silent: no encoders or language tables, every job draft fails
    "reframe.presets",
    "reframe.tools",
)


def analysis(script):
    return Analysis(
        [str(Path(SPECPATH) / script)],
        datas=[item for package in DATA_PACKAGES for item in collect_data_files(package)],
        # babelfish loads its converters from entry-point strings.
        hiddenimports=collect_submodules("babelfish"),
        # pydantic's hook pulls mypy and hypothesis in through pydantic.mypy and pydantic.v1. The
        # language libraries are dev dependencies that the language tables were built from.
        excludes=["mypy", "hypothesis", "langcodes", "language_data", "marisa_trie"],
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
