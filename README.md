# OnWatch Data Population Automation

Automated tool for populating OnWatch on-premise systems with configuration and data via API.

**Supports OnWatch 2.6 and 2.8** - See [VERSION_COMPATIBILITY.md](VERSION_COMPATIBILITY.md) for details.

## Quick Start

On macOS with Homebrew Python (or any PEP 668 “externally managed” Python), you must use a virtual environment; installing packages system-wide will fail.

```bash
# Create and activate virtual environment (required on Homebrew Python)
python3 -m venv .venv
source .venv/bin/activate   # On macOS/Linux
# On Windows: .venv\Scripts\activate

# Install dependencies (inside the venv)
pip install -r requirements.txt

# Configure IP address (recommended - updates all IPs automatically)
python3 main.py --set-ip 192.168.1.100

# Or manually edit config.yaml with your system details
# The file already contains baseline data - just update connection details

# Validate configuration
python3 main.py --validate

# Run automation
python3 main.py
```

## Example Usage

### Full Automation
```bash
python3 main.py
```

### Run Specific Steps
```bash
# Add subjects to watch list
python3 main.py --step populate-watchlist

# Configure system settings
python3 main.py --step configure-system

# Upload translation file
python3 main.py --step upload-translation-file
```

### Preview Changes
```bash
# See what would be executed without making changes
python3 main.py --dry-run
```

### List All Steps
```bash
python3 main.py --list-steps
```

### Preview Dataset
```bash
# See what data will be populated
python3 main.py --preview-data
```

### Update IP Address
```bash
# Update all IP addresses in config.yaml (onwatch, ssh, rancher)
python3 main.py --set-ip 192.168.1.100
# Creates a backup of the original config file automatically
```

### Set OnWatch Version
```bash
# Set OnWatch version (automatically updates Rancher password)
python3 main.py --set-version 2.8

# Or combine with IP update
python3 main.py --set-ip 192.168.1.100 --set-version 2.8
```

This automatically updates:
- `onwatch.version` (2.6 or 2.8)
- `rancher.password` (2.6="admin", 2.8="administrator")

### Validate Data (Post-Upgrade)

See [VALIDATION_GUIDE.md](VALIDATION_GUIDE.md) for complete validation instructions.

```bash
# Quick validation
python3 validate_data.py onwatch_data_export_2025-01-15_10-30-00.yaml
```

### Web UI Hub

A local web interface for running population, validation, and viewing logs and results:

```bash
python run_web.py
```

Then open http://127.0.0.1:5000 in your browser. See [web/README.md](web/README.md) for details.

## Configuration

### Quick IP Configuration

The easiest way to configure IP addresses is using the `--set-ip` option:

```bash
python3 main.py --set-ip 192.168.1.100
```

This automatically updates:
- `onwatch.ip_address` and `onwatch.base_url`
- `ssh.ip_address`
- `rancher.ip_address` and `rancher.base_url`

### Working from different locations (office, home, abroad)

The script works from **office, home, or abroad** with the same config. Connect to the **company VPN** when you are not in the office (same as for OnWatch in the browser). The script will try all local interfaces, including the VPN interface. **Leave `bind_address` unset** in shared configs so one config works everywhere.

To force a specific interface only in rare cases, set under `onwatch` your **current** IP (from System Settings → Network or `ifconfig`). The value is network-specific and not portable.
   ```yaml
   # bind_address: "192.168.1.100"   # optional; leave unset for office/home/VPN
   ```

### Manual Configuration

Edit `config.yaml` with your OnWatch system details. Use environment variables for passwords:

```yaml
onwatch:
  ip_address: "10.1.71.14"
  username: "Administrator"
  password: "${ONWATCH_PASSWORD}"  # Set: export ONWATCH_PASSWORD="your-password"
```

### Operator overrides — `config.local.yaml`

Per-machine values (target IP, OnWatch version, etc.) are kept in `config.local.yaml`, a gitignored overlay next to `config.yaml`. It's created automatically the first time you click **Set IP** or **Set Version** in the web UI (or run `--set-ip` / `--set-version` on the CLI). Anything in the overlay is deep-merged over `config.yaml` at load time, so the tracked file stays clean and `git status` doesn't churn between runs.

```yaml
# config.local.yaml — gitignored, written by the UI/CLI
onwatch:
  ip_address: "10.1.25.241"
  base_url: "https://10.1.25.241"
  version: "2.8"
ssh:
  ip_address: "10.1.25.241"
rancher:
  ip_address: "10.1.25.241"
  base_url: "https://10.1.25.241:9443"
  password: "administrator"
```

If `config.yaml` already has local edits from before this change, run `git checkout config.yaml` once, then use **Set IP** / **Set Version** to repopulate the overlay.


## What It Does

The tool automates:
- System configuration (KV parameters, settings, thresholds)
- Subject groups and user accounts
- Watch list population with images
- Camera/device configuration
- Inquiry cases with file uploads
- Mass import uploads
- Kubernetes environment variables (Rancher)
- Translation file uploads

All automation is done via REST API, GraphQL API, and Rancher API - no UI interaction required.

## Post-Upgrade Validation

After running the population script, an output YAML file is generated (e.g., `onwatch_data_export_2025-01-15_10-30-00.yaml`). This file contains a snapshot of all data that was created.

**For detailed validation instructions, see [VALIDATION_GUIDE.md](VALIDATION_GUIDE.md)**

Quick validation:

```bash
# Validate after population
python3 validate_data.py onwatch_data_export_2025-01-15_10-30-00.yaml

# Validate after upgrade
python3 validate_data.py onwatch_data_export_2025-01-15_10-30-00.yaml
```

## Testing

The project includes comprehensive unit and integration tests. To run tests:

```bash
# Install test dependencies (if not already installed)
pip3 install -r requirements.txt

# Run all tests
python3 -m pytest tests/ -v

# Run specific test file
python3 -m pytest tests/test_config_manager.py -v

# Run with coverage (if pytest-cov is installed)
python3 -m pytest tests/ --cov=. --cov-report=html
```

**Test Coverage:**
- ✅ Configuration management and validation
- ✅ Priority mapping (Low=201, Medium=101, High=1)
- ✅ Run summary and export file generation
- ✅ Integration workflows (config validation, export generation, Rancher env vars tracking)

All tests pass without requiring actual API connections (using mocks and temporary files).

## Help

```bash
python3 main.py --help
python3 validate_data.py --help
```
