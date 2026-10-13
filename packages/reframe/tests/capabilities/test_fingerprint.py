"""The GPU fingerprint: Linux sysfs (a fake tree) and the Windows registry (a fake registry;
the Windows code is not run on Windows here)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from reframe.capabilities import gpu_fingerprint
from reframe.capabilities.fingerprint import (
    DISPLAY_CLASS_KEY,
    linux_fingerprint,
    windows_fingerprint,
)


def drm_device(root: Path, name: str, vendor: str, device: str, driver: str | None) -> Path:
    """``/sys/class/drm/<name>/device`` with PCI ids; ``device`` is a link to a shared folder
    (card and render node of one GPU point at the same PCI device)."""
    pci = root / "pci" / f"{vendor}-{device}"
    pci.mkdir(parents=True, exist_ok=True)
    (pci / "vendor").write_text(f"{vendor}\n", encoding="utf-8")
    (pci / "device").write_text(f"{device}\n", encoding="utf-8")
    if driver is not None and not (pci / "driver").exists():
        target = root / "drivers" / driver
        target.mkdir(parents=True, exist_ok=True)
        (pci / "driver").symlink_to(target)
    entry = root / "drm" / name
    entry.mkdir(parents=True)
    (entry / "device").symlink_to(pci)
    return entry


@pytest.mark.skipif(sys.platform == "win32", reason="symlinks need privileges on Windows")
def test_linux_fingerprint(tmp_path: Path) -> None:
    drm_device(tmp_path, "card1", "0x1002", "0x7480", "amdgpu")
    drm_device(tmp_path, "renderD128", "0x1002", "0x7480", "amdgpu")  # the same GPU
    drm_device(tmp_path, "card0", "0x8086", "0x56a0", None)
    connector = tmp_path / "drm" / "card1-DP-1"
    connector.mkdir()
    (connector / "device").symlink_to(tmp_path / "drm" / "card1")  # no PCI ids
    (tmp_path / "drm" / "version").write_text("drm 1.1.0\n", encoding="utf-8")
    nvidia = tmp_path / "nvidia-version"
    assert linux_fingerprint(tmp_path / "drm", nvidia) == (
        "drm 0x1002:0x7480 amdgpu; drm 0x8086:0x56a0 unknown; nvidia none"
    )
    nvidia.write_text(
        "NVRM version: NVIDIA UNIX x86_64 Kernel Module  580.82.07  Fri Aug 29 2026\n"
        "GCC version:  gcc version 15.2.1\n",
        encoding="utf-8",
    )
    assert linux_fingerprint(tmp_path / "drm", nvidia).endswith(
        "nvidia NVRM version: NVIDIA UNIX x86_64 Kernel Module  580.82.07  Fri Aug 29 2026"
    )


def test_linux_fingerprint_without_drm(tmp_path: Path) -> None:
    assert linux_fingerprint(tmp_path / "missing", tmp_path / "nvidia") == "drm none; nvidia none"


class FakeRegistry:
    def __init__(self, keys: dict[str, dict[str, str]]) -> None:
        self.keys = keys

    def subkeys(self, path: str) -> list[str]:
        prefix = path + "\\"
        return sorted({k[len(prefix) :].split("\\")[0] for k in self.keys if k.startswith(prefix)})

    def value(self, path: str, name: str) -> str | None:
        return self.keys.get(path, {}).get(name)


def adapters(**values: dict[str, str]) -> FakeRegistry:
    return FakeRegistry({f"{DISPLAY_CLASS_KEY}\\{key}": value for key, value in values.items()})


def test_windows_fingerprint() -> None:
    registry = adapters(
        **{
            "0000": {"DriverDesc": "AMD Radeon RX 7600", "DriverVersion": "32.0.21025.1024"},
            "0001": {"DriverDesc": "Microsoft Basic Display Adapter"},
            "0002": {"DriverVersion": "1.0"},  # no name: skipped
            "Properties": {"DriverDesc": "not an adapter"},
            "Configuration": {},
        }
    )
    assert windows_fingerprint(registry) == (
        "AMD Radeon RX 7600 32.0.21025.1024; Microsoft Basic Display Adapter unknown"
    )
    assert windows_fingerprint(FakeRegistry({})) == "no display adapter"


def test_gpu_fingerprint_dispatch() -> None:
    registry = adapters(**{"0000": {"DriverDesc": "Intel Arc A380", "DriverVersion": "32.0.101"}})
    assert (
        gpu_fingerprint(platform="win32", registry=registry) == "windows; Intel Arc A380 32.0.101"
    )
    assert gpu_fingerprint(platform="darwin") == "darwin"
    if sys.platform.startswith("linux"):
        assert gpu_fingerprint().startswith("linux; drm ")
