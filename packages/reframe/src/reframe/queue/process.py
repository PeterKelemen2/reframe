"""Pause and resume a running step: psutil ``suspend()`` / ``resume()`` on the process tree
(03 §Queue: "Pause suspends the FFmpeg process … works on both OSes").

psutil sends ``SIGSTOP`` / ``SIGCONT`` on POSIX and calls ``NtSuspendProcess`` /
``NtResumeProcess`` on Windows, so the same code serves both. The tree matters: on Windows
the fake tools and ``.cmd`` launchers run as ``cmd.exe → python``, and a wrapper may run the
real FFmpeg as a child.

Order: suspend the root first (so it cannot start a new child while the children are being
suspended), then its descendants; resume the descendants first, then the root. A process that
is already gone is skipped. The root is a ``psutil.Process`` made when the step started: psutil
checks its start time before it sends a signal, so a pid that the OS gave to another process
is never touched.
"""

from __future__ import annotations

import contextlib

import psutil

__all__ = ["resume_tree", "suspend_tree"]


def _children(root: psutil.Process) -> list[psutil.Process]:
    try:
        return root.children(recursive=True)
    except psutil.Error:
        return []


def suspend_tree(root: psutil.Process) -> int:
    """Suspend ``root`` and its descendants; returns how many processes were suspended."""
    try:
        root.suspend()
    except psutil.Error:
        return 0
    count = 1
    for child in _children(root):
        with contextlib.suppress(psutil.Error):
            child.suspend()
            count += 1
    return count


def resume_tree(root: psutil.Process) -> int:
    """Resume the descendants of ``root``, then ``root``; returns how many were resumed."""
    count = 0
    for child in reversed(_children(root)):
        with contextlib.suppress(psutil.Error):
            child.resume()
            count += 1
    with contextlib.suppress(psutil.Error):
        root.resume()
        count += 1
    return count
