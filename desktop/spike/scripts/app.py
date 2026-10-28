"""Start the spike app with its sidecar in a temporary folder and read the JSON lines it prints
(``sidecar_spawned``, ``sidecar_ready``, ``page_health``, ``sidecar_stopped``,
``sidecar_failed``)."""

from __future__ import annotations

import json
import os
import selectors
import shutil
import subprocess
import time
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from desktop.spike.scripts import sidecar, windows
from desktop.spike.scripts.spike_paths import APP


@dataclass
class App:
    process: subprocess.Popen[bytes]
    home: Path
    spawned_at: float
    """``time.monotonic()`` just before the spawn."""
    events: dict[str, dict[str, Any]] = field(default_factory=dict)
    """The last line of each event, with ``seen`` (seconds from the spawn to the line)."""

    @property
    def log(self) -> Path:
        return self.home / "data" / "sidecar.log"

    def quit(self) -> None:
        """Quit as a closed window does: the app asks its sidecar to shut down."""
        assert self.process.stdin is not None
        self.process.stdin.write(b"quit\n")
        self.process.stdin.flush()

    def wait_event(self, name: str, limit: float = 30.0) -> dict[str, Any]:
        """Read lines until ``name`` comes; raises when the app ends or ``limit`` passes."""
        assert self.process.stdout is not None
        deadline = time.monotonic() + limit
        with selectors.DefaultSelector() as selector:
            selector.register(self.process.stdout, selectors.EVENT_READ)
            while name not in self.events:
                left = deadline - time.monotonic()
                if left <= 0:
                    raise TimeoutError(f"no {name} within {limit} s; seen {list(self.events)}")
                if not selector.select(left):
                    continue
                line = self.process.stdout.readline()
                if not line:
                    raise RuntimeError(f"the app ended (exit {self.process.wait()}) before {name}")
                seen = time.monotonic() - self.spawned_at
                event = json.loads(line)
                self.events[event["event"]] = event | {"seen": seen}
        return self.events[name]


XDG = ("DATA", "CACHE", "CONFIG", "STATE")
GTK_CONFIG = ("gtk-3.0", "dconf/user")
"""Copied from the owner's config folder: without them GTK falls back to Adwaita (its font,
theme and decorations), which changes what the checks measure."""


def private_xdg(root: Path) -> dict[str, str]:
    """XDG folders below ``root``, the config one seeded with copies of :data:`GTK_CONFIG`
    (the owner's files are only read)."""
    owner = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    env = {}
    for name in XDG:
        folder = root / name.lower()
        folder.mkdir(parents=True, exist_ok=True)
        env[f"XDG_{name}_HOME"] = str(folder)
    for name in GTK_CONFIG:
        source, target = owner / name, root / "config" / name
        if target.exists() or not source.exists():
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        if source.is_dir():
            shutil.copytree(source, target, symlinks=True)
        else:
            shutil.copyfile(source, target)
    return env


def environment(
    home: Path, *, unfrozen: bool, extra: Mapping[str, str] | None, xdg: Path | None = None
) -> dict[str, str]:
    """The app's environment with everything it writes in ``home``: the sidecar's folders
    (with :data:`sidecar.SETTINGS`), and the XDG folders (``xdg``, by default in ``home``),
    where WebKitGTK keeps its profile (``$XDG_DATA_HOME/org.reframe.spike``) and caches."""
    env = {name: value for name, value in os.environ.items() if not name.startswith("REFRAME_")}
    env["REFRAME_SPIKE_HOME"] = str(home)
    sidecar.write_settings(home / "config")
    env |= private_xdg(xdg or home / "xdg")
    if unfrozen:
        env["REFRAME_SPIKE_SIDECAR"] = " ".join(sidecar.unfrozen_command())
    return env | dict(extra or {})


def start(
    home: Path,
    *,
    unfrozen: bool = False,
    extra_env: Mapping[str, str] | None = None,
    xdg: Path | None = None,
) -> App:
    """Starts the app; under ``windows run`` only once the window session admits it."""
    env = environment(home, unfrozen=unfrozen, extra=extra_env, xdg=xdg)
    gate = os.environ.get(windows.GATE_ENV)
    if gate:
        windows.ask(Path(gate))
    spawned_at = time.monotonic()
    process = subprocess.Popen(
        [str(APP)],
        env=env,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )
    return App(process, home, spawned_at)
