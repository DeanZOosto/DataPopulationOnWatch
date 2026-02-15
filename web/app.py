"""
OnWatch Data Population Hub - Web UI.

Centralized hub for running population, validation, viewing progress and results.
"""
import json
import os
import sys
import threading
import time
import uuid
from collections import deque
from pathlib import Path

import yaml
from flask import Flask, Response, jsonify, render_template, request

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)

from web.job_runner import run_population, run_validation

# -----------------------------------------------------------------------------
# Flask app and shared state
# -----------------------------------------------------------------------------

app = Flask(__name__, template_folder="templates", static_folder="static")

jobs = {}
jobs_lock = threading.Lock()
log_queues = {}
progress_queues = {}


# -----------------------------------------------------------------------------
# Data helpers — exports, config status
# -----------------------------------------------------------------------------

def get_exports():
    """List export YAML files with metadata, newest first."""
    exports = []
    for f in sorted(Path(".").glob("onwatch_data_export_*.yaml"), key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            with open(f) as fp:
                data = yaml.safe_load(fp)
            meta = data.get("metadata", {})
            run_status = meta.get("run_status", {})
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
    """Validate config and return status for UI."""
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


# -----------------------------------------------------------------------------
# SSE stream generators
# -----------------------------------------------------------------------------

def _stream_progress_generator(job_id):
    """Yield progress events as SSE JSON until job is done."""
    seen = 0
    while True:
        with jobs_lock:
            job = jobs.get(job_id, {})
            q = progress_queues.get(job_id, deque())
        if job.get("status") == "done" and seen >= len(q):
            break
        while seen < len(q):
            try:
                ev = q[seen]
                seen += 1
                yield f"data: {json.dumps(ev)}\n\n"
            except (IndexError, TypeError):
                break
        time.sleep(0.2)
    with jobs_lock:
        if job_id in progress_queues:
            del progress_queues[job_id]
    yield 'data: {"type":"stream_done"}\n\n'


def _stream_logs_generator(job_id):
    """Yield log lines as SSE until job is done."""
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
        time.sleep(0.2)
    yield "data: [DONE]\n\n"


# -----------------------------------------------------------------------------
# Routes — pages
# -----------------------------------------------------------------------------

@app.route("/")
def index():
    return render_template("index.html")


# -----------------------------------------------------------------------------
# Routes — config API
# -----------------------------------------------------------------------------

@app.route("/api/config/status")
def config_status():
    return jsonify(get_config_status())


@app.route("/api/config/set-ip", methods=["POST"])
def set_ip():
    data = request.get_json() or {}
    new_ip = (data.get("ip") or request.form.get("ip") or "").strip()
    if not new_ip:
        return jsonify({"success": False, "message": "IP address is required"}), 400
    try:
        from config_manager import ConfigManager
        manager = ConfigManager("config.yaml")
        success, message = manager.update_ip_address(new_ip, backup=True)
        return jsonify({"success": success, "message": message})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500


@app.route("/api/config/set-version", methods=["POST"])
def set_version():
    data = request.get_json() or {}
    version = (data.get("version") or request.form.get("version") or "").strip()
    if version not in ("2.6", "2.8"):
        return jsonify({"success": False, "message": "Version must be 2.6 or 2.8"}), 400
    try:
        from config_manager import ConfigManager
        manager = ConfigManager("config.yaml")
        success, message = manager.update_version(version, backup=True)
        return jsonify({"success": success, "message": message})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500


# -----------------------------------------------------------------------------
# Routes — exports
# -----------------------------------------------------------------------------

@app.route("/api/exports")
def exports():
    return jsonify(get_exports())


# -----------------------------------------------------------------------------
# Routes — job execution
# -----------------------------------------------------------------------------

@app.route("/api/run-population", methods=["POST"])
def start_population():
    job_id = str(uuid.uuid4())
    t = threading.Thread(target=run_population, args=(job_id, jobs, log_queues, progress_queues, jobs_lock))
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
    t = threading.Thread(target=run_validation, args=(job_id, export_file, jobs, log_queues, progress_queues, jobs_lock))
    t.daemon = True
    t.start()
    return jsonify({"job_id": job_id})


# -----------------------------------------------------------------------------
# Routes — job status and streams
# -----------------------------------------------------------------------------

@app.route("/api/progress/<job_id>")
def stream_progress(job_id):
    """Stream progress events as SSE (JSON)."""
    return Response(
        _stream_progress_generator(job_id),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.route("/api/logs/<job_id>")
def stream_logs(job_id):
    """Stream raw log lines as SSE (legacy)."""
    return Response(
        _stream_logs_generator(job_id),
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


@app.route("/api/jobs/active")
def active_jobs():
    """Return whether any job is currently running (for disabling UI actions)."""
    with jobs_lock:
        running = [jid for jid, j in jobs.items() if j.get("status") == "running"]
    return jsonify({"running": len(running) > 0, "job_ids": running})


# -----------------------------------------------------------------------------
# Entry point
# -----------------------------------------------------------------------------

def main():
    print("OnWatch Data Population Hub")
    print("Open http://127.0.0.1:5000 in your browser")
    print("Press Ctrl+C to stop")
    app.run(host="127.0.0.1", port=5000, debug=False, threaded=True)


if __name__ == "__main__":
    main()
