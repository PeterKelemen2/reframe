"""Encoder capabilities: which encoders this FFmpeg build and this computer can use.

Detection returns statuses, never exceptions, and every probe has a strict timeout, so a
broken encoder cannot freeze the caller.
"""

from reframe.capabilities.cache import CacheKey, CapabilityCache, cache_key
from reframe.capabilities.detect import (
    LIST_TIMEOUT,
    MAX_PARALLEL_TESTS,
    NOT_IN_BUILD,
    DetectionOptions,
    current_os,
    detect_capabilities,
    vaapi_nodes,
)
from reframe.capabilities.devices import render_nodes
from reframe.capabilities.fingerprint import gpu_fingerprint
from reframe.capabilities.hwtest import (
    DEFAULT_VAAPI_DEVICE,
    FILTER_TESTS,
    TEST_TIMEOUT,
    filter_test_argv,
    hardware_test_argv,
    run_filter_test,
    run_hardware_test,
    uses_vaapi_device,
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
    "FILTER_TESTS",
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
    "filter_test_argv",
    "gpu_fingerprint",
    "hardware_test_argv",
    "parse_encoder_help",
    "parse_encoders",
    "parse_filters",
    "render_nodes",
    "run_filter_test",
    "run_hardware_test",
    "uses_vaapi_device",
    "vaapi_nodes",
]
