"""
Durable job store for the OnWatch Population Hub.

Progress events, logs, and job metadata are persisted to ``runs/`` on disk so a
run survives a browser reload, a second browser tab, or a server restart:

* The progress SSE stream reads from the persisted event log, so a client that
  reconnects (or connects late) replays the whole run from the beginning and
  ends up with the correct UI state.
* On startup, any job still marked ``running`` is reconciled to ``interrupted``
  (its worker thread died with the previous process) so the UI degrades
  gracefully instead of hanging forever waiting for events that will never come.

The store is intentionally file-based and dependency-free: runs are small
(a few dozen progress events) and this keeps the hub a single ``pip install``
away from working on any operator laptop.
"""
import json
import threading
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
RUNS_DIR = PROJECT_ROOT / "runs"

# Keep at most this many runs on disk; older ones are pruned on each new run.
MAX_RUNS_KEPT = 50

_lock = threading.Lock()


def _ensure_dir():
    RUNS_DIR.mkdir(exist_ok=True)


def _meta_path(job_id):
    return RUNS_DIR / f"{job_id}.json"


def _events_path(job_id):
    return RUNS_DIR / f"{job_id}.events.jsonl"


def _log_path(job_id):
    return RUNS_DIR / f"{job_id}.log"


def init_job(job_id, job_type, meta=None):
    """Create the on-disk record for a new job and return its metadata dict."""
    _ensure_dir()
    data = {
        "job_id": job_id,
        "type": job_type,
        "status": "running",
        "started_at": time.time(),
        "updated_at": time.time(),
        "result": None,
    }
    if meta:
        data.update(meta)
    with _lock:
        _meta_path(job_id).write_text(json.dumps(data, default=str))
        # Truncate/create the event + log files.
        _events_path(job_id).write_text("")
        _log_path(job_id).write_text("")
    prune()
    return data


def append_event(job_id, event):
    """Append one progress event (a JSON-serialisable dict) to the run's log."""
    _ensure_dir()
    line = json.dumps(event, default=str)
    with _lock:
        with open(_events_path(job_id), "a", encoding="utf-8") as f:
            f.write(line + "\n")
            f.flush()


def append_log(job_id, text):
    """Append one formatted log line to the run's log file."""
    _ensure_dir()
    with _lock:
        with open(_log_path(job_id), "a", encoding="utf-8") as f:
            f.write(text.rstrip("\n") + "\n")


def set_status(job_id, status, result=None):
    """Update a job's status (and optionally its final result)."""
    with _lock:
        path = _meta_path(job_id)
        try:
            data = json.loads(path.read_text())
        except Exception:
            data = {"job_id": job_id}
        data["status"] = status
        data["updated_at"] = time.time()
        if result is not None:
            data["result"] = result
        path.write_text(json.dumps(data, default=str))


def read_meta(job_id):
    """Return the job's metadata dict, or ``None`` if unknown."""
    try:
        return json.loads(_meta_path(job_id).read_text())
    except Exception:
        return None


def read_events(job_id, offset=0):
    """Return the list of events for a job starting at ``offset``."""
    path = _events_path(job_id)
    if not path.exists():
        return []
    events = []
    with open(path, encoding="utf-8") as f:
        lines = f.readlines()
    for line in lines[offset:]:
        line = line.strip()
        if not line:
            continue
        try:
            events.append(json.loads(line))
        except Exception:
            continue
    return events


def count_events(job_id):
    """Return how many events have been persisted for a job."""
    path = _events_path(job_id)
    if not path.exists():
        return 0
    with open(path, encoding="utf-8") as f:
        return sum(1 for line in f if line.strip())


def read_log(job_id):
    """Return the full persisted log text for a job (empty string if none)."""
    path = _log_path(job_id)
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8", errors="replace")


def list_jobs():
    """Return all known jobs, newest first."""
    _ensure_dir()
    jobs = []
    for path in RUNS_DIR.glob("*.json"):
        try:
            jobs.append(json.loads(path.read_text()))
        except Exception:
            continue
    jobs.sort(key=lambda j: j.get("started_at", 0), reverse=True)
    return jobs


def running_job():
    """Return the most recent job still marked ``running``, or ``None``."""
    for job in list_jobs():
        if job.get("status") == "running":
            return job
    return None


def latest_job():
    """Return the most recent job of any status, or ``None``."""
    jobs = list_jobs()
    return jobs[0] if jobs else None


def mark_orphans_interrupted():
    """Reconcile jobs left ``running`` by a previous process to ``interrupted``.

    Called once at startup: a job marked running whose worker thread no longer
    exists (because the server restarted) must not leave the UI waiting forever.
    """
    reconciled = []
    for job in list_jobs():
        if job.get("status") == "running":
            set_status(job["job_id"], "interrupted")
            reconciled.append(job["job_id"])
    return reconciled


def prune(keep=MAX_RUNS_KEPT):
    """Delete on-disk records beyond the newest ``keep`` runs."""
    jobs = list_jobs()
    for job in jobs[keep:]:
        job_id = job.get("job_id")
        if not job_id:
            continue
        for path in (_meta_path(job_id), _events_path(job_id), _log_path(job_id)):
            try:
                path.unlink()
            except Exception:
                pass
