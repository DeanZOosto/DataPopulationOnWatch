# OnWatch Data Population Automation - User Guide

## Overview

Automated tool for populating OnWatch on-premise systems with configuration and data. All operations are performed via API - no manual UI interaction required.

## Quick Start

### 1. Clone and Setup

```bash
# Clone the repository
git clone <repository-url>
cd DataPopulationOnWatch

# Install Python dependencies
pip install -r requirements.txt
```

### 2. Configure

```bash
# Copy example configuration
cp config.example.yaml config.yaml

# Edit config.yaml with your system details
nano config.yaml  # or use your preferred editor
```

**Required Configuration:**
- `onwatch.ip_address` - Your OnWatch system IP
- `onwatch.username` - OnWatch admin username
- `onwatch.password` - OnWatch admin password (or use `${ONWATCH_PASSWORD}` env var)
- `ssh.ip_address` - SSH IP (usually same as onwatch)
- `ssh.username` - SSH username
- `ssh.password` - SSH password (or use `${SSH_PASSWORD}` env var)
- `rancher.ip_address` - Rancher server IP
- `rancher.username` - Rancher username
- `rancher.password` - Rancher password (or use `${RANCHER_PASSWORD}` env var)

### 3. Validate Configuration

```bash
python3 main.py --validate
```

**Expected Output:**
```
✓ Configuration validation passed with no errors or warnings
✓ Configuration is valid
```

### 4. Run Automation

```bash
# Preview what will be executed (recommended first)
python3 main.py --dry-run

# Run full automation
python3 main.py
```

## Default Baseline Data Setup (Most Common)

**Use Case:** Populate OnWatch system with the default baseline data provided in the repository.

This is the simplest and most common use case - running the automation with the pre-configured baseline data from machine 10.1.71.14.

### Quick Setup

```bash
# 1. Clone repository
git clone <repository-url>
cd DataPopulationOnWatch

# 2. Install dependencies
pip install -r requirements.txt

# 3. Update only IP addresses and credentials in config.yaml
# (The rest of the data is already configured)
nano config.yaml
```

**What to Update in config.yaml:**
- `onwatch.ip_address` - Your OnWatch system IP
- `onwatch.username` - Your OnWatch admin username  
- `onwatch.password` - Your OnWatch admin password
- `ssh.ip_address` - SSH IP (usually same as onwatch)
- `ssh.username` - SSH username
- `ssh.password` - SSH password
- `rancher.ip_address` - Rancher server IP
- `rancher.username` - Rancher username
- `rancher.password` - Rancher password

**Everything else is pre-configured:**
- ✓ 5 KV parameters
- ✓ System settings (thresholds, retention, map settings)
- ✓ 3 subject groups (OnPatrol subject, Cardholders, Default Group)
- ✓ 2 user accounts (Test, Administrator)
- ✓ 2 user groups
- ✓ 5 watch list subjects with images
- ✓ 4 cameras/devices
- ✓ 1 inquiry case with 4 files
- ✓ Mass import file
- ✓ Environment variables for Rancher
- ✓ Translation file

### Run Automation

```bash
# Validate configuration
python3 main.py --validate

# Preview what will be executed
python3 main.py --dry-run

# Run full automation
python3 main.py
```

### What to Expect

**Execution Time:** Approximately 5-10 minutes depending on file sizes and network speed.

**Output Example:**
```
[Step 1/11] Initializing API client...
✓ Successfully logged in to the OnWatch server at IP: 10.1.71.14

[Step 2/11] Setting KV parameters...
✓ Set KV parameter: applicationSettings/watchVideo/secondsAfterDetection = 6
✓ Set KV parameter: applicationSettings/watchVideo/secondsBeforeDetection = 6
...

[Step 6/11] Populating watch list...
✓ Added subject 'Yonatan' with 2 images
✓ Added subject 'crop 1' with 1 image
✓ Added subject 'crop 2' with 1 image
✓ Added subject 'women 1' with 1 image
✓ Added subject 'moderate 1' with 1 image

...

✓ Automation completed successfully

=== Automation Summary ===
Steps Completed: 11/11
Items Created: 45
Items Skipped: 2 (already existed)
Warnings: 0
Errors: 0
```

**After Completion:**
- All system settings configured
- Subject groups created
- 5 subjects added to watch list
- 4 cameras configured
- Inquiry case created with files
- Mass import uploaded (processing in background)
- Rancher environment variables set
- Translation file uploaded

**Note:** If you run this multiple times on the same system, existing items will be automatically skipped (⏭️). This is safe and expected behavior.

## Example Use Cases

### Example 1: Initial System Setup

**Scenario:** Setting up a new OnWatch system with baseline configuration.

```bash
# 1. Configure system settings
python3 main.py --step configure-system

# 2. Create subject groups
python3 main.py --step configure-groups

# 3. Add subjects to watch list
python3 main.py --step populate-watchlist

# 4. Configure cameras
python3 main.py --step configure-devices
```

**What to Expect:**
- Each step shows progress with ✓ success indicators
- Existing items are automatically skipped (⏭️)
- Summary report at the end showing what was created/skipped

### Example 2: Add New Subjects

**Scenario:** Adding new subjects to an existing system.

```bash
# 1. Update watch_list section in config.yaml
# 2. Run only the watch list step
python3 main.py --step populate-watchlist
```

**What to Expect:**
```
[Step 6/11] Populating watch list...
✓ Added subject 'John Doe' with 2 images
⏭️  Subject 'Jane Smith' already exists, skipping
✓ Added subject 'Bob Wilson' with 1 image
```

### Example 3: Update System Settings

**Scenario:** Changing thresholds or retention periods.

```bash
# 1. Update system_settings section in config.yaml
# 2. Run system configuration step
python3 main.py --step configure-system
```

**What to Expect:**
```
[Step 3/11] Configuring system settings...
✓ System settings configured via API
✓ Acknowledge actions enabled
✓ Uploaded company logo
✓ Uploaded favicon logo
```

### Example 4: Upload Translation File

**Scenario:** Updating translation file on the device.

```bash
# 1. Ensure translation file path is correct in config.yaml
# 2. Run upload step
python3 main.py --step upload-files
```

**What to Expect:**
```
[Step 11/11] Uploading files...
Copying assets/Polski-updated3.json.json to user@10.1.71.14:/tmp/Polski-updated3.json.json
✓ Successfully copied file to /tmp/Polski-updated3.json.json
✓ Translation file uploaded successfully
```

### Example 5: Configure Kubernetes Environment Variables

**Scenario:** Setting environment variables for OnWatch engine pods.

```bash
# 1. Update env_vars section in config.yaml
# 2. Run Rancher configuration step
python3 main.py --step configure-rancher
```

**What to Expect:**
```
[Step 10/11] Configuring Rancher...
Successfully logged in to Rancher API
Successfully retrieved workload: statefulset:default:cv-engine
✓ Successfully configured 4 environment variables in Rancher
```

## What to Expect During Execution

### Normal Execution Flow

```
2025-12-09 12:00:00 - INFO - Configuration loaded from config.yaml
2025-12-09 12:00:01 - INFO - [Step 1/11] Initializing API client...
2025-12-09 12:00:02 - INFO - Successfully logged in to the OnWatch server at IP: 10.1.71.14
2025-12-09 12:00:02 - INFO - [Step 2/11] Setting KV parameters...
2025-12-09 12:00:03 - INFO - ✓ Set KV parameter: applicationSettings/watchVideo/secondsAfterDetection = 6
...
2025-12-09 12:05:00 - INFO - ✓ Automation completed successfully
```

### Success Indicators

- ✓ Green checkmarks for successful operations
- ⏭️ Skip indicators for items that already exist
- Clear step-by-step progress messages
- Summary report at the end

### Error Handling

If an error occurs:
- Clear error message with context
- Troubleshooting hints included
- Script continues with other steps (if possible)
- Summary report shows what failed

**Example Error:**
```
ERROR - Login failed: Authentication failed (401 Unauthorized)
  → Check username and password in config.yaml (onwatch section)
  → Verify credentials are correct for this OnWatch system
```

## Available Steps

Use `python3 main.py --list-steps` to see all available steps with descriptions:

```
--step init-api              Initialize API Client
                            Connect and authenticate with OnWatch API

--step set-kv-params         Set KV Parameters
                            Configure key-value system parameters

--step configure-system      Configure System Settings
                            Set general, map, engine, and interface settings

--step configure-groups      Configure Groups
                            Create subject groups with authorization and visibility

--step configure-accounts    Configure Accounts
                            Create user accounts and user groups

--step populate-watchlist    Populate Watch List
                            Add subjects to watch list with images

--step configure-devices     Configure Devices
                            Create cameras/devices with thresholds and calibration

--step configure-inquiries   Configure Inquiries
                            Create inquiry cases with file uploads and ROI settings

--step upload-mass-import    Upload Mass Import
                            Upload mass import file for bulk subject import

--step configure-rancher     Configure Rancher
                            Set Kubernetes environment variables via Rancher API

--step upload-files          Upload Files
                            Upload translation file to device via SSH
```

## Common Commands

```bash
# Validate configuration
python3 main.py --validate

# Preview changes (dry-run)
python3 main.py --dry-run

# Run full automation
python3 main.py

# Run specific step
python3 main.py --step populate-watchlist

# Verbose logging (for debugging)
python3 main.py --verbose

# Save logs to file
python3 main.py --log-file automation.log

# List all available steps
python3 main.py --list-steps
```

## Troubleshooting

### Configuration Validation Fails

**Error:** `Missing required section: 'onwatch'`

**Solution:** Check that `config.yaml` exists and contains all required sections. Compare with `config.example.yaml`.

### Login Failed

**Error:** `Login failed: Authentication failed (401 Unauthorized)`

**Solution:** 
- Verify username and password in `config.yaml`
- Test credentials manually via OnWatch UI
- Use environment variables if password contains special characters

### File Not Found

**Error:** `Image file not found: assets/images/me.jpg`

**Solution:**
- Verify file paths in `config.yaml` are correct
- Check if files exist (paths are relative to project root)
- Use absolute paths if needed

### Network Connectivity

**Error:** `Connection error` or `404 Not Found`

**Solution:**
- Verify IP address in `config.yaml` is correct
- Check network connectivity: `ping 10.1.71.14`
- Ensure OnWatch API is accessible

## Tips

1. **Always validate first:** `python3 main.py --validate`
2. **Use dry-run:** `python3 main.py --dry-run` before actual run
3. **Use environment variables** for passwords (more secure)
4. **Run specific steps** when troubleshooting: `--step <step-name>`
5. **Check logs** saved with `--log-file` option for detailed debugging

## Support

For issues:
1. Run `python3 main.py --validate` to check configuration
2. Review error messages (they include troubleshooting hints)
3. Use `--verbose` for detailed debugging
4. Check logs saved with `--log-file` option
