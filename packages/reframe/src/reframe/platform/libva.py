"""Whether the system's libva can serve the bundled FFmpeg on Linux.

The bundled FFmpeg loads libva at run time and aborts, rather than failing, when a function it
calls is missing. Discovery then points the bundled FFmpeg at the libva shipped next to it.
"""

from __future__ import annotations

import ctypes
import functools

__all__ = ["NEEDED_FUNCTIONS", "SYSTEM_LIBRARIES", "system_libva_usable"]

#: The libva functions of the bundled FFmpeg that older libva releases lack (libva 2.20 has no
#: ``vaMapBuffer2``).
NEEDED_FUNCTIONS = ("vaMapBuffer2", "vaSyncBuffer", "vaSyncSurface2", "vaCopy")
SYSTEM_LIBRARIES = ("libva.so.2", "libva-drm.so.2")


@functools.cache
def system_libva_usable() -> bool:
    """True when the system has libva and libva-drm with every function in
    :data:`NEEDED_FUNCTIONS`. Never raises."""
    try:
        libva, _drm = (ctypes.CDLL(name) for name in SYSTEM_LIBRARIES)
    except OSError:
        return False
    return all(hasattr(libva, name) for name in NEEDED_FUNCTIONS)
