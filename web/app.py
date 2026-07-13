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
from pathlib import Path

import yaml
from flask import Flask, Response, jsonify, redirect, render_template, request, session, url_for

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)

from web import job_store
from web.job_runner import run_population, run_validation

# -----------------------------------------------------------------------------
# Auth config
# -----------------------------------------------------------------------------

def _load_auth_config():
    """Load web UI credentials from config. Supports multiple users (web_ui.users) or single user (web_ui.username/password).
    Reads through ConfigManager so config.local.yaml overrides apply (e.g. operator can keep web_ui creds out of git).
    """
    try:
        from config_manager import ConfigManager
        config = ConfigManager(str(PROJECT_ROOT / "config.yaml")).load_config() or {}
        web_ui = config.get("web_ui") or {}
        onwatch = config.get("onwatch") or {}
        users = web_ui.get("users")
        if users and isinstance(users, list):
            # Multi-user: list of {username, password}
            user_map = {}
            for u in users:
                if isinstance(u, dict) and u.get("username"):
                    user_map[u["username"]] = u.get("password", "")
            return {"users": user_map, "secret_key": os.environ.get("OW_WEB_SECRET_KEY") or web_ui.get("secret_key") or "dev-secret-change-in-production"}
        # Single user (backward compat)
        return {
            "users": {web_ui.get("username") or onwatch.get("username") or "Administrator": web_ui.get("password") or onwatch.get("password") or ""},
            "secret_key": os.environ.get("OW_WEB_SECRET_KEY") or web_ui.get("secret_key") or "dev-secret-change-in-production",
        }
    except Exception:
        return {"users": {"Administrator": ""}, "secret_key": "dev-secret"}


def _require_login(f):
    """Decorator: redirect to login if not authenticated."""
    from functools import wraps
    @wraps(f)
    def wrapped(*args, **kwargs):
        if not session.get("logged_in"):
            if request.path.startswith("/api/"):
                return jsonify({"error": "Unauthorized", "login_required": True}), 401
            return redirect(url_for("login_page", next=request.url))
        return f(*args, **kwargs)
    return wrapped


# -----------------------------------------------------------------------------
# Flask app and shared state
# -----------------------------------------------------------------------------

app = Flask(__name__, template_folder="templates", static_folder="static")
auth_config = _load_auth_config()
app.secret_key = auth_config["secret_key"]
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"

jobs = {}
jobs_lock = threading.Lock()
log_queues = {}
progress_queues = {}

# Any run left "running" belongs to a previous process that no longer exists;
# reconcile it to "interrupted" so the UI degrades gracefully on reconnect.
_orphaned = job_store.mark_orphans_interrupted()
if _orphaned:
    print(f"Reconciled {len(_orphaned)} interrupted run(s) from a previous session")


# -----------------------------------------------------------------------------
# Data helpers — exports, config status
# -----------------------------------------------------------------------------

def get_exports():
    """List data_inserted YAML files with metadata, newest first.
    Scans exports/ first (current), then project root (legacy files left from before
    the exports/ migration). Patterns include onwatch_data_export_*.yaml and
    *_data_inserted_*.yaml for backward compatibility.
    """
    seen = set()
    all_files = []
    search_dirs = [Path("exports"), Path(".")]
    for d in search_dirs:
        if not d.exists():
            continue
        for pattern in ["onwatch_data_export_*.yaml", "*_data_inserted_*.yaml"]:
            for f in d.glob(pattern):
                if f.name in seen:
                    continue
                seen.add(f.name)
                all_files.append(f)
    exports = []
    for f in sorted(all_files, key=lambda p: p.stat().st_mtime, reverse=True):
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
    """Validate config and return status for UI. Reports current IP/version so users see
    what they're about to run against; never exposes credentials."""
    try:
        from config_manager import ConfigManager
        manager = ConfigManager("config.yaml")
        is_valid, errors = manager.validate_config(verbose=False)
        config = manager.load_config()
        onwatch = config.get("onwatch", {}) or {}
        return {
            "valid": is_valid,
            "errors": errors,
            "onwatch_ip": (onwatch.get("ip_address") or "").strip(),
            "onwatch_version": (onwatch.get("version") or "").strip(),
        }
    except Exception as e:
        return {"valid": False, "errors": [str(e)], "onwatch_ip": "", "onwatch_version": ""}


def _config_has_ip_and_version():
    """Return (ip, version) from config for run validation. Used internally by run/validate endpoints."""
    try:
        from config_manager import ConfigManager
        manager = ConfigManager("config.yaml")
        config = manager.load_config()
        onwatch = config.get("onwatch", {})
        ip = (onwatch.get("ip_address") or "").strip()
        version = (onwatch.get("version") or "").strip()
        return ip, version
    except Exception:
        return "", ""


# -----------------------------------------------------------------------------
# SSE stream generators
# -----------------------------------------------------------------------------

TERMINAL_STATUSES = ("done", "interrupted", "error")


def _stream_progress_generator(job_id):
    """Yield progress events as SSE JSON, replaying from the durable store.

    Reading from the on-disk event log (rather than a per-process queue) means a
    client that reconnects, opens a second tab, or connects after a server
    restart replays the whole run from the beginning and lands in the correct
    UI state. A run left ``running`` by a crashed process is surfaced as an
    explicit ``interrupted`` event instead of hanging forever.
    """
    seen = 0
    start = time.time()
    JOB_NOT_FOUND_TIMEOUT = 3.0
    while True:
        for ev in job_store.read_events(job_id, offset=seen):
            seen += 1
            yield f"data: {json.dumps(ev)}\n\n"
        meta = job_store.read_meta(job_id)
        if meta is None:
            if (time.time() - start) > JOB_NOT_FOUND_TIMEOUT:
                yield 'data: {"type":"stream_done","error":"job_not_found"}\n\n'
                return
            time.sleep(0.3)
            continue
        if meta.get("status") in TERMINAL_STATUSES:
            # Catch any events written just before the status flipped.
            for ev in job_store.read_events(job_id, offset=seen):
                seen += 1
                yield f"data: {json.dumps(ev)}\n\n"
            if meta.get("status") == "interrupted":
                yield "data: " + json.dumps({
                    "type": "interrupted",
                    "message": "Run was interrupted (the server restarted mid-run). "
                               "Partial data may already be on OnWatch.",
                    "checkpoint": meta.get("checkpoint"),
                }) + "\n\n"
            break
        time.sleep(0.3)
    yield 'data: {"type":"stream_done"}\n\n'


def _stream_logs_generator(job_id):
    """Yield log lines as SSE from the durable store until the job is terminal."""
    seen = 0
    start = time.time()
    JOB_NOT_FOUND_TIMEOUT = 3.0
    while True:
        text = job_store.read_log(job_id)
        lines = text.split("\n") if text else []
        # Last element is a trailing empty string when text ends with newline.
        available = len(lines) - 1 if lines and lines[-1] == "" else len(lines)
        while seen < available:
            yield f"data: {lines[seen]}\n\n"
            seen += 1
        meta = job_store.read_meta(job_id)
        if meta is None:
            if (time.time() - start) > JOB_NOT_FOUND_TIMEOUT:
                yield "data: [DONE]\n\n"
                return
        elif meta.get("status") in TERMINAL_STATUSES:
            break
        time.sleep(0.3)
    yield "data: [DONE]\n\n"


# -----------------------------------------------------------------------------
# Routes — auth (unprotected)
# -----------------------------------------------------------------------------

@app.route("/login")
def login_page():
    if session.get("logged_in"):
        return redirect(url_for("index"))
    return render_template("login.html")


@app.route("/api/login", methods=["POST"])
def login():
    data = request.get_json(silent=True) or request.form
    username = (data.get("username") or "").strip()
    password = (data.get("password") or "")
    users = auth_config.get("users") or {}
    if username in users and users[username] == password:
        session["logged_in"] = True
        session["username"] = username
        next_url = request.args.get("next") or request.form.get("next") or "/"
        if request.headers.get("X-Requested-With") == "XMLHttpRequest" or request.is_json:
            return jsonify({"success": True, "redirect": next_url})
        return redirect(next_url)
    if request.headers.get("X-Requested-With") == "XMLHttpRequest" or request.is_json:
        return jsonify({"success": False, "error": "Invalid username or password"}), 401
    return redirect(url_for("login_page", error=1))


@app.route("/api/logout", methods=["POST", "GET"])
def logout():
    session.pop("logged_in", None)
    if request.headers.get("X-Requested-With") == "XMLHttpRequest" or request.is_json:
        return jsonify({"success": True, "redirect": "/login"})
    return redirect(url_for("login_page"))


# -----------------------------------------------------------------------------
# Routes — pages (protected)
# -----------------------------------------------------------------------------

@app.route("/")
@_require_login
def index():
    return render_template("index.html")


# -----------------------------------------------------------------------------
# Routes — config API (protected)
# -----------------------------------------------------------------------------

@app.route("/api/config/status")
@_require_login
def config_status():
    return jsonify(get_config_status())


@app.route("/api/config/set-ip", methods=["POST"])
@_require_login
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


@app.route("/api/config/preview")
@_require_login
def config_preview():
    """Return the effective merged config (base + overlay) for preview, with web_ui redacted."""
    config_path = PROJECT_ROOT / "config.yaml"
    if not config_path.exists():
        return jsonify({"error": "config.yaml not found"}), 404
    try:
        from config_manager import ConfigManager
        data = ConfigManager(str(config_path)).load_config() or {}
        data.pop("web_ui", None)
        content = yaml.dump(data, default_flow_style=False, sort_keys=False, allow_unicode=True)
        return Response(content, mimetype="text/plain; charset=utf-8")
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/config/set-version", methods=["POST"])
@_require_login
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
# Routes — exports (protected)
# -----------------------------------------------------------------------------

@app.route("/api/exports")
@_require_login
def exports():
    return jsonify(get_exports())


@app.route("/api/file/preview")
@_require_login
def file_preview():
    """Return YAML file content for preview. Path must be under project root."""
    path_arg = request.args.get("path")
    if not path_arg:
        return jsonify({"error": "Missing 'path' parameter"}), 400
    try:
        resolved = Path(path_arg).resolve()
        try:
            resolved.relative_to(PROJECT_ROOT.resolve())
        except ValueError:
            return jsonify({"error": "Path must be within project directory"}), 403
        if not resolved.exists() or not resolved.is_file():
            return jsonify({"error": "File not found"}), 404
        content = resolved.read_text(encoding="utf-8")
        return Response(content, mimetype="text/plain; charset=utf-8")
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# -----------------------------------------------------------------------------
# Routes — job execution (protected)
# -----------------------------------------------------------------------------

@app.route("/api/run-population", methods=["POST"])
@_require_login
def start_population():
    data = request.get_json() or {}
    user_name = (data.get("name") or "").strip()
    if not user_name:
        return jsonify({"error": "Your name is required. Enter your name to prefix the export file."}), 400
    ip, version = _config_has_ip_and_version()
    if not ip or not version:
        return jsonify({
            "error": "Set IP and Version before running population. Use Config Status and click Set IP / Set Version."
        }), 400
    job_id = str(uuid.uuid4())
    t = threading.Thread(
        target=run_population,
        args=(job_id, jobs, log_queues, progress_queues, jobs_lock),
        kwargs={"user_name": user_name, "target": {"ip": ip, "version": version}},
    )
    t.daemon = True
    t.start()
    return jsonify({"job_id": job_id})


@app.route("/api/validate", methods=["POST"])
@_require_login
def start_validation():
    data = request.get_json() or {}
    export_file = data.get("file") or request.args.get("file")
    if not export_file:
        return jsonify({"error": "Missing 'file' parameter"}), 400
    ip, version = _config_has_ip_and_version()
    if not ip or not version:
        return jsonify({
            "error": "Set IP and Version before running validation. Use Config Status and click Set IP / Set Version."
        }), 400
    job_id = str(uuid.uuid4())
    t = threading.Thread(
        target=run_validation,
        args=(job_id, export_file, jobs, log_queues, progress_queues, jobs_lock),
        kwargs={"target": {"ip": ip, "version": version}},
    )
    t.daemon = True
    t.start()
    return jsonify({"job_id": job_id})


# -----------------------------------------------------------------------------
# Routes — job status and streams (protected)
# -----------------------------------------------------------------------------

@app.route("/api/progress/<job_id>")
@_require_login
def stream_progress(job_id):
    """Stream progress events as SSE (JSON)."""
    return Response(
        _stream_progress_generator(job_id),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.route("/api/logs/<job_id>")
@_require_login
def stream_logs(job_id):
    """Stream raw log lines as SSE (legacy)."""
    return Response(
        _stream_logs_generator(job_id),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.route("/api/status/<job_id>")
@_require_login
def job_status(job_id):
    with jobs_lock:
        job = jobs.get(job_id)
    if not job:
        # Fall back to the durable store (different worker, or after a restart).
        meta = job_store.read_meta(job_id)
        if not meta:
            return jsonify({"error": "Job not found"}), 404
        return jsonify({
            "type": meta.get("type"),
            "status": meta.get("status"),
            "result": meta.get("result"),
        })
    return jsonify({
        "type": job.get("type"),
        "status": job.get("status"),
        "result": job.get("result"),
    })


def _job_summary(meta):
    """Compact job view for the frontend to restore/reconnect after a reload."""
    if not meta:
        return None
    return {
        "job_id": meta.get("job_id"),
        "type": meta.get("type"),
        "status": meta.get("status"),
        "started_at": meta.get("started_at"),
        "target": meta.get("target"),
        "checkpoint": meta.get("checkpoint"),
        "result": meta.get("result"),
    }


@app.route("/api/jobs/active")
@_require_login
def active_jobs():
    """Report the currently running job (if any) and the most recent job.

    The frontend uses this on page load to reconnect to an in-flight run or to
    show the outcome of the last one, so refreshing the page never loses a run.
    """
    running = job_store.running_job()
    latest = job_store.latest_job()
    return jsonify({
        "running": bool(running),
        "running_job": _job_summary(running),
        "latest_job": _job_summary(latest),
    })


# -----------------------------------------------------------------------------
# Entry point
# -----------------------------------------------------------------------------

def main():
    print("OnWatch Data Population UI")
    print("Open http://127.0.0.1:5000 in your browser")
    print("Press Ctrl+C to stop")
    app.run(host="127.0.0.1", port=5000, debug=False, threaded=True)


if __name__ == "__main__":
    main()
