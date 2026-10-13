"""Encoder capabilities (C-4): which encoders this FFmpeg build and this computer can use.

Detection runs in the background, has strict timeouts and returns statuses, never
exceptions (it fixes the HandBrake freeze, 03 §Missing encoder behaviour).

- :class:`CapabilityService` (``Reframe.capabilities``): the cached result at once, detection
  in the background, ``capabilities.changed`` events, re-scan.
- :func:`detect_capabilities`: one detection run (``-encoders``, ``-filters``,
  ``-h encoder=<id>``, hardware test encodes).
- :func:`closest_available` and :func:`encoder_issues` (pure): the fallback chain and the
  ``encoder.*`` validation issues (C-8 registers them as its encoder rule).
- :func:`explain_failure`: the reason mapping of decision 0008.
"""

from reframe.capabilities.cache import CacheKey, CapabilityCache, cache_key
from reframe.capabilities.detect import (
    LIST_TIMEOUT,
    MAX_PARALLEL_TESTS,
    NOT_IN_BUILD,
    DetectionOptions,
    current_os,
    detect_capabilities,
)
from reframe.capabilities.fingerprint import gpu_fingerprint
from reframe.capabilities.hwtest import (
    DEFAULT_VAAPI_DEVICE,
    TEST_TIMEOUT,
    hardware_test_argv,
    run_hardware_test,
)
from reframe.capabilities.issues import closest_available, encoder_issues, field_pointer
from reframe.capabilities.parse import (
    EncoderHelp,
    EncoderListing,
    parse_encoder_help,
    parse_encoders,
    parse_filters,
)
from reframe.capabilities.reasons import Failure, TestContext, explain_failure
from reframe.capabilities.service import CapabilityService

__all__ = [
    "DEFAULT_VAAPI_DEVICE",
    "LIST_TIMEOUT",
    "MAX_PARALLEL_TESTS",
    "NOT_IN_BUILD",
    "TEST_TIMEOUT",
    "CacheKey",
    "CapabilityCache",
    "CapabilityService",
    "DetectionOptions",
    "EncoderHelp",
    "EncoderListing",
    "Failure",
    "TestContext",
    "cache_key",
    "closest_available",
    "current_os",
    "detect_capabilities",
    "encoder_issues",
    "explain_failure",
    "field_pointer",
    "gpu_fingerprint",
    "hardware_test_argv",
    "parse_encoder_help",
    "parse_encoders",
    "parse_filters",
    "run_hardware_test",
]
