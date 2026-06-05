"""Scheduled-collection config: load `schedules.yaml` + decide what is due.

A schedule is a saved collection prompt that fires every day at a given local
time. `due_schedules` is a pure function (the testable core); the running loop
lives in `scheduler.py`. The config file is the authorization point — only
someone who can write the filesystem can add a schedule — so the collect
passcode allowlist does not apply to scheduled runs.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)

DEFAULT_SCHEDULES = Path(__file__).resolve().parents[3] / "config" / "schedules.yaml"


@dataclass(frozen=True)
class Schedule:
    name: str
    hour: int
    minute: int
    prompt: str
    enabled: bool = True


def _schedules_path(path=None) -> Path:
    if path is not None:
        return Path(path)
    return Path(os.environ.get("AISHELF_SCHEDULES", DEFAULT_SCHEDULES))


def _parse_time(value) -> tuple[int, int]:
    """Parse 'HH:MM' into (hour, minute); raise ValueError on anything else."""
    hh, mm = str(value).split(":")
    hour, minute = int(hh), int(mm)
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise ValueError(f"time out of range: {value!r}")
    return hour, minute


def _parse_entry(entry) -> Schedule:
    if not isinstance(entry, dict):
        raise ValueError(f"entry is not a mapping: {entry!r}")
    name = entry.get("name")
    prompt = entry.get("prompt")
    if not name or not str(name).strip():
        raise ValueError("missing name")
    if not prompt or not str(prompt).strip():
        raise ValueError(f"schedule {name!r} missing prompt")
    hour, minute = _parse_time(entry.get("time"))
    return Schedule(
        name=str(name).strip(),
        hour=hour,
        minute=minute,
        prompt=str(prompt),
        enabled=bool(entry.get("enabled", True)),
    )


def load_schedules(path=None) -> list[Schedule]:
    """Read schedules from YAML; skip+log malformed entries, dedup names.

    A missing/empty/unreadable file yields an empty list.
    """
    try:
        raw = yaml.safe_load(_schedules_path(path).read_text(encoding="utf-8"))
    except OSError:
        return []
    except yaml.YAMLError as exc:
        logger.warning("unreadable schedules file: %s", exc)
        return []
    if not isinstance(raw, dict):
        return []
    entries = raw.get("schedules") or []
    out: list[Schedule] = []
    seen: set[str] = set()
    for entry in entries:
        try:
            sched = _parse_entry(entry)
        except (ValueError, TypeError) as exc:
            logger.warning("skipping malformed schedule: %s", exc)
            continue
        if sched.name in seen:
            logger.warning("duplicate schedule name %r, keeping first", sched.name)
            continue
        seen.add(sched.name)
        out.append(sched)
    return out


def due_schedules(schedules: list[Schedule], state: dict[str, str], now: datetime) -> list[Schedule]:
    """Schedules that should run at `now`: enabled, past today's fire time, and
    not already run today (per `state`, mapping name -> last-run ISO date).
    """
    today = now.date().isoformat()
    due = []
    for s in schedules:
        if not s.enabled:
            continue
        fire = now.replace(hour=s.hour, minute=s.minute, second=0, microsecond=0)
        if now >= fire and state.get(s.name) != today:
            due.append(s)
    return due
