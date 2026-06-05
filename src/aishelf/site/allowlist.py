"""Collect access control: a hand-maintained passcode allowlist.

Only callers presenting a token listed in the allowlist file may trigger
Hermes collection. The file is the single choke point for "who can collect";
it is read per request, so edits take effect on the next call with no restart.
Fail-closed: a missing or empty allowlist denies everyone.
"""

from __future__ import annotations

import os
from pathlib import Path

DEFAULT_ALLOWLIST = Path(__file__).resolve().parents[3] / "config" / "collect_allowlist.txt"


def _allowlist_path(path=None) -> Path:
    if path is not None:
        return Path(path)
    return Path(os.environ.get("AISHELF_COLLECT_ALLOWLIST", DEFAULT_ALLOWLIST))


def load_tokens(path=None) -> set[str]:
    """Read the allowlist file into a set of valid tokens.

    One token per line. Blank lines and `#` comments (whole-line or inline)
    are ignored; surrounding whitespace is stripped. A missing or unreadable
    file yields an empty set.
    """
    try:
        text = _allowlist_path(path).read_text(encoding="utf-8")
    except OSError:
        return set()
    tokens = set()
    for line in text.splitlines():
        token = line.split("#", 1)[0].strip()
        if token:
            tokens.add(token)
    return tokens


def is_allowed(token, path=None) -> bool:
    """True only when a non-empty token is present in the allowlist."""
    if not token or not token.strip():
        return False
    return token.strip() in load_tokens(path)
