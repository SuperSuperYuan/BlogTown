"""In-process scheduler for timed Hermes collection.

A background thread (started from the FastAPI lifespan when
`AISHELF_SCHEDULER_ENABLED` is set) wakes every `TICK_SECONDS` and runs any
schedule that is due. State is persisted per run so a missed run — e.g. the
machine was asleep at the scheduled time — is caught up on the next tick.
Each run is isolated: one failing schedule is logged and retried next tick,
without blocking the others or killing the thread.
"""

from __future__ import annotations

import logging
import threading
from datetime import datetime

from aishelf.db import sync as db_sync
from aishelf.db.config import default_db_path
from aishelf.site import collect, schedule_state, schedules
from aishelf.site.config import get_data_dir

logger = logging.getLogger(__name__)

TICK_SECONDS = 60


def run_due_now(now: datetime | None = None) -> list[str]:
    """Run every schedule due at `now`; return the names that ran.

    Successful runs record today's date so they don't repeat; a failing run is
    logged and left unrecorded so it retries on the next tick.
    """
    now = now or datetime.now()
    data_dir = get_data_dir()
    state = schedule_state.load_state(data_dir)
    due = schedules.due_schedules(schedules.load_schedules(), state, now)
    ran: list[str] = []
    for s in due:
        try:
            summary = collect.run_once(s.prompt)
        except Exception as exc:  # never let one schedule kill the loop
            logger.warning("scheduled collection %r failed: %s", s.name, exc)
            continue
        state[s.name] = now.date().isoformat()
        schedule_state.save_state(data_dir, state)
        ran.append(s.name)
        logger.info("scheduled collection %r ran: %s", s.name, summary)
    if ran:
        try:
            summary = db_sync.sync(data_dir, default_db_path(data_dir))
            logger.info("DB synced after scheduled collection: %s", summary)
        except Exception as exc:  # derived DB; failure is recoverable, never fatal
            logger.warning("DB sync after scheduled collection failed: %s", exc)
    return ran


def _loop(stop: threading.Event) -> None:
    while not stop.is_set():
        try:
            run_due_now()
        except Exception as exc:  # defense in depth: keep the thread alive
            logger.warning("scheduler tick failed: %s", exc)
        stop.wait(TICK_SECONDS)


def start(stop: threading.Event | None = None) -> threading.Event:
    """Start the background scheduler thread; return its stop Event."""
    stop = stop or threading.Event()
    thread = threading.Thread(target=_loop, args=(stop,), name="aishelf-scheduler", daemon=True)
    thread.start()
    logger.info("scheduler started (tick=%ss)", TICK_SECONDS)
    return stop
