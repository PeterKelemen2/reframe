"""Shared test infrastructure for Reframe: fake FFmpeg/FFprobe and fixture media helpers.

Not shipped. Imported by the core, server and end-to-end tests (pytest ``pythonpath``).

Modules:

- ``media``: the fixture media generator (``scripts/make-testdata.py``). ``ensure_fixture(name)``
  returns the path of a fixture and generates it if needed; ``probe(path)`` runs ffprobe.
- ``fake_tools``: ``make_fake_tools(dir, Scenario([...]))`` writes fake ``ffmpeg`` / ``ffprobe``
  launchers for fault-injection tests (sleep, hang, crash, driver errors, progress, ...).
- ``fake_ffmpeg``: the fake itself (a standalone script); ``fake_data/`` holds real FFmpeg
  output that it prints (``capture_fake_data.py`` refreshes it).
- ``capabilities``: helpers for encoder-detection tests (C-4): a tool-discovery stand-in and
  rules that replay the ``c4_*`` captures of the real test encodes.
- ``pytest_plugin``: fixtures ``fixture_media`` and ``fake_tools``; skips ``needs_ffmpeg``
  tests when there is no usable ffmpeg (fails them with ``REFRAME_REQUIRE_FFMPEG=1``).
  Registered for all tests in ``pyproject.toml``.
- ``vobsub``, ``boxfont``: helpers of the generator (VobSub writer, tiny TrueType font).
"""
