# OnWatch Data Population Automation

Automated data population tool for OnWatch on-premise systems. This script automates the configuration and data setup process via REST API, GraphQL API, and Rancher configuration.

## Quick Start

### 1. Installation

```bash
# Install Python dependencies
pip install -r requirements.txt
```

### 2. Configuration

Copy the example config and update with your values:

```bash
cp config.example.yaml config.yaml
# Edit config.yaml with your OnWatch system details
```

**Important**: Use environment variables for sensitive data:
```yaml
onwatch:
  password: "${ONWATCH_PASSWORD}"  # Set ONWATCH_PASSWORD env var
```

### 3. Validate Configuration

```bash
python3 main.py --validate
```

### 4. Run Automation

```bash
# Full automation
python3 main.py

# Dry-run (preview without making changes)
python3 main.py --dry-run

# Run specific step
python3 main.py --step 6
```

## Table of Contents

- [Quick Start](#quick-start)
- [Configuration](#configuration)
- [Usage Examples](#usage-examples)
- [Command-Line Options](#command-line-options)
- [Troubleshooting](#troubleshooting)
- [Configuration Reference](#configuration-reference)

## Configuration

### Environment Variables

For security, use environment variables for passwords and sensitive data:

```bash
export ONWATCH_PASSWORD="your-password"
export SSH_PASSWORD="ssh-password"
export RANCHER_PASSWORD="rancher-password"
```

Then in `config.yaml`:
```yaml
onwatch:
  password: "${ONWATCH_PASSWORD}"
ssh:
  password: "${SSH_PASSWORD}"
rancher:
  password: "${RANCHER_PASSWORD}"
```

### Required Configuration Sections

- **onwatch**: OnWatch system connection (IP, username, password)
- **ssh**: SSH connection for translation file upload
- **rancher**: Rancher API connection for Kubernetes environment variables

See `config.example.yaml` for complete configuration template.

## Usage Examples

### Validate Configuration
```bash
python3 main.py --validate
```

### Dry-Run (Preview Changes)
```bash
python3 main.py --dry-run
```

### Run Full Automation
```bash
python3 main.py
```

### Run Specific Step
```bash
# Step 6: Populate Watch List
python3 main.py --step 6
```

### Verbose Logging
```bash
python3 main.py --verbose
```

### Save Logs to File
```bash
python3 main.py --log-file automation.log
```

### List Available Steps
```bash
python3 main.py --list-steps
```

## Command-Line Options

| Option | Description |
|--------|-------------|
| `--config FILE` | Use custom config file (default: `config.yaml`) |
| `--validate` | Validate configuration and exit |
| `--dry-run` | Preview changes without executing |
| `--step N` | Run only step N (1-11) |
| `--verbose` | Enable debug logging |
| `--quiet` | Show errors only |
| `--log-file FILE` | Save logs to file |
| `--list-steps` | List all available steps |
| `--version` | Show version information |
| `--help` | Show help message |

## Troubleshooting

### Common Issues

#### Configuration Validation Fails

**Error**: `Missing required section: 'onwatch'`

**Solution**: 
- Check that `config.yaml` exists and is valid YAML
- Verify all required sections are present (onwatch, ssh, rancher)
- Run `python3 main.py --validate` for detailed validation report

#### Login Failed (401 Unauthorized)

**Error**: `Login failed: Authentication failed (401 Unauthorized)`

**Solution**:
- Verify username and password in `config.yaml` (onwatch section)
- Check credentials are correct for this OnWatch system
- Ensure password is not empty (use env var if needed)

#### File Not Found

**Error**: `Image file not found: assets/images/me.jpg`

**Solution**:
- Verify file paths in `config.yaml` are correct
- Check if files exist (paths are relative to project root)
- Use absolute paths if needed

#### Network Connectivity Issues

**Error**: `Connection error` or `404 Not Found`

**Solution**:
- Verify IP address in `config.yaml` is correct
- Check network connectivity to OnWatch system
- Ensure OnWatch API is accessible
- Verify firewall rules allow connections

#### SSH Authentication Failed

**Error**: `SFTP authentication failed`

**Solution**:
- Check SSH username and password in `config.yaml` (ssh section)
- Verify credentials are correct for the device
- Ensure SSH service is running on the device

### Getting Help

1. **Validate Configuration**: `python3 main.py --validate`
2. **Check Logs**: Review error messages for specific issues
3. **Dry-Run First**: Use `--dry-run` to preview changes
4. **Verbose Mode**: Use `--verbose` for detailed debugging

## Configuration Reference

### Configuration File Structure

```yaml
onwatch:              # OnWatch system connection
  ip_address: "10.1.71.14"
  username: "Administrator"
  password: "${ONWATCH_PASSWORD}"

ssh:                  # SSH for translation file upload
  ip_address: "10.1.71.14"
  username: "user"
  password: "${SSH_PASSWORD}"

rancher:              # Rancher API connection
  ip_address: "10.1.71.14"
  port: 9443
  username: "admin"
  password: "${RANCHER_PASSWORD}"

kv_parameters:        # Key-value settings
  "applicationSettings/watchVideo/secondsAfterDetection": 6

system_settings:      # System configuration
  general: {...}
  map: {...}
  engine: {...}

devices:              # Camera/device configurations
  - name: "face camera"
    video_url: "rtsp://..."
    ...

watch_list:          # Subjects to add
  subjects:
    - name: "Yonatan"
      images:
        - path: "assets/images/me.jpg"
```

See `config.example.yaml` for complete example.

## Automation Steps

1. **Initialize API Client** - Connect to OnWatch API
2. **Set KV Parameters** - Configure key-value settings
3. **Configure System Settings** - General, map, engine, interface settings
4. **Configure Groups** - Create subject groups
5. **Configure Accounts** - Create users and user groups
6. **Populate Watch List** - Add subjects with images
7. **Configure Devices** - Create cameras/devices
8. **Configure Inquiries** - Create inquiry cases with files
9. **Upload Mass Import** - Upload mass import file
10. **Configure Rancher** - Set Kubernetes environment variables
11. **Upload Files** - Upload translation file via SSH

## Features

- **API-Only Approach**: All automation via REST API, GraphQL API, and Rancher API
- **Configuration Validation**: Validate config before running
- **Dry-Run Mode**: Preview changes without executing
- **Environment Variables**: Secure password handling
- **Duplicate Detection**: Automatically skips existing items
- **Comprehensive Logging**: Detailed progress and error reporting
- **Error Recovery**: Clear error messages with troubleshooting hints

## Notes

- The script disables SSL verification for self-signed certificates
- Mass import processing continues in background (check UI for status)
- Some items may need manual resolution after automation completes
- All file paths are relative to project root unless absolute

## Support

For detailed documentation, see `CONFLUENCE_TEMPLATE.md` for step-by-step guide.

For issues:
1. Run `python3 main.py --validate` to check configuration
2. Review error messages (they include troubleshooting hints)
3. Use `--verbose` for detailed debugging
4. Check logs saved with `--log-file` option
