# OnWatch Data Population Automation

Automated tool for populating OnWatch on-premise systems with configuration and data via API.

## Quick Start

```bash
# Install dependencies
pip3 install -r requirements.txt

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
python3 main.py --step upload-files
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

### Update IP Address
```bash
# Update all IP addresses in config.yaml (onwatch, ssh, rancher)
python3 main.py --set-ip 192.168.1.100
# Creates a backup of the original config file automatically
```

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

### Manual Configuration

Edit `config.yaml` with your OnWatch system details. Use environment variables for passwords:

```yaml
onwatch:
  ip_address: "10.1.71.14"
  username: "Administrator"
  password: "${ONWATCH_PASSWORD}"  # Set: export ONWATCH_PASSWORD="your-password"
```


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

## Help

```bash
python3 main.py --help
```
