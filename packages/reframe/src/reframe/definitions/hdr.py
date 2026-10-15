"""**Copy HDR metadata from source** (03 §Advanced encoder options): the encoder's HDR options
filled from the probe (mastering display, MaxCLL / MaxFALL).

Contract stub: built by the C-6 option-sets task (wave 1e). ``Reframe.jobs.hdr_metadata``
turns the values into a JSON patch on ``/video/advanced``.
"""

from __future__ import annotations

from reframe.definitions.models import VideoEncoderDef
from reframe.models.job import OptionValue
from reframe.models.media import VideoStream

__all__ = ["hdr_options"]


def hdr_options(encoder: VideoEncoderDef, stream: VideoStream) -> dict[str, OptionValue]:
    """``VideoSettings.advanced`` values (option key → value) that carry ``stream``'s HDR10
    metadata with ``encoder``'s own options (x265 ``master-display`` / ``max-cll``, SVT-AV1
    and others where they exist). Empty when the stream has no HDR10 metadata or the encoder
    has no such options. Pure."""
    raise NotImplementedError("C-6 HDR metadata")
