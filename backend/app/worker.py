"""Evaluation worker: `python -m app.worker`.

Jobs are rows in `report_evaluations` (PENDING/FAILED), so nothing is lost if the API or this process restarts.
Claiming is an atomic UPDATE (see evaluation.run_job), so several workers or an admin retry can never double-score.
Run it as a separate service with EVALUATION_MODE=worker on the API.
"""
import logging
import os
import signal
import time

from . import evaluation

log = logging.getLogger("arena.worker")
_stop = False


def _handle(signum, _frame):
    global _stop
    log.info("signal %s received; finishing the current job then exiting", signum)
    _stop = True


def main() -> None:
    logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"), format="%(asctime)s %(levelname)s %(name)s %(message)s")
    signal.signal(signal.SIGTERM, _handle)
    signal.signal(signal.SIGINT, _handle)
    interval = float(os.getenv("WORKER_INTERVAL_SECONDS", "10"))
    log.info("worker started (interval %.0fs)", interval)
    backoff = interval
    while not _stop:
        try:
            done = evaluation.run_pending(limit=int(os.getenv("WORKER_BATCH", "10")))
            if done:
                log.info("processed %d job(s): %s", len(done), {k[:8]: v for k, v in done.items()})
            backoff = interval
        except Exception as e:                       # DB blip etc.: keep running, back off up to 2 min
            log.error("worker cycle failed: %s", type(e).__name__)
            backoff = min(backoff * 2, 120)
        for _ in range(int(backoff * 2)):            # sleep in small steps so SIGTERM is honoured quickly
            if _stop:
                break
            time.sleep(0.5)
    log.info("worker stopped")


if __name__ == "__main__":
    main()
