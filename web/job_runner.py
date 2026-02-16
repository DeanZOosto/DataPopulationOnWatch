"""
Job execution for OnWatch Population Hub.

Runs population and validation in background threads, captures logs and progress
events for streaming to the UI.
"""
import asyncio
import logging
from collections import deque

# -----------------------------------------------------------------------------
# Logging handlers — capture logs and progress for streaming to UI
# -----------------------------------------------------------------------------

LOG_QUEUE_MAX = 5000
PROGRESS_QUEUE_MAX = 500


class QueueLogHandler(logging.Handler):
    """Capture log records to a deque for streaming."""

    def __init__(self, job_id, log_queues, jobs_lock):
        super().__init__()
        self.job_id = job_id
        self._queues = log_queues
        self._lock = jobs_lock

    def emit(self, record):
        try:
            msg = self.format(record)
            with self._lock:
                if self.job_id in self._queues:
                    q = self._queues[self.job_id]
                    q.append(msg)
                    while len(q) > LOG_QUEUE_MAX:
                        q.popleft()
        except Exception:
            pass


class ProgressLogHandler(logging.Handler):
    """Capture WARNING and ERROR logs as progress events for UI."""

    def __init__(self, job_id, progress_queues, jobs_lock):
        super().__init__()
        self.job_id = job_id
        self._queues = progress_queues
        self._lock = jobs_lock

    def emit(self, record):
        try:
            if record.levelno < logging.WARNING:
                return
            msg = (self.format(record) or "").strip()
            if not msg:
                return
            event_type = "error" if record.levelno >= logging.ERROR else "warning"
            with self._lock:
                if self.job_id in self._queues:
                    q = self._queues[self.job_id]
                    q.append({"type": event_type, "message": msg})
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


# -----------------------------------------------------------------------------
# Population job
# -----------------------------------------------------------------------------

def run_population(job_id, jobs, log_queues, progress_queues, jobs_lock, user_name=None):
    """Run population automation in thread. Updates jobs[job_id] with result."""
    with jobs_lock:
        jobs[job_id] = {"type": "population", "status": "running", "logs": [], "result": None}
        log_queues[job_id] = deque(maxlen=LOG_QUEUE_MAX)
        progress_queues[job_id] = deque(maxlen=PROGRESS_QUEUE_MAX)

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


def _build_population_result(automation, export_path):
    """Build result dict from automation summary."""
    steps = automation.summary.steps
    return {
        "success": True,
        "export_path": str(export_path) if export_path else None,
        "run_status": {
            "total_steps": len(steps),
            "successful_steps": sum(1 for s in steps.values() if s["status"] == "success"),
            "failed_steps": sum(1 for s in steps.values() if s["status"] == "failed"),
            "skipped_steps": sum(1 for s in steps.values() if s["status"] == "skipped"),
        },
        "duration": automation.summary.format_duration(automation.summary.get_total_duration()),
    }


# -----------------------------------------------------------------------------
# Validation job
# -----------------------------------------------------------------------------

def run_validation(job_id, export_file, jobs, log_queues, progress_queues, jobs_lock):
    """Run validation in thread. Updates jobs[job_id] with result."""
    with jobs_lock:
        jobs[job_id] = {"type": "validation", "status": "running", "logs": [], "result": None}
        log_queues[job_id] = deque(maxlen=LOG_QUEUE_MAX)
        progress_queues[job_id] = deque(maxlen=PROGRESS_QUEUE_MAX)

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
