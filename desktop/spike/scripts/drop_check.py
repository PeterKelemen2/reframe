"""Drag-and-drop from Dolphin into the spike app, with the real pointer, on the secondary output.

For each case (a name with spaces, non-ASCII names, a name that is not UTF-8, three files, a
folder) it starts a Dolphin of its own (temporary XDG folders, the case's items selected), drags
the selection onto the drop page and records what arrives: Tauri's drag-drop event (the paths as
bytes in the shell, and as the page gets them) or, with Tauri's handler off, the DOM's ``drop``
event. The button is released only over the app after the page saw the drag enter; otherwise
the pointer goes back to where it pressed and releases there (a drop on itself does nothing).

    uv run python -m desktop.spike.scripts.drop_check --session wayland \\
        --json results/drop-wayland.json
    uv run python -m desktop.spike.scripts.drop_check --session xwayland \\
        --json results/drop-xwayland.json
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
import threading
import time
import urllib.parse
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from desktop.spike.scripts import app as spike_app
from desktop.spike.scripts import kwin, pointer, windows
from desktop.spike.scripts.spike_paths import APP, SPIKE

APP_SPOT: windows.Spot = (590, 120, 1240, 760)
"""The app's left edge is under Dolphin's right edge: a drag goes straight from one to the other."""
DOLPHIN_SPOT: windows.Spot = (20, 120, 580, 760)
FILE_ITEM = (216, 131)
"""The middle of the first item of Dolphin's icon view from the frame's top-left corner, with
Dolphin's defaults, a new configuration and the spot above (from ``--calibrate``)."""
ATSPI = """
import json, sys
import gi
gi.require_version("Atspi", "2.0")
from gi.repository import Atspi
pid, names, found = int(sys.argv[1]), set(sys.argv[2:]), []
def walk(node, depth):
    if node is None or depth > 25:
        return
    if node.get_name() in names or node.get_role_name() == "frame":
        box = node.get_extents(Atspi.CoordType.WINDOW)
        found.append({
            "name": node.get_name(),
            "role": node.get_role_name(),
            "client": [box.x, box.y, box.width, box.height],
            "selected": node.get_state_set().contains(Atspi.StateType.SELECTED),
        })
    for index in range(min(node.get_child_count(), 200)):
        walk(node.get_child_at_index(index), depth + 1)
desktop = Atspi.get_desktop(0)
for index in range(desktop.get_child_count()):
    app = desktop.get_child_at_index(index)
    if app is not None and app.get_process_id() == pid:
        walk(app, 0)
print(json.dumps(found))
"""
"""Reads the AT-SPI extents of the named items (relative to the client area). It runs in the
system Python, which has PyGObject; the spike's environment does not."""


def dolphin_items(pid: int, paths: list[bytes]) -> list[dict[str, Any]]:
    """What AT-SPI says of Dolphin's window and of the items named like ``paths`` (read only;
    Dolphin must run with ``QT_LINUX_ACCESSIBILITY_ALWAYS_ON``). Empty when it cannot tell."""
    # Qt shows a byte that is not UTF-8 as U+FFFD.
    names = [os.path.basename(path).decode(errors="replace") for path in paths]
    try:
        answer = subprocess.run(
            ["/usr/bin/python3", "-I", "-c", ATSPI, str(pid), *names],
            capture_output=True,
            text=True,
            timeout=30,
            check=True,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    found: list[dict[str, Any]] = json.loads(answer.stdout)
    return found


def item_point(frame: kwin.Rect, items: list[dict[str, Any]]) -> tuple[int, int] | None:
    """The middle of the first item in screen coordinates. The client area is the bottom of
    the frame: KWin's title bar is above it."""
    client = next((item for item in items if item["role"] == "frame"), None)
    files = [item for item in items if item["role"] != "frame"]
    if client is None or not files:
        return None
    first = min(files, key=lambda item: (item["client"][1], item["client"][0]))
    x, y, width, height = first["client"]
    top = frame.y + frame.height - client["client"][3]
    return (frame.x + x + width // 2, top + y + height // 2)


GTK_TARGET = """
import json, sys
import gi
gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import GLib, Gdk, Gtk
def log(**record):
    line = {"event": "spike_log", "check": "drop", "source": "gtk", **record}
    print(json.dumps(line), flush=True)
entered = []
def motion(widget, context, x, y, time):
    if not entered:
        entered.append(1)
        log(type="enter", targets=[atom.name() for atom in context.list_targets()])
    return False
def received(widget, context, x, y, data, info, time):
    raw = data.get_data()
    text = raw.decode(errors="replace")
    log(type="drop", target=data.get_target().name(), hex=raw.hex(), text=text)
    entered.clear()
def stdin(source, condition):
    Gtk.main_quit()
    return False
window = Gtk.Window(title="reframe-spike raw drop target")
window.set_default_size(1240, 760)
label = Gtk.Label(label="GTK 3 drop target: logs the raw text/uri-list")
window.add(label)
uris = [Gtk.TargetEntry.new("text/uri-list", 0, 0)]
label.drag_dest_set(Gtk.DestDefaults.ALL, uris, Gdk.DragAction.COPY)
label.connect("drag-motion", motion)
label.connect("drag-data-received", received)
GLib.io_add_watch(sys.stdin.fileno(), GLib.PRIORITY_DEFAULT, GLib.IO_IN | GLib.IO_HUP, stdin)
window.show_all()
log(source="page", type="ready")
Gtk.main()
"""
"""A plain GTK 3 drop target (system Python, PyGObject) that logs the bytes of the
``text/uri-list`` that the source sends, before any toolkit turns them into paths."""

CASES: list[tuple[str, list[bytes]]] = [
    ("spaces", [b"film with spaces.mkv"]),
    ("accents", ["Ünnepi film \u2013 2.mkv".encode()]),
    ("cjk", ["日本語.mkv".encode()]),
    ("not-utf8", [b"bad\xffname.mkv"]),
    ("three-files", [b"one.mkv", "két film.mkv".encode(), "日本語 3.mkv".encode()]),
    ("folder", [b"A folder"]),
]


class Lines:
    """The JSON lines that a process prints on stdout, kept in order."""

    def __init__(self, process: subprocess.Popen[bytes]) -> None:
        self.process = process
        self.seen: list[dict[str, Any]] = []
        self._changed = threading.Condition()
        threading.Thread(target=self._read, daemon=True).start()

    def _read(self) -> None:
        assert self.process.stdout is not None
        for raw in self.process.stdout:
            try:
                record = json.loads(raw)
            except ValueError:
                continue
            with self._changed:
                self.seen.append(record)
                self._changed.notify_all()

    def mark(self) -> int:
        with self._changed:
            return len(self.seen)

    def wait(
        self, match: Callable[[dict[str, Any]], bool], limit: float, since: int = 0
    ) -> dict[str, Any] | None:
        deadline = time.monotonic() + limit
        with self._changed:
            while True:
                for record in self.seen[since:]:
                    if match(record):
                        return record
                since = len(self.seen)
                left = deadline - time.monotonic()
                if left <= 0:
                    return None
                self._changed.wait(left)


def is_enter(record: dict[str, Any]) -> bool:
    return any(
        is_drop_log(record, source, kind)
        for source, kind in (("dom", "dragenter"), ("tauri", "enter"), ("gtk", "enter"))
    )


def is_drop(record: dict[str, Any]) -> bool:
    return any(is_drop_log(record, source, "drop") for source in ("dom", "tauri", "gtk"))


def is_drop_log(record: dict[str, Any], source: str, kind: str) -> bool:
    return (
        record.get("event") == "spike_log"
        and record.get("check") == "drop"
        and record.get("source") == source
        and record.get("type") == kind
    )


def make_files(root: Path) -> dict[str, list[bytes]]:
    """One folder per case with only its items, so the view shows the selection alone."""
    made: dict[str, list[bytes]] = {}
    root.mkdir(parents=True, exist_ok=True)
    for name, items in CASES:
        folder = os.fsencode(root / name)
        os.mkdir(folder)
        paths = []
        for item in items:
            path = os.path.join(folder, item)
            if name == "folder":
                os.mkdir(path)
                Path(os.fsdecode(path), "inside.mkv").write_bytes(b"not a video")
            else:
                with open(path, "wb") as file:
                    file.write(b"not a video")
            paths.append(path)
        made[name] = paths
    return made


def private_xdg(root: Path) -> dict[str, str]:
    """XDG folders of our own: Dolphin and Spectacle read and write none of the owner's."""
    env = dict(os.environ)
    for name in ("CONFIG", "STATE", "CACHE", "DATA"):
        folder = root / name.lower()
        folder.mkdir(parents=True, exist_ok=True)
        env[f"XDG_{name}_HOME"] = str(folder)
    return env


def owner_files() -> dict[str, float | None]:
    home = Path.home()
    files = [home / ".config" / "dolphinrc", home / ".local" / "state" / "dolphinstaterc"]
    return {str(path): path.stat().st_mtime if path.exists() else None for path in files}


def uri_paths(uri_list: str) -> list[dict[str, Any]]:
    """The local paths of a ``text/uri-list`` as bytes, and whether each exists."""
    found = []
    for uri in uri_list.splitlines():
        if not uri or uri.startswith("#"):
            continue
        parsed = urllib.parse.urlsplit(uri)
        raw = urllib.parse.unquote_to_bytes(parsed.path)
        found.append({"uri": uri, "hex": raw.hex(), "exists": os.path.exists(raw)})
    return found


def string_paths(paths: list[str]) -> list[dict[str, Any]]:
    """Paths as the page got them (JSON strings): their UTF-8 bytes and whether those exist."""
    return [
        {"path": path, "hex": path.encode().hex(), "exists": os.path.exists(path.encode())}
        for path in paths
    ]


@dataclass
class Run:
    session: windows.Session
    pointer: pointer.Pointer
    app: Lines
    app_rect: kwin.Rect
    xdg: dict[str, str]

    def dolphin(self, paths: list[bytes], name: str) -> tuple[subprocess.Popen[bytes], kwin.Rect]:
        process = self.session.spawn(
            [b"dolphin", b"--new-window", b"--select", *paths],
            DOLPHIN_SPOT,
            env=self.xdg,
            stdout=subprocess.DEVNULL,
            stderr=trace(f"dolphin-{name}"),
        )
        try:
            placed = self.session.window(process.pid)
        except BaseException:
            windows.terminate(process)
            raise
        return process, placed.rect

    def drag(self, start: tuple[int, int]) -> dict[str, Any]:
        """Press at ``start``, move onto the app, release there once the page saw the drag."""
        target = (
            self.app_rect.x + self.app_rect.width // 2,
            self.app_rect.y + self.app_rect.height // 2,
        )
        since = self.app.mark()
        began = time.monotonic()
        self.pointer.move(*start)
        time.sleep(0.15)
        self.pointer.press()
        # Past Qt's drag distance first, then on to the app in small steps.
        self.pointer.glide(pointer.line(start, (start[0] + 12, start[1] + 6), 4), pause=0.03)
        self.pointer.glide(pointer.line((start[0] + 12, start[1] + 6), target, 30), pause=0.016)
        entered = self.app.wait(is_enter, 1.5, since)
        if entered is None:
            self.pointer.glide(pointer.line(target, start, 20), pause=0.016)
            self.pointer.release()
            return {
                "dropped": False,
                "reason": "the page saw no drag enter",
                "seconds": time.monotonic() - began,
            }
        self.pointer.glide(pointer.line(target, (target[0] + 8, target[1] + 8), 4), pause=0.03)
        self.pointer.release()
        done = self.app.wait(is_drop, 2.0, since)
        time.sleep(0.5)
        return {
            "dropped": done is not None,
            "seconds": round(time.monotonic() - began, 2),
            "records": [
                record
                for record in self.app.seen[since:]
                if record.get("event") in ("spike_log", "drop_native")
            ],
        }


def summarise(records: list[dict[str, Any]]) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    for record in records:
        if record.get("event") == "drop_native":
            summary[f"native_{record['kind']}"] = record.get("paths")
        elif record.get("source") == "tauri":
            summary[f"tauri_{record['type']}"] = string_paths(record.get("paths") or [])
        elif record.get("source") == "gtk":
            entry = {key: record.get(key) for key in ("target", "targets", "hex", "text")}
            if record.get("text"):
                entry["uri_paths"] = uri_paths(record["text"])
            summary[f"gtk_{record['type']}"] = entry
        elif record.get("source") == "dom":
            transfer = record.get("transfer") or {}
            entry = dict(transfer)
            if transfer.get("uriList"):
                entry["uri_paths"] = uri_paths(transfer["uriList"])
            # WebKitGTK's text/html is one styled <a> per drop: keep the links only.
            entry["html_links"] = re.findall(r">([^<]*)</a>", entry.pop("html", ""))
            summary[f"dom_{record['type']}"] = entry
    return summary


def pointer_summary(log: list[dict[str, Any]]) -> dict[str, Any]:
    """Every move's read-back folded into a few numbers; presses and releases kept."""
    moves = [entry for entry in log if "to" in entry]
    seen = [entry["read_back"] for entry in moves if entry["read_back"]]
    return {
        "moves": len(moves),
        "read_back_equal_to_target": all(entry["read_back"] == entry["to"] for entry in moves),
        "read_back_box": [
            min(x for x, _ in seen),
            min(y for _, y in seen),
            max(x for x, _ in seen),
            max(y for _, y in seen),
        ]
        if seen
        else None,
        "slowest_read_back_ms": max((entry["ms"] for entry in moves), default=None),
        "buttons": [entry for entry in log if "to" not in entry],
    }


def without_html(record: dict[str, Any]) -> dict[str, Any]:
    transfer = record.get("transfer")
    if not transfer or "html" not in transfer:
        return record
    html = transfer["html"]
    return record | {"transfer": {**transfer, "html": f"<{len(html)} characters>"}}


def calibrate() -> int:
    """Opens Dolphin on the three-file case and prints where AT-SPI puts its items (relative
    to the client area, which starts below KWin's title bar)."""
    with tempfile.TemporaryDirectory(prefix="reframe-spike-drop-") as tmp:
        root = Path(tmp)
        files = make_files(root / "files")
        xdg = private_xdg(root / "xdg") | {"QT_LINUX_ACCESSIBILITY_ALWAYS_ON": "1"}
        with windows.Session() as session:
            process = session.spawn(
                [b"dolphin", b"--new-window", b"--select", *files["three-files"]],
                DOLPHIN_SPOT,
                env=xdg,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            try:
                placed = session.window(process.pid)
                time.sleep(2.0)
                names = [os.fsdecode(os.path.basename(path)) for path in files["three-files"]]
                answer = subprocess.run(
                    ["/usr/bin/python3", "-I", "-c", ATSPI, str(process.pid), *names],
                    capture_output=True,
                    text=True,
                    timeout=30,
                    check=True,
                )
            finally:
                windows.terminate(process)
        print(json.dumps({"dolphin": placed.summary()}))
        print(json.dumps({"items": json.loads(answer.stdout)}, ensure_ascii=False))
        print(json.dumps({"scripts_loaded_after": session.unloaded()}))
    return 0


def run_cases(
    session: windows.Session,
    device: pointer.Pointer,
    target: list[str],
    env: dict[str, str],
    files: dict[str, list[bytes]],
    xdg: dict[str, str],
    only: list[str] | None,
) -> dict[str, Any]:
    result: dict[str, Any] = {"cases": {}}
    assert device.device is not None
    result["pointer_device"] = pointer.check_device(device.device)
    # KWin puts a new window on the output under the cursor.
    screen = session.screen
    device.move(screen.x + 900, screen.y + 1000)
    app_process = session.spawn(
        target,
        APP_SPOT,
        env=env,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=trace("app"),
    )
    lines = Lines(app_process)
    try:
        app_window = session.window(app_process.pid)
        result["app_window"] = app_window.summary()
        if lines.wait(lambda record: is_drop_log(record, "page", "ready"), 20) is None:
            raise RuntimeError("the drop page did not report ready")
        run = Run(session, device, lines, app_window.rect, xdg)
        for name, _ in CASES:
            if only and name not in only:
                continue
            dolphin, rect = run.dolphin(files[name], name)
            try:
                time.sleep(1.5)
                items = dolphin_items(dolphin.pid, files[name])
                start = item_point(rect, items) or (rect.x + FILE_ITEM[0], rect.y + FILE_ITEM[1])
                outcome = run.drag(start)
                outcome["dolphin_items"] = items
            finally:
                windows.terminate(dolphin)
                session.give_back()
            records = outcome.pop("records", [])
            outcome["dolphin_window"] = rect.as_list()
            outcome["sent"] = [
                {"hex": path.hex(), "exists": os.path.exists(path)} for path in files[name]
            ]
            outcome |= summarise(records)
            outcome["raw"] = [without_html(record) for record in records]
            result["cases"][name] = outcome
    finally:
        assert app_process.stdin is not None
        app_process.stdin.write(b"quit\n")
        app_process.stdin.flush()
        try:
            result["app_exit"] = app_process.wait(15)
        except subprocess.TimeoutExpired:
            result["app_exit"] = windows.terminate(app_process)
    return result


def run_session(
    kind: str, tauri_handler: bool, only: list[str] | None, gtk: bool = False
) -> dict[str, Any]:
    before = owner_files()
    result: dict[str, Any] = {
        "session": kind,
        "target": "gtk" if gtk else "app",
        "tauri_handler": tauri_handler,
        "dolphin": subprocess.run(
            ["dolphin", "--version"], capture_output=True, text=True
        ).stdout.strip(),
    }
    with tempfile.TemporaryDirectory(prefix="reframe-spike-drop-") as tmp:
        root = Path(tmp)
        files = make_files(root / "files")
        result["root"] = str(root / "files")
        xdg = private_xdg(root / "xdg") | {"QT_LINUX_ACCESSIBILITY_ALWAYS_ON": "1"}
        extra = {"REFRAME_SPIKE_PAGE": "drop", "REFRAME_SPIKE_WINDOW_SIZE": "1240x760"}
        if not tauri_handler:
            extra["REFRAME_SPIKE_NO_DRAG_DROP"] = "1"
        env = spike_app.environment(root / "home", unfrozen=False, extra=extra)
        if kind == "xwayland":
            env["GDK_BACKEND"] = "x11"
        if TRACE is not None:
            env["WAYLAND_DEBUG"] = xdg["WAYLAND_DEBUG"] = "1"
        # Dolphin takes the keyboard at each press: it goes back after each case (give_back).
        with windows.Session(cursor=True, guard=False) as session:
            device = pointer.for_session(session.journal, session.screen)
            with device:
                try:
                    target = ["/usr/bin/python3", "-I", "-c", GTK_TARGET] if gtk else [str(APP)]
                    result |= run_cases(session, device, target, env, files, xdg, only)
                finally:
                    result["pointer"] = pointer_summary(device.log)
        result["windows"] = [placed.summary() for placed in session.placed]
        result["focus"] = [
            {key: value for key, value in record.items() if key not in ("seen", "t")}
            for record in session.journal.seen
            if record["event"] in ("loaded", "kept_active", "active")
        ]
        result["popups"] = [
            record
            for record in session.journal.seen
            if record["event"] == "added" and not (record["normal"] or record["dialog"])
        ]
        result["scripts_loaded_after"] = session.unloaded()
    result["owner_dolphin_files"] = {"before": before, "after": owner_files()}
    result["device_left"] = pointer.NAME in Path("/proc/bus/input/devices").read_text()
    return result


TRACE: Path | None = None
"""``--trace``: the folder for the Wayland protocol logs of the app and of each Dolphin."""


def trace(name: str) -> Any:
    if TRACE is None:
        return subprocess.DEVNULL
    return (TRACE / f"{name}.log").open("wb")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--session", choices=["wayland", "xwayland"], default="wayland")
    parser.add_argument(
        "--handler",
        choices=["tauri", "dom", "both"],
        default="both",
        help="tauri: Tauri's drop handler on; dom: off, the page gets WebKitGTK's drop",
    )
    parser.add_argument("--case", action="append", help="only these cases")
    parser.add_argument(
        "--gtk", action="store_true", help="drop on a plain GTK 3 target instead of the app"
    )
    parser.add_argument("--json", type=Path, help="write the results here")
    parser.add_argument("--trace", type=Path, help="WAYLAND_DEBUG logs of the app and Dolphin")
    parser.add_argument(
        "--calibrate", action="store_true", help="print where Dolphin's items are and stop"
    )
    args = parser.parse_args(argv)
    windows.stop_on_signals()
    if args.calibrate:
        return calibrate()
    global TRACE
    TRACE = args.trace
    handlers = {"tauri": [True], "dom": [False], "both": [True, False]}[args.handler]
    if args.gtk:
        handlers = [True]
    runs = [run_session(args.session, handler, args.case, args.gtk) for handler in handlers]
    text = json.dumps({"runs": runs}, indent=1, ensure_ascii=False)
    if args.json:
        out = args.json if args.json.is_absolute() else SPIKE / args.json
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
