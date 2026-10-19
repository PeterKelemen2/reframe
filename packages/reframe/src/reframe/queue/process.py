"""Pause and resume a running step: psutil ``suspend()`` and ``resume()`` on its process tree.

The tree matters, because a wrapper such as a ``.cmd`` launcher may run FFmpeg as a child. The
caller keeps the root's ``psutil.Process`` from the step's start: psutil checks its start time
before it signals, so a pid that the OS gave to another process is never touched.
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
    """Suspend ``root`` first, so it cannot start a child meanwhile, then its descendants.
    Returns how many processes were suspended."""
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
