# OnWatch Data Population Automation - User Guide

Automated tool for populating OnWatch on-premise systems with configuration and data via API.

## Prerequisites

- **Python 3.9 or higher** (check with `python3 --version`)
- Network access to OnWatch system
- Network access to Rancher (for Kubernetes environment variables)
- SSH access to OnWatch device (for translation file upload)
- OnWatch admin credentials
- Rancher admin credentials
- SSH credentials to OnWatch device

## Quick Start - Default Baseline Data Setup

This is the most common use case: populate OnWatch with the pre-configured baseline data.

### Step 1: Clone and Install

```bash
# Clone the repository
git clone https://github.com/DeanZOosto/DataPopulationOnWatch.git
cd DataPopulationOnWatch

# Install Python dependencies
pip3 install -r requirements.txt
```

### Step 2: Configure

#### Option A: Quick IP Configuration (Recommended)

Update all IP addresses with a single command:

```bash
python3 main.py --set-ip YOUR_IP_ADDRESS
```

**Example:**
```bash
python3 main.py --set-ip 192.168.1.100
```

This automatically updates:
- `onwatch.ip_address` and `onwatch.base_url`
- `ssh.ip_address` (usually same as onwatch)
- `rancher.ip_address` and `rancher.base_url`

A backup of your original `config.yaml` is created automatically (e.g., `config.yaml.backup.20231209_181500`).

#### Option B: Manual Configuration

If you prefer to edit manually:

```bash
nano config.yaml  # or use your preferred editor
```

**Update these fields:**
- `onwatch.ip_address` - Your OnWatch system IP
- `onwatch.base_url` - Update IP in URL (e.g., `https://YOUR_IP`)
- `onwatch.username` - Your OnWatch admin username  
- `onwatch.password` - Your OnWatch admin password
- `ssh.ip_address` - SSH IP (usually same as onwatch)
- `ssh.username` - SSH username
- `ssh.password` - SSH password
- `rancher.ip_address` - Rancher server IP
- `rancher.base_url` - Update IP in URL (e.g., `https://YOUR_IP:9443`)
- `rancher.username` - Rancher username
- `rancher.password` - Rancher password

**Note:** All other data (subjects, cameras, groups, etc.) is already pre-configured.

### Step 3: Validate and Run

```bash
# Validate configuration
python3 main.py --validate

# Preview what will be executed (recommended)
python3 main.py --dry-run

# Run full automation
python3 main.py
```

### What to Expect

**Execution Time:** 5-10 minutes

**Output Example:**
```
[Step 1/11] Initializing API client...
✓ Successfully logged in to the OnWatch server

[Step 2/11] Setting KV parameters...
✓ Set KV parameter: applicationSettings/watchVideo/secondsAfterDetection = 6

[Step 6/11] Populating watch list...
✓ Added subject 'Yonatan' with 2 images
✓ Added subject 'crop 1' with 1 image
...

✓ Automation completed successfully
```

**After Completion:**
- System settings configured
- 3 subject groups created
- 5 subjects added to watch list
- 4 cameras configured
- Inquiry case created
- Mass import uploaded
- Rancher environment variables set
- Translation file uploaded

**Note:** Running multiple times is safe - existing items are automatically skipped (⏭️).

## Advanced Usage

### Update IP Address

If you need to change the IP address after initial setup:

```bash
# Update all IP addresses to a new IP
python3 main.py --set-ip 192.168.1.200

# The original config.yaml is automatically backed up
# You can find backups as: config.yaml.backup.YYYYMMDD_HHMMSS
```

### Run Specific Steps

```bash
# Add subjects to watch list only
python3 main.py --step populate-watchlist

# Configure system settings only
python3 main.py --step configure-system

# Upload translation file only
python3 main.py --step upload-files
```

### List All Available Steps

```bash
python3 main.py --list-steps
```

**Available Steps:**
- `init-api` - Initialize API connection
- `set-kv-params` - Set key-value parameters
- `configure-system` - Configure system settings
- `configure-groups` - Create subject groups
- `configure-accounts` - Create user accounts
- `populate-watchlist` - Add subjects with images
- `configure-devices` - Create cameras/devices
- `configure-inquiries` - Create inquiry cases
- `upload-mass-import` - Upload mass import file
- `configure-rancher` - Set Kubernetes environment variables
- `upload-files` - Upload translation file via SSH

### Custom Configuration

To customize the data being populated:

1. Edit `config.yaml` to modify:
   - Watch list subjects and images
   - Camera configurations
   - System settings
   - Groups and accounts
   - Inquiry cases

2. Run specific steps or full automation:
   ```bash
   python3 main.py --step populate-watchlist
   # or
   python3 main.py
   ```

### Additional Options

```bash
# Verbose logging (for debugging)
python3 main.py --verbose

# Save logs to file
python3 main.py --log-file automation.log

# Use custom config file
python3 main.py --config my-config.yaml
```

## Troubleshooting

### Configuration Validation Fails

**Error:** `Missing required section: 'onwatch'`

**Solution:** Check that `config.yaml` exists and contains all required sections.

### Login Failed

**Error:** `Login failed: Authentication failed (401 Unauthorized)`

**Solution:** 
- Verify username and password in `config.yaml`
- Test credentials manually via OnWatch UI

### File Not Found

**Error:** `Image file not found: assets/images/me.jpg`

**Solution:**
- Verify file paths in `config.yaml` are correct
- Check if files exist (paths are relative to project root)

### Network Connectivity

**Error:** `Connection error` or `404 Not Found`

**Solution:**
- Verify IP address in `config.yaml` is correct
- Check network connectivity: `ping <ip-address>`
- Ensure OnWatch API is accessible

## Common Use Cases

### Use Case 1: Add New Subjects

**Scenario:** Adding new subjects to an existing system.

1. Update `watch_list.subjects` in `config.yaml`
2. Run: `python3 main.py --step populate-watchlist`

**What to Expect:**
```
✓ Added subject 'John Doe' with 2 images
⏭️  Subject 'Jane Smith' already exists, skipping
```

### Use Case 2: Update System Settings

**Scenario:** Changing thresholds or retention periods.

1. Update `system_settings` section in `config.yaml`
2. Run: `python3 main.py --step configure-system`

### Use Case 3: Upload Translation File

**Scenario:** Updating translation file on the device.

1. Ensure translation file path is correct in `config.yaml`
2. Run: `python3 main.py --step upload-files`

## Tips

1. **Always validate first:** `python3 main.py --validate`
2. **Use dry-run:** `python3 main.py --dry-run` before actual run
3. **Run specific steps** when troubleshooting: `--step <step-name>`
4. **Check logs** saved with `--log-file` option for debugging

## Support

For issues:
1. Run `python3 main.py --validate` to check configuration
2. Review error messages (they include troubleshooting hints)
3. Use `--verbose` for detailed debugging
4. Check logs saved with `--log-file` option
