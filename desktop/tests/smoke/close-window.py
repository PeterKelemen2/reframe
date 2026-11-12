"""Ask the mapped X11 windows of a process to close, as a window manager's close button does.

Usage: close-window.py PID. Exits 1 when the process has no mapped window that takes
WM_DELETE_WINDOW. Needs python-xlib (Debian/Ubuntu: python3-xlib).
"""

import sys
from collections.abc import Iterator

from Xlib import X, display
from Xlib.protocol import event
from Xlib.xobject.drawable import Window


def _windows(window: Window) -> Iterator[Window]:
    for child in window.query_tree().children:
        yield child
        yield from _windows(child)


def main() -> int:
    pid = int(sys.argv[1])
    screen = display.Display()
    net_wm_pid = screen.intern_atom("_NET_WM_PID")
    wm_protocols = screen.intern_atom("WM_PROTOCOLS")
    wm_delete = screen.intern_atom("WM_DELETE_WINDOW")
    sent = 0
    for window in _windows(screen.screen().root):
        owner = window.get_full_property(net_wm_pid, X.AnyPropertyType)
        if owner is None or owner.value[0] != pid:
            continue
        # GTK's unmapped client-leader window carries the pid too.
        if window.get_attributes().map_state != X.IsViewable:
            continue
        if wm_delete not in (window.get_wm_protocols() or []):
            continue
        message = event.ClientMessage(
            window=window,
            client_type=wm_protocols,
            data=(32, [wm_delete, X.CurrentTime, 0, 0, 0]),
        )
        window.send_event(message)
        sent += 1
    screen.flush()
    if sent == 0:
        print(f"no mapped window of process {pid} takes WM_DELETE_WINDOW", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
