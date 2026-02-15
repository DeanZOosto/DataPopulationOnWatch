"""
OnWatch Data Population Hub - Web UI.

Centralized hub for running population, validation, viewing logs and results.
"""
import asyncio
import logging
import os
import sys
import threading
import uuid
from collections import deque
from pathlib import Path

import yaml
from flask import Flask, Response, jsonify, render_template, request

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)

app = Flask(__name__, template_folder="templates", static_folder="static")

# Job storage: job_id -> {type, status, logs, result}
jobs = {}
jobs_lock = threading.Lock()

# Log queue for streaming (max 5000 lines)
LOG_QUEUE_MAX = 5000
log_queues = {}  # job_id -> deque of log lines


class QueueLogHandler(logging.Handler):
    """Capture log records to a deque for streaming."""

    def __init__(self, job_id):
        super().__init__()
        self.job_id = job_id

    def emit(self, record):
        try:
            msg = self.format(record)
            with jobs_lock:
                if self.job_id in log_queues:
                    q = log_queues[self.job_id]
                    q.append(msg)
                    while len(q) > LOG_QUEUE_MAX:
                        q.popleft()
        except Exception:
            pass


def get_exports():
    """List export YAML files with metadata."""
    exports = []
    for f in sorted(Path(".").glob("onwatch_data_export_*.yaml"), key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            with open(f) as fp:
                data = yaml.safe_load(fp)
            meta = data.get("metadata", {})
            run_status = data.get("metadata", {}).get("run_status", {})
            exports.append({
                "filename": f.name,
                "path": str(f.absolute()),
                "mtime": f.stat().st_mtime,
                "generated_at": meta.get("generated_at", ""),
                "onwatch_ip": meta.get("onwatch_ip", ""),
                "onwatch_version": meta.get("onwatch_version", ""),
                "total_duration": meta.get("total_duration", ""),
                "successful_steps": run_status.get("successful_steps", 0),
                "failed_steps": run_status.get("failed_steps", 0),
                "skipped_steps": run_status.get("skipped_steps", 0),
                "total_steps": run_status.get("total_steps", 0),
            })
        except Exception:
            exports.append({"filename": f.name, "path": str(f.absolute()), "mtime": f.stat().st_mtime})
    return exports


def get_config_status():
    """Validate config and return status."""
    try:
        from config_manager import ConfigManager
        manager = ConfigManager("config.yaml")
        is_valid, errors = manager.validate_config(verbose=False)
        config = manager.load_config()
        onwatch = config.get("onwatch", {})
        return {
            "valid": is_valid,
            "errors": errors,
            "onwatch_ip": onwatch.get("ip_address", ""),
            "onwatch_version": onwatch.get("version", ""),
        }
    except Exception as e:
        return {"valid": False, "errors": [str(e)], "onwatch_ip": "", "onwatch_version": ""}


def run_population(job_id):
    """Run population in thread."""
    with jobs_lock:
        jobs[job_id] = {"type": "population", "status": "running", "logs": [], "result": None}
        log_queues[job_id] = deque(maxlen=LOG_QUEUE_MAX)

    handler = QueueLogHandler(job_id)
    handler.setFormatter(logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s", datefmt="%Y-%m-%d %H:%M:%S"))
    root = logging.getLogger()
    root.addHandler(handler)

    try:
        from main import OnWatchAutomation
        automation = OnWatchAutomation(config_path="config.yaml")
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(automation.run())
        export_path = automation.summary.export_to_file(format="yaml")
        result = {
            "success": True,
            "export_path": str(export_path) if export_path else None,
            "run_status": {
                "total_steps": len(automation.summary.steps),
                "successful_steps": sum(1 for s in automation.summary.steps.values() if s["status"] == "success"),
                "failed_steps": sum(1 for s in automation.summary.steps.values() if s["status"] == "failed"),
                "skipped_steps": sum(1 for s in automation.summary.steps.values() if s["status"] == "skipped"),
            },
            "duration": automation.summary.format_duration(automation.summary.get_total_duration()),
        }
    except Exception as e:
        result = {"success": False, "error": str(e)}
    finally:
        root.removeHandler(handler)
        with jobs_lock:
            jobs[job_id]["status"] = "done"
            jobs[job_id]["result"] = result
            if job_id in log_queues:
                del log_queues[job_id]


def run_validation(job_id, export_file):
    """Run validation in thread."""
    with jobs_lock:
        jobs[job_id] = {"type": "validation", "status": "running", "logs": [], "result": None}
        log_queues[job_id] = deque(maxlen=LOG_QUEUE_MAX)

    handler = QueueLogHandler(job_id)
    handler.setFormatter(logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s", datefmt="%Y-%m-%d %H:%M:%S"))
    root = logging.getLogger()
    root.addHandler(handler)

    try:
        from validate_data import DataValidator
        validator = DataValidator(export_file, config_path="config.yaml")
        success = validator.validate()
        checklist = validator._manual_verification_checklist()
        manual_checklist = [line.strip() for line in checklist[1:] if line.strip()] if len(checklist) > 1 else []
        result = {
            "success": success,
            "validated": validator.results.get("validated", 0),
            "passed": validator.results.get("passed", 0),
            "failed": validator.results.get("failed", 0),
            "errors": validator.results.get("errors", []),
            "skipped": validator.results.get("skipped", []),
            "acknowledged": validator.results.get("acknowledged", []),
            "manual_checklist": manual_checklist,
        }
    except Exception as e:
        result = {"success": False, "error": str(e)}
    finally:
        root.removeHandler(handler)
        with jobs_lock:
            jobs[job_id]["status"] = "done"
            jobs[job_id]["result"] = result
            if job_id in log_queues:
                del log_queues[job_id]


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/config/status")
def config_status():
    return jsonify(get_config_status())


@app.route("/api/exports")
def exports():
    return jsonify(get_exports())


@app.route("/api/run-population", methods=["POST"])
def start_population():
    job_id = str(uuid.uuid4())
    t = threading.Thread(target=run_population, args=(job_id,))
    t.daemon = True
    t.start()
    return jsonify({"job_id": job_id})


@app.route("/api/validate", methods=["POST"])
def start_validation():
    data = request.get_json() or {}
    export_file = data.get("file") or request.args.get("file")
    if not export_file:
        return jsonify({"error": "Missing 'file' parameter"}), 400
    job_id = str(uuid.uuid4())
    t = threading.Thread(target=run_validation, args=(job_id, export_file))
    t.daemon = True
    t.start()
    return jsonify({"job_id": job_id})


@app.route("/api/logs/<job_id>")
def stream_logs(job_id):
    def generate():
        with jobs_lock:
            q = log_queues.get(job_id, deque())
        seen = 0
        while True:
            with jobs_lock:
                job = jobs.get(job_id, {})
                q = log_queues.get(job_id, deque())
            if job.get("status") == "done" and seen >= len(q):
                break
            while seen < len(q):
                try:
                    line = q[seen]
                    seen += 1
                    yield f"data: {line}\n\n"
                except IndexError:
                    break
            import time
            time.sleep(0.2)
        yield "data: [DONE]\n\n"

    return Response(
        generate(),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.route("/api/status/<job_id>")
def job_status(job_id):
    with jobs_lock:
        job = jobs.get(job_id, {})
    if not job:
        return jsonify({"error": "Job not found"}), 404
    return jsonify({
        "type": job.get("type"),
        "status": job.get("status"),
        "result": job.get("result"),
    })


def main():
    print("OnWatch Data Population Hub")
    print("Open http://127.0.0.1:5000 in your browser")
    print("Press Ctrl+C to stop")
    app.run(host="127.0.0.1", port=5000, debug=False, threaded=True)


if __name__ == "__main__":
    main()
