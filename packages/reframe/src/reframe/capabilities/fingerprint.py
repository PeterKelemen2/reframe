"""The GPU fingerprint of the capability cache key (C-4).

A cached detection result is reused only on the same GPUs and drivers:

- **Linux**: the PCI vendor and device id of every DRM device
  (``/sys/class/drm/*/device/{vendor,device}``) and its kernel driver, plus the first line of
  ``/proc/driver/nvidia/version`` (the NVIDIA driver version) when it exists.
- **Windows**: the name and driver version of every display adapter, read from the registry
  (the display adapter class key, ``DriverDesc`` and ``DriverVersion``). No subprocess, no WMI:
  ``winreg`` from the standard library. Called in a worker thread by the capability service
  ("read once in the background", 05 §C-4).

Reading never raises: a value that cannot be read is left out. The fingerprint is a stable
text (sorted), so it can be compared and stored as it is.

The Windows code is unit-tested on Linux with a fake registry (:class:`Registry`); it has not
run on Windows yet.
"""

from __future__ import annotations

import contextlib
import itertools
import os
import sys
from pathlib import Path
from typing import Protocol

__all__ = [
    "DISPLAY_CLASS_KEY",
    "Registry",
    "gpu_fingerprint",
    "linux_fingerprint",
    "windows_fingerprint",
]

#: ``HKEY_LOCAL_MACHINE`` key of the display adapter device class (GUID_DEVCLASS_DISPLAY).
DISPLAY_CLASS_KEY = r"SYSTEM\CurrentControlSet\Control\Class\{4d36e968-e325-11ce-bfc1-08002be10318}"
_DRM = Path("/sys/class/drm")
_NVIDIA_VERSION = Path("/proc/driver/nvidia/version")


def _read(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        return None


def linux_fingerprint(drm: Path = _DRM, nvidia_version: Path = _NVIDIA_VERSION) -> str:
    """``drm 0x1002:0x7480 amdgpu; nvidia none`` (one entry per PCI device, sorted)."""
    devices: dict[str, str] = {}
    try:
        entries = sorted(drm.iterdir())
    except OSError:
        entries = []
    for entry in entries:
        device = entry / "device"
        vendor = _read(device / "vendor")
        product = _read(device / "device")
        if vendor is None or product is None:
            continue  # connectors (card1-DP-1) and the "version" file have no PCI ids
        try:
            real = os.path.realpath(device)
        except OSError:
            real = str(device)
        driver = "unknown"
        with contextlib.suppress(OSError):
            driver = os.path.basename(os.readlink(device / "driver"))
        devices[real] = f"{vendor}:{product} {driver}"
    nvidia = _read(nvidia_version)
    nvidia_line = nvidia.splitlines()[0].strip() if nvidia else "none"
    parts = [f"drm {value}" for value in sorted(devices.values())] or ["drm none"]
    return "; ".join([*parts, f"nvidia {nvidia_line}"])


class Registry(Protocol):
    """Read access to ``HKEY_LOCAL_MACHINE`` (``winreg``, or a fake in tests)."""

    def subkeys(self, path: str) -> list[str]:
        """Names of the subkeys of ``path``; ``[]`` if it cannot be opened."""
        ...

    def value(self, path: str, name: str) -> str | None:
        """The value ``name`` of ``path`` as text; ``None`` if it cannot be read."""
        ...


def windows_fingerprint(registry: Registry) -> str:
    """``AMD Radeon RX 7600 32.0.21025.1024; …`` (one entry per display adapter, sorted)."""
    adapters = []
    for name in registry.subkeys(DISPLAY_CLASS_KEY):
        if not (len(name) == 4 and name.isdigit()):
            continue  # "Configuration", "Properties": not adapters
        path = f"{DISPLAY_CLASS_KEY}\\{name}"
        description = registry.value(path, "DriverDesc")
        if description is None:
            continue
        version = registry.value(path, "DriverVersion") or "unknown"
        adapters.append(f"{description} {version}")
    return "; ".join(sorted(adapters)) or "no display adapter"


class _WinReg:  # pragma: no cover - Windows only
    """:class:`Registry` with ``winreg``."""

    def subkeys(self, path: str) -> list[str]:
        names: list[str] = []
        if sys.platform == "win32":
            import winreg

            try:
                with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, path) as key:
                    for index in itertools.count():
                        try:
                            names.append(winreg.EnumKey(key, index))
                        except OSError:
                            break
            except OSError:
                pass
        return names

    def value(self, path: str, name: str) -> str | None:
        result: str | None = None
        if sys.platform == "win32":
            import winreg

            try:
                with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, path) as key:
                    data, _kind = winreg.QueryValueEx(key, name)
                result = str(data)
            except OSError:
                result = None
        return result


def gpu_fingerprint(*, platform: str | None = None, registry: Registry | None = None) -> str:
    """The GPU fingerprint of this machine (blocking file or registry reads: call it in a
    worker thread). ``platform`` is a ``sys.platform`` value (default: this one)."""
    platform = sys.platform if platform is None else platform
    if platform == "win32":
        return "windows; " + windows_fingerprint(registry if registry is not None else _WinReg())
    if platform.startswith("linux"):
        return "linux; " + linux_fingerprint()
    return platform
