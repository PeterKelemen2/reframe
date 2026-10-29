"""Find the external tools and check that they work.

An override (an environment variable or a Settings path) that is missing, broken or too old is
reported, never replaced: discovery never falls back to the bundled build or to ``PATH``
behind the user's back. A bundled FFmpeg folder without ffprobe leaves ffprobe missing.

The bundled build is per tool family: FFmpeg (ffmpeg and ffprobe), mkvpropedit and MediaInfo.
On Linux, FFmpeg is bundled but mkvpropedit comes from the distro, so a bundled FFmpeg does not
stop the ``PATH`` search for mkvpropedit.

On Windows only ``.exe`` programs run: a ``.cmd`` or ``.bat`` file goes through ``cmd.exe``,
which interprets ``& | % ^ < >`` in the arguments.
"""

from __future__ import annotations

import asyncio
import os
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from pydantic import BaseModel

from reframe import paths
from reframe.models.issues import Fix, RemoveOp
from reframe.models.tools import ToolInfo, ToolName, ToolOrigin, ToolSet, ToolStatus
from reframe.tools import versions
from reframe.tools.runner import run

__all__ = [
    "ALLOW_SCRIPT_TOOLS_ENV",
    "ENV_VARS",
    "LIBVA_DRIVER_DIRS",
    "TOOL_NAMES",
    "VERSION_TIMEOUT",
    "ToolLocation",
    "ToolPathSettings",
    "check_tool",
    "discover_tools",
    "discover_tools_sync",
    "locate_tools",
]

#: Test-only opt-in: accept ``.cmd`` / ``.bat`` tools on Windows. Nothing else should set it.
ALLOW_SCRIPT_TOOLS_ENV = "REFRAME_ALLOW_SCRIPT_TOOLS"

TOOL_NAMES: tuple[ToolName, ...] = ("ffmpeg", "ffprobe", "mkvpropedit", "mediainfo")
ENV_VARS: Mapping[ToolName, str] = {
    "ffmpeg": "REFRAME_FFMPEG",
    "ffprobe": "REFRAME_FFPROBE",
    "mkvpropedit": "REFRAME_MKVPROPEDIT",
    "mediainfo": "REFRAME_MEDIAINFO",
}
#: Distro folders with libva drivers. The bundled libva may not look there, so the bundled
#: FFmpeg on Linux gets the first one that exists as ``LIBVA_DRIVERS_PATH``.
LIBVA_DRIVER_DIRS = (
    Path("/usr/lib/x86_64-linux-gnu/dri"),
    Path("/usr/lib64/dri"),
    Path("/usr/lib/dri"),
)
#: Seconds for a ``-version`` call. Generous: the first start of a binary on a network share
#: or under a virus scanner can be slow.
VERSION_TIMEOUT = 20.0

_DISPLAY = {
    "ffmpeg": "FFmpeg",
    "ffprobe": "ffprobe",
    "mkvpropedit": "mkvpropedit",
    "mediainfo": "MediaInfo",
}
_FAMILY: Mapping[ToolName, ToolName] = {
    "ffmpeg": "ffmpeg",
    "ffprobe": "ffmpeg",
    "mkvpropedit": "mkvpropedit",
    "mediainfo": "mediainfo",
}

#: Tool paths by tool name. A model with the same fields (``AppSettings.tools``) is accepted too.
ToolPathSettings = Mapping[str, str | os.PathLike[str] | None]


@dataclass(frozen=True)
class ToolLocation:
    """Where a tool is, before it is run (the result of :func:`locate_tools`)."""

    name: ToolName
    path: Path | None
    origin: ToolOrigin | None
    problem: str | None = None
    """Set when the tool cannot be used without running it (missing file)."""
    env_var: str | None = None
    next_to_ffmpeg: bool = False
    env: dict[str, str] = field(default_factory=dict)
    fixes: list[Fix] = field(default_factory=list)
    problem_status: ToolStatus = ToolStatus.MISSING
    """The status that ``problem`` gives (``broken`` for a script tool on Windows)."""


@dataclass(frozen=True)
class _Context:
    environ: Mapping[str, str]
    settings: Mapping[str, str | os.PathLike[str] | None]
    roots: Sequence[Path]
    search_path: str | None
    platform: str

    @property
    def windows(self) -> bool:
        return self.platform == "win32"

    @property
    def allow_scripts(self) -> bool:
        value = self.environ.get(ALLOW_SCRIPT_TOOLS_ENV, "").strip().lower()
        return value not in ("", "0", "false", "no")

    def runnable(self, path: Path) -> bool:
        """On Windows only ``.exe`` (unless script tools are allowed); elsewhere anything."""
        return not self.windows or self.allow_scripts or path.suffix.lower() == ".exe"

    def exe_names(self, tool: str) -> list[str]:
        if not self.windows:
            return [tool]
        if not self.allow_scripts:
            return [tool + ".exe"]
        exts = [
            e.strip().lower()
            for e in self.environ.get("PATHEXT", ".COM;.EXE;.BAT;.CMD").split(";")
            if e.strip()
        ]
        ordered = [".exe", *(e for e in exts if e != ".exe")]
        return [tool + ext for ext in ordered]


def _find_in_dirs(ctx: _Context, tool: str, dirs: Sequence[Path]) -> Path | None:
    for directory in dirs:
        for name in ctx.exe_names(tool):
            candidate = directory / name
            if candidate.is_file():
                return candidate
    return None


def _use_bundled_fix(tool: ToolName, bundled_exists: bool) -> Fix:
    label = f"Use bundled {_DISPLAY[tool]}" if bundled_exists else "Remove the path override"
    return Fix(label=label, patch=[RemoveOp(path=f"/tools/{tool}")], target="settings")


def _bundled_dir(ctx: _Context, tool: ToolName) -> tuple[Path | None, Path | None]:
    """``(binary, family_dir)``: the bundled binary (or None), and the bundled folder of the
    tool's family if one exists (for FFmpeg: the first root with ffmpeg or ffprobe in it)."""
    subdir = paths.BUNDLED_SUBDIRS[tool]
    members = ("ffmpeg", "ffprobe") if _FAMILY[tool] == "ffmpeg" else (tool,)
    for root in ctx.roots:
        family_dir = root / subdir
        search = [family_dir / "bin", family_dir]
        if any(_find_in_dirs(ctx, m, search) for m in members):
            return _find_in_dirs(ctx, tool, search), family_dir
    return None, None


def _libva_env(ctx: _Context) -> dict[str, str]:
    if not ctx.platform.startswith("linux") or ctx.environ.get("LIBVA_DRIVERS_PATH"):
        return {}
    for directory in LIBVA_DRIVER_DIRS:
        if directory.is_dir():
            return {"LIBVA_DRIVERS_PATH": str(directory)}
    return {}


def _override(
    ctx: _Context, tool: ToolName, value: str, origin: ToolOrigin, bundled_exists: bool
) -> ToolLocation:
    env_var = ENV_VARS[tool]
    given = Path(value).expanduser()
    path: Path | None = given
    if given.is_dir():
        path = _find_in_dirs(ctx, tool, [given / "bin", given])
    if origin is ToolOrigin.ENV:
        where = f"{env_var}={value}"
        fixes: list[Fix] = []
        cannot_fix = (
            f" The environment sets this path, so it cannot be changed in Reframe: "
            f"change or unset {env_var} and restart."
        )
    else:
        where = f"The {_DISPLAY[tool]} path in Settings ({value})"
        fixes = [_use_bundled_fix(tool, bundled_exists)]
        cannot_fix = ""
    if path is None:
        problem = f"{where}: the folder has no {tool} executable.{cannot_fix}"
        return ToolLocation(tool, given, origin, problem, env_var, fixes=fixes)
    if not path.is_file():
        problem = f"{where}: the file does not exist.{cannot_fix}"
        return ToolLocation(tool, path, origin, problem, env_var, fixes=fixes)
    if not ctx.runnable(path):
        problem = (
            f"{where}: not an .exe file. On Windows Reframe runs only .exe programs: a .cmd "
            f"or .bat file goes through cmd.exe, which interprets & | % ^ < > in file "
            f"names.{cannot_fix}"
        )
        return ToolLocation(
            tool, path, origin, problem, env_var, problem_status=ToolStatus.BROKEN, fixes=fixes
        )
    return ToolLocation(tool, path, origin, None, env_var, fixes=fixes)


def _sibling_ffprobe(ctx: _Context, ffmpeg: Path) -> Path | None:
    directory = ffmpeg.parent
    names: list[str] = []
    if "ffmpeg" in ffmpeg.name:
        names.append(ffmpeg.name.replace("ffmpeg", "ffprobe", 1))
    names += ctx.exe_names("ffprobe")
    for name in names:
        candidate = directory / name
        if candidate != ffmpeg and candidate.is_file() and ctx.runnable(candidate):
            return candidate
    return None


def _search_path(ctx: _Context, tool: str) -> Path | None:
    """Search the absolute folders of ``PATH``. Never the current folder: ``shutil.which``
    checks it first on Windows."""
    separator = ";" if ctx.windows else ":"
    for entry in (ctx.search_path or "").split(separator):
        folder = entry.strip().strip('"')
        if not folder or not os.path.isabs(folder):
            continue
        for name in ctx.exe_names(tool):
            candidate = Path(folder) / name
            if candidate.is_file() and (ctx.windows or os.access(candidate, os.X_OK)):
                return candidate
    return None


def _locate(
    ctx: _Context, tool: ToolName, located: Mapping[ToolName, ToolLocation]
) -> ToolLocation:
    env_var = ENV_VARS[tool]
    bundled, family_dir = _bundled_dir(ctx, tool)
    bundled_exists = family_dir is not None

    env_value = ctx.environ.get(env_var, "").strip()
    if env_value:
        return _override(ctx, tool, env_value, ToolOrigin.ENV, bundled_exists)
    setting = ctx.settings.get(tool)
    if setting is not None and str(setting).strip():
        return _override(ctx, tool, os.fspath(setting).strip(), ToolOrigin.SETTINGS, bundled_exists)

    if tool == "ffprobe":
        ffmpeg = located.get("ffmpeg")
        if (
            ffmpeg is not None
            and ffmpeg.origin in (ToolOrigin.ENV, ToolOrigin.SETTINGS)
            and ffmpeg.problem is None
            and ffmpeg.path is not None
        ):
            sibling = _sibling_ffprobe(ctx, ffmpeg.path)
            if sibling is not None:
                return ToolLocation(
                    tool,
                    sibling,
                    ffmpeg.origin,
                    None,
                    env_var,
                    next_to_ffmpeg=True,
                    fixes=list(ffmpeg.fixes),
                )

    if family_dir is not None:
        env = _libva_env(ctx) if _FAMILY[tool] == "ffmpeg" else {}
        if bundled is None:
            problem = (
                f"The bundled {_DISPLAY[_FAMILY[tool]]} in {family_dir} has no {tool}: the "
                f"installation is damaged. Reinstall Reframe (or run `reframe tools fetch`)."
            )
            return ToolLocation(tool, None, ToolOrigin.BUNDLED, problem, env_var)
        return ToolLocation(tool, bundled, ToolOrigin.BUNDLED, None, env_var, env=env)

    found = _search_path(ctx, tool)
    if found is not None:
        return ToolLocation(tool, found, ToolOrigin.PATH, None, env_var)
    if tool in ("mkvpropedit", "mediainfo"):
        # A web client cannot set a tool path in Settings: name what works in every mode.
        problem = f"{tool} was not found (optional: install it, or set {env_var} to its path)."
    else:
        problem = (
            f"{tool} was not found: no bundled build, nothing on PATH. Set its path in "
            f"Settings or {env_var}, or run `reframe tools fetch`."
        )
    return ToolLocation(tool, None, None, problem, env_var)


def locate_tools(
    settings: ToolPathSettings | BaseModel | None = None,
    *,
    environ: Mapping[str, str] | None = None,
    bundled_roots: Sequence[Path] | None = None,
    search_path: str | None = None,
    platform: str | None = None,
) -> dict[ToolName, ToolLocation]:
    """Find every tool without running it (file checks only)."""
    env = dict(os.environ if environ is None else environ)
    ctx = _Context(
        environ=env,
        settings=_settings_mapping(settings),
        roots=list(
            paths.bundled_tool_roots(environ=env, platform=platform)
            if bundled_roots is None
            else bundled_roots
        ),
        search_path=env.get("PATH", "") if search_path is None else search_path,
        platform=sys.platform if platform is None else platform,
    )
    located: dict[ToolName, ToolLocation] = {}
    for tool in TOOL_NAMES:
        located[tool] = _locate(ctx, tool, located)
    return located


def _settings_mapping(settings: ToolPathSettings | BaseModel | None) -> ToolPathSettings:
    if settings is None:
        return {}
    if isinstance(settings, BaseModel):
        dumped: dict[str, str | None] = settings.model_dump(mode="json")
        return dumped
    return settings


def _version_argv(tool: ToolName, path: Path) -> list[str]:
    if tool in ("ffmpeg", "ffprobe"):
        return [str(path), "-version"]
    if tool == "mkvpropedit":
        return [str(path), "--version"]
    return [str(path), "--Version"]


def _last_line(text: str) -> str:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return lines[-1] if lines else ""


def _info(loc: ToolLocation, status: ToolStatus, reason: str | None, **kw: object) -> ToolInfo:
    fixes = loc.fixes if status is not ToolStatus.FOUND else []
    return ToolInfo.model_validate(
        {
            "name": loc.name,
            "status": status,
            "path": loc.path,
            "origin": loc.origin,
            "reason": reason,
            "env": loc.env,
            "env_var": loc.env_var,
            "next_to_ffmpeg": loc.next_to_ffmpeg,
            "fixes": fixes,
            **kw,
        }
    )


def _with_origin_note(loc: ToolLocation, reason: str) -> str:
    if loc.origin is ToolOrigin.ENV:
        return (
            f"{reason} The path comes from {loc.env_var}, so it cannot be changed in Reframe: "
            f"change or unset {loc.env_var} and restart."
        )
    if loc.origin is ToolOrigin.SETTINGS and loc.next_to_ffmpeg:
        return f"{reason} (found next to the ffmpeg set in Settings)"
    return reason


async def check_tool(
    loc: ToolLocation,
    *,
    timeout: float = VERSION_TIMEOUT,  # noqa: ASYNC109 - passed to run()
) -> ToolInfo:
    """Run the tool's version command and turn the result into a :class:`ToolInfo`."""
    if loc.problem is not None or loc.path is None:
        return _info(loc, loc.problem_status, loc.problem or f"{loc.name} was not found.")
    result = await run(_version_argv(loc.name, loc.path), timeout=timeout, extra_env=loc.env)
    label = f"{loc.path}"
    if result.error is not None:
        return _info(
            loc, ToolStatus.BROKEN, _with_origin_note(loc, f"{label} cannot run: {result.error}.")
        )
    if result.timed_out:
        reason = f"{label} did not answer the version check within {timeout:g} s."
        return _info(loc, ToolStatus.BROKEN, _with_origin_note(loc, reason))
    if result.returncode != 0:
        detail = _last_line(result.stderr_text) or _last_line(result.stdout_text)
        reason = f"{label}: the version check exited with code {result.returncode}"
        reason += f": {detail}." if detail else "."
        return _info(loc, ToolStatus.BROKEN, _with_origin_note(loc, reason))

    out = result.stdout_text
    if loc.name in ("ffmpeg", "ffprobe"):
        return _ffmpeg_info(loc, out)
    parsed = (
        versions.parse_mkvpropedit_version(out)
        if loc.name == "mkvpropedit"
        else versions.parse_mediainfo_version(out)
    )
    if parsed is None:
        first = out.strip().splitlines()[0] if out.strip() else ""
        reason = f"{label} does not look like {loc.name} (version output: {first[:120]!r})."
        return _info(loc, ToolStatus.BROKEN, _with_origin_note(loc, reason))
    return _info(loc, ToolStatus.FOUND, None, version=parsed.version, release=parsed.version)


def _ffmpeg_info(loc: ToolLocation, out: str) -> ToolInfo:
    parsed = versions.parse_ffmpeg_version(out)
    if parsed is None or parsed.tool != loc.name:
        first = out.strip().splitlines()[0] if out.strip() else ""
        reason = f"{loc.path} does not look like {loc.name} (version output: {first[:120]!r})."
        return _info(loc, ToolStatus.BROKEN, _with_origin_note(loc, reason))
    series = parsed.series
    details: dict[str, object] = {
        "version": parsed.version,
        "release": parsed.release_text,
        "release_series": None if series is None else f"{series[0]}.{series[1]}",
        "build_flags": parsed.build_flags,
        "library_versions": {name: ".".join(map(str, v)) for name, v in parsed.libraries.items()},
    }
    if series is None:
        note = f"The version of {loc.name} ({parsed.version}) could not be checked."
        return _info(loc, ToolStatus.FOUND, note, **details)
    if series < versions.MIN_FFMPEG:
        minimum = ".".join(map(str, versions.MIN_FFMPEG))
        shown = parsed.release_text or f"{parsed.version} (series {series[0]}.{series[1]})"
        reason = (
            f"{_DISPLAY[loc.name]} {shown} at {loc.path} is too old: "
            f"Reframe needs {minimum} or newer."
        )
        return _info(loc, ToolStatus.TOO_OLD, _with_origin_note(loc, reason), **details)
    return _info(loc, ToolStatus.FOUND, None, **details)


async def discover_tools(
    settings: ToolPathSettings | BaseModel | None = None,
    *,
    environ: Mapping[str, str] | None = None,
    bundled_roots: Sequence[Path] | None = None,
    search_path: str | None = None,
    platform: str | None = None,
    timeout: float = VERSION_TIMEOUT,  # noqa: ASYNC109 - passed to run()
) -> ToolSet:
    """Locate every tool and check its version (in parallel). Never raises for tool problems."""
    located = locate_tools(
        settings,
        environ=environ,
        bundled_roots=bundled_roots,
        search_path=search_path,
        platform=platform,
    )
    # A TaskGroup, not gather(): a cancelled gather() returns at its first child's end, so the
    # other children's process kills can be dropped (orphaned ffmpeg). A TaskGroup waits for all.
    async with asyncio.TaskGroup() as group:
        checks = [group.create_task(check_tool(located[t], timeout=timeout)) for t in TOOL_NAMES]
    return ToolSet(**{check.result().name: check.result() for check in checks})


def discover_tools_sync(
    settings: ToolPathSettings | BaseModel | None = None,
    *,
    environ: Mapping[str, str] | None = None,
    bundled_roots: Sequence[Path] | None = None,
    search_path: str | None = None,
    platform: str | None = None,
    timeout: float = VERSION_TIMEOUT,
) -> ToolSet:
    """:func:`discover_tools` for synchronous code.

    It runs its own event loop, so it must not be called from a running loop.
    """
    return asyncio.run(
        discover_tools(
            settings,
            environ=environ,
            bundled_roots=bundled_roots,
            search_path=search_path,
            platform=platform,
            timeout=timeout,
        )
    )
