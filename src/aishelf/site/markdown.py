"""Render user-authored markdown to sanitized HTML for inline display.

The author is the only trusted local user, so sanitizing is cheap defense in
depth (strip <script>, inline event handlers, javascript: URLs). Rendering
never raises: on any failure it falls back to escaped plain text so a page
can't be crashed by malformed input.
"""

from __future__ import annotations

import html
import logging

import nh3
from markdown_it import MarkdownIt

logger = logging.getLogger(__name__)

_MD = MarkdownIt("commonmark", {"linkify": True})


def _render(text: str) -> str:
    """Markdown -> raw HTML (may contain anything the source asked for)."""
    return _MD.render(text)


def render_markdown(text: str) -> str:
    """Render markdown to sanitized HTML; '' for empty, escaped text on error."""
    if not text:
        return ""
    try:
        raw = _render(text)
        return nh3.clean(raw)
    except Exception as exc:  # never let a bad post crash the page
        logger.warning("markdown render failed, falling back to plain text: %s", exc)
        return html.escape(text)
