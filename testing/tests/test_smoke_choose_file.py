"""desktop/tests/smoke/choose-file.py: finding the file chooser while other windows come and go.

python-xlib is not a dependency of the test environment, so a fake ``Xlib`` stands in for it.
"""

from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "desktop" / "tests" / "smoke" / "choose-file.py"
PID = 4242
VIEWABLE = 2


class BadWindow(Exception):
    pass


class BadDrawable(Exception):
    pass


class Window:
    """A window of the fake X server; ``gone`` names the request that finds it destroyed."""

    def __init__(
        self,
        *children: Window,
        pid: int | None = None,
        role: bytes | None = None,
        gone: str | None = None,
        error: type[Exception] = BadWindow,
    ) -> None:
        self.children = list(children)
        self.pid = pid
        self.role = role
        self.gone = gone
        self.error = error

    def _check(self, request: str) -> None:
        if self.gone == request:
            raise self.error

    def query_tree(self) -> Any:
        self._check("query_tree")
        return types.SimpleNamespace(children=self.children)

    def get_full_property(self, atom: str, kind: int) -> Any:
        self._check("get_full_property")
        value = {
            "_NET_WM_PID": None if self.pid is None else [self.pid],
            "WM_WINDOW_ROLE": self.role,
        }
        found = value[atom]
        return None if found is None else types.SimpleNamespace(value=found)

    def get_attributes(self) -> Any:
        self._check("get_attributes")
        return types.SimpleNamespace(map_state=VIEWABLE)


class Display:
    def __init__(self, root: Window) -> None:
        self.root = root

    def intern_atom(self, name: str) -> str:
        return name

    def screen(self) -> Any:
        return types.SimpleNamespace(root=self.root)


@pytest.fixture
def choose_file(monkeypatch: pytest.MonkeyPatch) -> types.ModuleType:
    xlib = types.ModuleType("Xlib")
    modules: dict[str, Any] = {
        "Xlib": xlib,
        "Xlib.X": types.SimpleNamespace(AnyPropertyType=0, IsViewable=VIEWABLE),
        "Xlib.XK": types.SimpleNamespace(),
        "Xlib.display": types.SimpleNamespace(Display=Display),
        "Xlib.error": types.SimpleNamespace(BadWindow=BadWindow, BadDrawable=BadDrawable),
        "Xlib.ext": types.ModuleType("Xlib.ext"),
        "Xlib.xobject": types.ModuleType("Xlib.xobject"),
        "Xlib.xobject.drawable": types.SimpleNamespace(Window=Window),
    }
    for name in ("X", "XK", "display", "error"):
        setattr(xlib, name, modules[f"Xlib.{name}"])
    modules["Xlib.ext"].xtest = types.SimpleNamespace()
    for name, module in modules.items():
        monkeypatch.setitem(sys.modules, name, module)
    spec = importlib.util.spec_from_file_location("choose_file", SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _dialog() -> Window:
    return Window(pid=PID, role=b"GtkFileChooserDialog")


@pytest.mark.parametrize(
    ("request_", "error"),
    [
        ("query_tree", BadWindow),
        ("get_full_property", BadWindow),
        ("get_attributes", BadWindow),
        ("get_attributes", BadDrawable),
    ],
)
def test_a_window_that_disappears_during_the_walk_is_skipped(
    choose_file: types.ModuleType, request_: str, error: type[Exception]
) -> None:
    dialog = _dialog()
    gone = Window(Window(pid=PID), pid=PID, gone=request_, error=error)
    root = Window(Window(pid=1), gone, Window(dialog))

    assert choose_file._dialog(Display(root), PID) is dialog


def test_no_dialog_of_the_process(choose_file: types.ModuleType) -> None:
    other = Window(pid=PID + 1, role=b"GtkFileChooserDialog")
    root = Window(other, Window(pid=PID, role=b"GtkWindow"), Window(gone="query_tree"))

    assert choose_file._dialog(Display(root), PID) is None
