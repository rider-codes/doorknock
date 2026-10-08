"""Keep the job list current without anyone pressing a button.

Whenever the app is running and the last read of the job boards is older than AUTO_REFRESH_HOURS, it reads them again, so
a person who comes back after days (or a new person running the app) sees the latest postings first. 0 turns this off."""
import logging
import threading
import time
from datetime import datetime, timezone

from sqlalchemy import select

from . import config, pipeline, store
from .db import session_scope
from .models import Run

log = logging.getLogger("doorknock.refresh")
CHECK_EVERY = 15 * 60  # seconds between looks at whether a refresh is due
FIRST_CHECK = 20  # let the app finish starting before the first look
_started = False


def hours() -> float:
    try:
        return max(0.0, float(config.env("AUTO_REFRESH_HOURS", "6")))
    except ValueError:
        return 6.0


def last_refreshed(s) -> datetime | None:
    """When the job boards were last read successfully (a later stage failing does not undo that)."""
    for run in s.execute(select(Run).order_by(Run.id.desc()).limit(30)).scalars():
        stamp = (run.detail or {}).get("fetched_at")
        if stamp:
            return datetime.fromisoformat(stamp)
    return None


def due(s) -> bool:
    if hours() <= 0 or store.latest_profile(s) is None:
        return False  # nothing to match against yet
    last = last_refreshed(s)
    return last is None or (datetime.now(timezone.utc) - last).total_seconds() > hours() * 3600


def refresh_if_due() -> bool:
    with session_scope() as s:
        if not due(s):
            return False
    stages = ["fetch", "filter", "hydrate", "rank", "relevance", "score"]
    if not config.llm_ready():
        stages = stages[:4]  # without an AI key only the free steps run
    try:
        pipeline.run_pipeline(stages, 15)
    except RuntimeError:
        return False  # a search is already running
    log.info("automatic refresh started")
    return True


def _loop() -> None:
    time.sleep(FIRST_CHECK)
    while True:
        try:
            refresh_if_due()
        except Exception:  # never let the timer thread die
            log.exception("automatic refresh check failed")
        time.sleep(CHECK_EVERY)


def start() -> None:
    global _started
    if _started or hours() <= 0:
        return
    _started = True
    threading.Thread(target=_loop, daemon=True, name="auto-refresh").start()
