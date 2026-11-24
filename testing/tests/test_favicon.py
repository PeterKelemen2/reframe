"""The web app's favicons are the desktop app's icon files, and its page names them."""

from __future__ import annotations

from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
ICONS = REPO / "desktop" / "src-tauri" / "icons"
PUBLIC = REPO / "frontend" / "public"


def test_the_favicons_are_the_app_icon() -> None:
    assert (PUBLIC / "favicon.svg").read_bytes() == (ICONS / "source" / "reframe.svg").read_bytes()
    assert (PUBLIC / "favicon.ico").read_bytes() == (ICONS / "icon.ico").read_bytes()


def test_the_page_links_both_favicons() -> None:
    page = (REPO / "frontend" / "index.html").read_text("utf-8")
    assert '<link rel="icon" href="/favicon.svg" type="image/svg+xml" />' in page
    assert '<link rel="icon" href="/favicon.ico"' in page
