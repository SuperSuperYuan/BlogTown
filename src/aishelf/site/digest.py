"""Daily-digest assembly for the home page (pure).

Recent-by-collected_at items + one date-seeded "gem" from the older remainder,
each carrying its A-generated hook. No LLM, no caching — pure per-request
assembly. Mirrors the views.py / collide.py pure-logic pattern.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import datetime, timezone


@dataclass
class Entry:
    item: object       # a ContentItem (only .id/.type/.title/.collected_at are read)
    hook: str          # "" when no hook is available


@dataclass
class Digest:
    recent: list
    gem: "Entry | None"


def _collected_key(it):
    """ISO collected_at -> naive-UTC datetime for sorting; unparseable sorts last.

    Normalizes tz-aware values to naive UTC so a mix of aware/naive timestamps
    never raises when compared (same approach as the contract loader)."""
    raw = getattr(it, "collected_at", "") or ""
    try:
        dt = datetime.fromisoformat(raw)
    except ValueError:
        return datetime.min
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def build_digest(items, hooks, *, today, recent_n=5) -> Digest:
    """Recent collections + one date-seeded older gem, each with its hook.

    `items`: ContentItems (any order). `hooks`: {id: hook}. `today`: a date
    string seeding the gem so it is stable within a day. `recent` holds the
    `recent_n` most recently collected; `gem` is one random pick from the rest
    (None when there is none); the two are disjoint.
    """
    ordered = sorted(items, key=lambda it: (_collected_key(it), it.id), reverse=True)
    recent = [Entry(it, hooks.get(it.id, "")) for it in ordered[:recent_n]]
    older = ordered[recent_n:]
    gem = None
    if older:
        pick = random.Random(today).choice(older)
        gem = Entry(pick, hooks.get(pick.id, ""))
    return Digest(recent=recent, gem=gem)
