"""The GPU fingerprint: Linux sysfs (a fake tree) and the Windows registry (a fake registry;
the Windows code is not run on Windows here)."""

from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest

from reframe.capabilities import fingerprint as fingerprint_module
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


class FakeKey:
    def __init__(self, path: str) -> None:
        self.path = path
        self.closed = False

    def __enter__(self) -> FakeKey:
        return self

    def __exit__(self, *exc: object) -> None:
        self.closed = True


class FakeWinreg(types.ModuleType):
    """The part of ``winreg`` that the registry reader uses, over ``keys`` (path → values)."""

    HKEY_LOCAL_MACHINE = 0x80000002

    def __init__(self, keys: dict[str, dict[str, object]]) -> None:
        super().__init__("winreg")
        self.keys = keys
        self.opened: list[FakeKey] = []

    def OpenKey(self, root: int, path: str) -> FakeKey:
        assert root == self.HKEY_LOCAL_MACHINE
        if not any(k == path or k.startswith(path + "\\") for k in self.keys):
            raise FileNotFoundError(2, "The system cannot find the file specified")
        key = FakeKey(path)
        self.opened.append(key)
        return key

    def EnumKey(self, key: FakeKey, index: int) -> str:
        prefix = key.path + "\\"
        names = sorted({k[len(prefix) :].split("\\")[0] for k in self.keys if k.startswith(prefix)})
        if index >= len(names):
            raise OSError(259, "No more data is available")
        return names[index]

    def QueryValueEx(self, key: FakeKey, name: str) -> tuple[object, int]:
        values = self.keys.get(key.path, {})
        if name not in values:
            raise FileNotFoundError(2, "The system cannot find the file specified")
        return values[name], 1  # REG_SZ


def windows_gpu_fingerprint(monkeypatch: pytest.MonkeyPatch, fake: FakeWinreg) -> str:
    """``gpu_fingerprint()`` as on Windows, with ``fake`` as ``winreg``."""
    monkeypatch.setitem(sys.modules, "winreg", fake)
    monkeypatch.setattr(sys, "platform", "win32")
    try:
        return gpu_fingerprint()
    finally:
        monkeypatch.undo()  # sys.platform back before anything else runs


def test_the_windows_registry_reader(monkeypatch: pytest.MonkeyPatch) -> None:
    """The ``winreg`` reader itself, with a fake ``winreg`` module."""
    fake = FakeWinreg(
        {
            f"{DISPLAY_CLASS_KEY}\\0000": {
                "DriverDesc": "AMD Radeon RX 7600",
                "DriverVersion": "32.0.21025.1024",
            },
            f"{DISPLAY_CLASS_KEY}\\0001": {"DriverDesc": "Microsoft Basic Display Adapter"},
            f"{DISPLAY_CLASS_KEY}\\0002": {"DriverVersion": "1.0"},
            f"{DISPLAY_CLASS_KEY}\\Properties": {},
        }
    )
    assert windows_gpu_fingerprint(monkeypatch, fake) == (
        "windows; AMD Radeon RX 7600 32.0.21025.1024; Microsoft Basic Display Adapter unknown"
    )
    assert fake.opened
    assert all(key.closed for key in fake.opened)


@pytest.mark.skipif(sys.platform == "win32", reason="reads the real registry on Windows")
def test_the_windows_registry_reader_reads_nothing_on_another_os() -> None:
    reader = fingerprint_module._WinReg()
    assert reader.subkeys(DISPLAY_CLASS_KEY) == []
    assert reader.value(f"{DISPLAY_CLASS_KEY}\\0000", "DriverDesc") is None
    assert gpu_fingerprint(platform="win32") == "windows; no display adapter"


def test_the_windows_registry_reader_without_the_class_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = FakeWinreg({})
    assert windows_gpu_fingerprint(monkeypatch, fake) == "windows; no display adapter"
    assert fake.opened == []
