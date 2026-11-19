"""Persistent monitoring worker – runs independently of the dashboard.

    python -m app.worker            # from the backend/ directory

Schedules (configurable per provider in Settings → Sources):
  * each provider at its own interval (priority sources 45–60 min, others 120 min)
  * expiry sweep hourly, link verification every 3 h
  * re-scoring with fresh history daily 03:30, FX refresh daily 06:00
  * daily digest at DIGEST_HOUR (local time)
A heartbeat is written every minute so the dashboard can show worker health.
"""
from __future__ import annotations

import logging
import signal
import sys
from datetime import datetime, timedelta

from apscheduler.executors.pool import ThreadPoolExecutor
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.interval import IntervalTrigger

from . import duffel, notify, positioning, scanner
from .config import DIGEST_HOUR, TIMEZONE
from .db import Provider, Setting, init_db, session_scope, utcnow
from .fx import refresh_rates

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("worker")

sched = BlockingScheduler(timezone=TIMEZONE, executors={"default": ThreadPoolExecutor(3)},
                          job_defaults={"coalesce": True, "max_instances": 1, "misfire_grace_time": 600})
_intervals: dict[str, int] = {}


def heartbeat():
    with session_scope() as s:
        jobs = {j.id: j.next_run_time.isoformat() if j.next_run_time else None for j in sched.get_jobs()}
        s.merge(Setting(key="worker_heartbeat", value={"at": utcnow().isoformat(), "jobs": jobs}))


def _scan_job(key: str):
    res = scanner.run_provider(key)
    log.info("scan %s: %s", key, {k: v for k, v in res.items() if k not in ("new_ids", "dropped_ids")})


def sync_provider_jobs(initial: bool = False):
    """Pick up interval / enable changes made in the dashboard without restarting."""
    with session_scope() as s:
        provs = [(p.key, p.enabled, p.interval_minutes) for p in s.query(Provider).all()]
    for i, (key, enabled, interval) in enumerate(provs):
        job_id = f"scan:{key}"
        job = sched.get_job(job_id)
        if not enabled:
            if job:
                job.remove()
            continue
        if job and _intervals.get(key) == interval:
            continue
        first = datetime.now().astimezone() + timedelta(seconds=10 + 25 * i) if initial or not job else None
        if job:
            job.reschedule(IntervalTrigger(minutes=interval))
        else:
            sched.add_job(_scan_job, IntervalTrigger(minutes=interval), id=job_id, args=[key], next_run_time=first)
        _intervals[key] = interval
        log.info("scheduled %s every %s min", key, interval)


def main():
    init_db()
    scanner.ensure_seed()
    refresh_rates()
    sync_provider_jobs(initial=True)
    sched.add_job(sync_provider_jobs, "interval", minutes=2, id="sync")
    sched.add_job(heartbeat, "interval", minutes=1, id="heartbeat", next_run_time=datetime.now().astimezone())
    sched.add_job(scanner.expire_offers, "interval", hours=1, id="expire")
    sched.add_job(scanner.verify_links, "interval", hours=3, id="verify",
                  next_run_time=datetime.now().astimezone() + timedelta(minutes=8))
    sched.add_job(lambda: (positioning.refresh(), scanner.rescore_all()), "interval", hours=12, id="positioning",
                  next_run_time=datetime.now().astimezone() + timedelta(minutes=3))
    sched.add_job(positioning.refresh_dated, "interval", hours=6, id="positioning_dated")
    sched.add_job(duffel.check_top_flights, "interval", hours=4, id="live_check")
    sched.add_job(scanner.rescore_all, "cron", hour=3, minute=30, id="rescore")
    sched.add_job(scanner.backfill_images, "interval", hours=6, id="images",
                  next_run_time=datetime.now().astimezone() + timedelta(minutes=5))
    sched.add_job(lambda: refresh_rates(force=True), "cron", hour=6, minute=0, id="fx")
    sched.add_job(notify.send_daily_digest, "cron", hour=DIGEST_HOUR, minute=0, id="digest")

    def stop(*_):
        log.info("stopping worker")
        sched.shutdown(wait=False)
        sys.exit(0)

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)
    log.info("TravelEdge worker started")
    sched.start()


if __name__ == "__main__":
    main()
