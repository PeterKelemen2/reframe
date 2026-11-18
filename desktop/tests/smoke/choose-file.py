"""Choose a file in the GTK file chooser of a process, as a user does with the keyboard: Ctrl+L,
the path, Enter.

Usage: choose-file.py PID PATH [TIMEOUT]. Waits up to TIMEOUT seconds (default 30) for the
dialog; exits 1 when none opens. Needs python-xlib (Debian/Ubuntu: python3-xlib) and an X server
with the XTEST extension (Xvfb has it).
"""

import sys
import time
from collections.abc import Iterator

from Xlib import XK, X, display
from Xlib.ext import xtest
from Xlib.xobject.drawable import Window

DIALOG_ROLE = b"GtkFileChooserDialog"


def _windows(window: Window) -> Iterator[Window]:
    for child in window.query_tree().children:
        yield child
        yield from _windows(child)


def _dialog(screen: display.Display, pid: int) -> Window | None:
    net_wm_pid = screen.intern_atom("_NET_WM_PID")
    role = screen.intern_atom("WM_WINDOW_ROLE")
    for window in _windows(screen.screen().root):
        owner = window.get_full_property(net_wm_pid, X.AnyPropertyType)
        if owner is None or owner.value[0] != pid:
            continue
        if window.get_attributes().map_state != X.IsViewable:
            continue
        name = window.get_full_property(role, X.AnyPropertyType)
        if name is not None and bytes(name.value) == DIALOG_ROLE:
            return window
    return None


def _press(screen: display.Display, keysym: int, *modifiers: int) -> None:
    keycode = screen.keysym_to_keycode(keysym)
    if keycode == 0:
        raise SystemExit(f"no key for keysym {keysym:#x}")
    # A character on the key's second level (an underscore on a US layout) needs Shift.
    shift = screen.keycode_to_keysym(keycode, 0) != keysym
    held = [*modifiers, *([XK.XK_Shift_L] if shift else [])]
    for modifier in held:
        xtest.fake_input(screen, X.KeyPress, screen.keysym_to_keycode(modifier))
    xtest.fake_input(screen, X.KeyPress, keycode)
    xtest.fake_input(screen, X.KeyRelease, keycode)
    for modifier in reversed(held):
        xtest.fake_input(screen, X.KeyRelease, screen.keysym_to_keycode(modifier))
    screen.sync()
    time.sleep(0.02)


def main() -> int:
    pid, path = int(sys.argv[1]), sys.argv[2]
    timeout = float(sys.argv[3]) if len(sys.argv) > 3 else 30.0
    screen = display.Display()
    deadline = time.monotonic() + timeout
    while (dialog := _dialog(screen, pid)) is None:
        if time.monotonic() > deadline:
            print(f"no file chooser of process {pid} after {timeout:.0f} s", file=sys.stderr)
            return 1
        time.sleep(0.25)
    # Without a window manager nothing gives the dialog the keyboard.
    dialog.set_input_focus(X.RevertToParent, X.CurrentTime)
    screen.sync()
    time.sleep(0.5)
    _press(screen, XK.XK_l, XK.XK_Control_L)
    time.sleep(0.3)
    _press(screen, XK.XK_a, XK.XK_Control_L)
    for char in path:
        # Latin-1 keysyms are the characters' code points.
        _press(screen, ord(char))
    time.sleep(0.3)
    _press(screen, XK.XK_Return)
    return 0


if __name__ == "__main__":
    sys.exit(main())
