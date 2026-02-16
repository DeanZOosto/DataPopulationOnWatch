# OnWatch Data Population Hub

Web UI for running population, validation, and viewing logs and results.

## Run

From the project root:

```bash
pip install -r requirements.txt   # if not already installed
python run_web.py
```

Then open **http://127.0.0.1:5000** in your browser.

## Hosted deployment (gunicorn)

When deploying behind gunicorn (e.g. on a server), use **one worker** (`-w 1`). The app keeps job state in memory per process; with multiple workers, progress streams can hit a different worker than the one that created the job, causing 500 errors and UI blocking.

```bash
gunicorn -w 1 -b 0.0.0.0:5050 "web.app:app"
```

## Features

- **Config status** – Validates config and shows OnWatch IP/version
- **Run population** – One-click run with live log streaming
- **Validate** – Select an export file and run validation with live logs
- **Exports list** – View all export files with metadata
- **Results** – Population and validation results, manual checklist
