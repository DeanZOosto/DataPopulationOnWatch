"""
Job execution for OnWatch Population Hub.

Runs population and validation in background threads, captures logs and progress
events, and mirrors both to the durable :mod:`web.job_store` so a run can be
followed from a fresh page load, a second tab, or after a server restart.
"""
import asyncio
import logging
from collections import deque

from web import job_store

# -----------------------------------------------------------------------------
# Logging handlers — capture logs and progress for streaming to UI
# -----------------------------------------------------------------------------

LOG_QUEUE_MAX = 5000
PROGRESS_QUEUE_MAX = 500


class QueueLogHandler(logging.Handler):
    """Capture log records to a deque (live) and to the durable store."""

    def __init__(self, job_id, log_queues, jobs_lock):
        super().__init__()
        self.job_id = job_id
        self._queues = log_queues
        self._lock = jobs_lock

    def emit(self, record):
        try:
            msg = self.format(record)
            job_store.append_log(self.job_id, msg)
            with self._lock:
                if self.job_id in self._queues:
                    q = self._queues[self.job_id]
                    q.append(msg)
                    while len(q) > LOG_QUEUE_MAX:
                        q.popleft()
        except Exception:
            pass


class ProgressLogHandler(logging.Handler):
    """Turn WARNING/ERROR logs into progress events for the UI.

    De-duplicates identical messages within a run: the engine logs the same
    warning once per item in some loops (e.g. per subject/per file), which used
    to flood the progress panel with repeated lines. We keep only the first
    occurrence of each (level, message) pair.
    """

    def __init__(self, job_id, progress_queues, jobs_lock):
        super().__init__()
        self.job_id = job_id
        self._queues = progress_queues
        self._lock = jobs_lock
        self._seen = set()

    def emit(self, record):
        try:
            if record.levelno < logging.WARNING:
                return
            # Skip noisy third-party warnings; the operator cares about our own.
            if record.name.split(".")[0] in ("urllib3", "paramiko", "asyncio", "werkzeug"):
                return
            # Skip the end-of-run summary recap: RunSummary re-logs every error and
            # warning as an aggregated report, but the panel already showed each one
            # live during its step. Capturing the recap too is the duplicate the
            # operator sees. The results card still carries the manual checklist.
            if record.name == "run_summary":
                return
            msg = (self.format(record) or "").strip()
            if not msg:
                return
            event_type = "error" if record.levelno >= logging.ERROR else "warning"
            key = (event_type, msg)
            if key in self._seen:
                return
            self._seen.add(key)
            event = {"type": event_type, "message": msg}
            job_store.append_event(self.job_id, event)
            with self._lock:
                if self.job_id in self._queues:
                    q = self._queues[self.job_id]
                    q.append(event)
                    while len(q) > PROGRESS_QUEUE_MAX:
                        q.popleft()
        except Exception:
            pass


# -----------------------------------------------------------------------------
# Job setup — attach logging handlers, create progress callback
# -----------------------------------------------------------------------------

LOG_FORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
LOG_DATE_FMT = "%Y-%m-%d %H:%M:%S"


def attach_job_handlers(job_id, log_queues, progress_queues, jobs_lock):
    """
    Attach logging handlers for a job. Returns (log_handler, progress_handler, progress_callback).
    Caller must remove handlers in finally block.
    """
    log_handler = QueueLogHandler(job_id, log_queues, jobs_lock)
    log_handler.setFormatter(logging.Formatter(LOG_FORMAT, datefmt=LOG_DATE_FMT))

    progress_handler = ProgressLogHandler(job_id, progress_queues, jobs_lock)
    progress_handler.setFormatter(logging.Formatter("%(message)s"))
    progress_handler.setLevel(logging.WARNING)

    def progress_callback(event):
        # Persist first so a reconnecting/late client replays every event,
        # then fan out to any live in-process listener.
        try:
            job_store.append_event(job_id, event)
        except Exception:
            pass
        with jobs_lock:
            if job_id in progress_queues:
                progress_queues[job_id].append(event)

    root = logging.getLogger()
    root.addHandler(log_handler)
    root.addHandler(progress_handler)

    return log_handler, progress_handler, progress_callback


def detach_job_handlers(log_handler, progress_handler):
    """Remove logging handlers from root logger."""
    root = logging.getLogger()
    root.removeHandler(log_handler)
    root.removeHandler(progress_handler)


def _checkpoint_name(user_name):
    """Mirror RunSummary's checkpoint filename so the UI can point at partial data."""
    safe = "".join(c for c in (user_name or "") if c.isalnum() or c == "_").strip("_") or "onwatch"
    return f"{safe}_data_inserted_checkpoint.yaml"


# -----------------------------------------------------------------------------
# Population job
# -----------------------------------------------------------------------------

def run_population(job_id, jobs, log_queues, progress_queues, jobs_lock, user_name=None, target=None):
    """Run population automation in thread. Updates jobs[job_id] with result."""
    with jobs_lock:
        jobs[job_id] = {"type": "population", "status": "running", "logs": [], "result": None}
        log_queues[job_id] = deque(maxlen=LOG_QUEUE_MAX)
        progress_queues[job_id] = deque(maxlen=PROGRESS_QUEUE_MAX)

    meta = {"user_name": user_name, "checkpoint": _checkpoint_name(user_name)}
    if target:
        meta["target"] = target
    job_store.init_job(job_id, "population", meta)

    log_handler, progress_handler, progress_callback = attach_job_handlers(
        job_id, log_queues, progress_queues, jobs_lock
    )

    try:
        from main import OnWatchAutomation

        automation = OnWatchAutomation(
            config_path="config.yaml",
            progress_callback=progress_callback,
            export_name=user_name,
        )
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        export_path = loop.run_until_complete(automation.run())
        result = _build_population_result(automation, export_path)
    except Exception as e:
        result = {"success": False, "error": str(e)}
    finally:
        detach_job_handlers(log_handler, progress_handler)
        with jobs_lock:
            jobs[job_id]["status"] = "done"
            jobs[job_id]["result"] = result
            if job_id in log_queues:
                del log_queues[job_id]
        job_store.set_status(job_id, "done", result=result)


def _build_population_result(automation, export_path):
    """Build result dict from automation summary."""
    steps = automation.summary.steps
    failed_steps = sum(1 for s in steps.values() if s["status"] == "failed")
    errors = list(automation.summary.errors)
    return {
        # Mirror run()'s completion logic: item-level errors (e.g. cameras blocked
        # by an expired license) mean the run did not fully succeed.
        "success": failed_steps == 0 and len(errors) == 0,
        "errors_count": len(errors),
        "errors": errors,
        "export_path": str(export_path) if export_path else None,
        "run_status": {
            "total_steps": len(steps),
            "successful_steps": sum(1 for s in steps.values() if s["status"] == "success"),
            "failed_steps": failed_steps,
            "skipped_steps": sum(1 for s in steps.values() if s["status"] == "skipped"),
        },
        "duration": automation.summary.format_duration(automation.summary.get_total_duration()),
        "manual_checklist": automation.summary.get_manual_checklist_for_ui(),
    }


# -----------------------------------------------------------------------------
# Validation job
# -----------------------------------------------------------------------------

def run_validation(job_id, export_file, jobs, log_queues, progress_queues, jobs_lock, target=None):
    """Run validation in thread. Updates jobs[job_id] with result."""
    with jobs_lock:
        jobs[job_id] = {"type": "validation", "status": "running", "logs": [], "result": None}
        log_queues[job_id] = deque(maxlen=LOG_QUEUE_MAX)
        progress_queues[job_id] = deque(maxlen=PROGRESS_QUEUE_MAX)

    meta = {"export_file": export_file}
    if target:
        meta["target"] = target
    job_store.init_job(job_id, "validation", meta)

    log_handler, progress_handler, progress_callback = attach_job_handlers(
        job_id, log_queues, progress_queues, jobs_lock
    )

    try:
        from validate_data import DataValidator

        validator = DataValidator(export_file, config_path="config.yaml", progress_callback=progress_callback)
        success = validator.validate()
        result = _build_validation_result(validator, success)
    except Exception as e:
        result = {"success": False, "error": str(e)}
    finally:
        detach_job_handlers(log_handler, progress_handler)
        with jobs_lock:
            jobs[job_id]["status"] = "done"
            jobs[job_id]["result"] = result
            if job_id in log_queues:
                del log_queues[job_id]
        job_store.set_status(job_id, "done", result=result)


def _build_validation_result(validator, success):
    """Build result dict from validator results."""
    checklist = validator._manual_verification_checklist()
    manual_checklist = [line.strip() for line in checklist[1:] if line.strip()] if len(checklist) > 1 else []
    return {
        "success": success,
        "validated": validator.results.get("validated", 0),
        "passed": validator.results.get("passed", 0),
        "failed": validator.results.get("failed", 0),
        "errors": validator.results.get("errors", []),
        "skipped": validator.results.get("skipped", []),
        "acknowledged": validator.results.get("acknowledged", []),
        "manual_checklist": manual_checklist,
    }
