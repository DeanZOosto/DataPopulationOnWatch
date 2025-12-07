# OnWatch Data Population Automation

Automated data population script for OnWatch on-premise software. This tool automates the configuration and data setup process that was previously done manually through the UI.

## Features

### ✅ Fully Implemented (API-Based)
- **KV Parameters**: GraphQL API mutation for key-value settings
- **System Settings**: General, Map, Engine, and Interface settings via PATCH API
- **Acknowledge Actions**: Enable/disable and create acknowledge actions
- **Logo Uploads**: Company, sidebar, and favicon logos (two-step upload process)
- **Watch List**: Add subjects with multiple images via API

### 🚧 Not Yet Implemented (Requires API Endpoints)
- **Groups Configuration** (Step 4): Waiting for API endpoint
- **Accounts Configuration** (Step 5): Waiting for API endpoint
- **Devices/Cameras Configuration** (Step 7): Waiting for API endpoint
- **Inquiries Configuration** (Step 8): Waiting for API endpoint
- **Mass Import Upload** (Step 9): Waiting for API endpoint
- **File Uploads** (Step 11): Waiting for API endpoint

**Note**: This project uses **API-only approach**. UI automation has been removed. Once API endpoints are available, those steps will be implemented.

### 📋 Future Enhancements
- **Translation File Upload**: Currently requires manual bash script upload to service
  - Translation file: `/Users/deanzion/Downloads/Polski-updated3.json.json`
  - Future: Implement SSH/SCP upload or wait for API endpoint

## Prerequisites

- Python 3.9 or higher
- Access to OnWatch system
- Access to Rancher UI (for Step 10 - when implemented)

## Installation

1. Clone or navigate to this directory:
```bash
cd /Users/deanzion/Work/DataPopulationOnWatch
```

2. Install Python dependencies:
```bash
pip install -r requirements.txt
```

## Configuration

Edit the `config.yaml` file with your settings:

1. **OnWatch Connection**:
   - Update `onwatch.ip_address` with your OnWatch system IP
   - Update credentials if different from defaults

2. **Rancher Connection**:
   - Update `rancher.ip_address` and `port` if needed
   - Update credentials if different

3. **KV Parameters**: Add/modify key-value pairs as needed

4. **System Settings**: Configure all system settings sections

5. **Devices**: Add/modify camera configurations

6. **Watch List**: 
   - Add subject names
   - Specify image file paths
   - Set group IDs or leave null for default group

7. **Environment Variables**: Add Rancher environment variables if needed

## Usage

### Basic Usage

Run the automation script:
```bash
python3 main.py
```

### With Custom Config File

```bash
python3 main.py --config my-config.yaml
```


## Configuration File Structure

The `config.yaml` file contains all settings organized in sections:

- `onwatch`: Connection details for OnWatch
- `rancher`: Connection details for Rancher
- `kv_parameters`: Key-value settings
- `system_settings`: General, map, engine, and interface settings
- `devices`: Camera/device configurations
- `watch_list`: Subjects to add with image paths
- `env_vars`: Rancher environment variables
- `file_uploads`: File paths for uploads

## How It Works

The automation uses **API-only approach**:

1. **REST API** (via `ClientApi`): 
   - Watch list population (Step 6)
   - System settings (PATCH `/bt/api/settings`) (Step 3)
   - Acknowledge actions (Step 3)
   - Logo uploads (Step 3)
2. **GraphQL API**: 
   - KV parameters (mutation `updateSingleSetting`) (Step 2)
3. **Rancher Automation**: 
   - For setting Kubernetes pod environment variables (Step 10 - when implemented)

## Customization

### API Endpoints

If your OnWatch API endpoints differ from the defaults, update them in `client_api.py`:
- Login endpoint
- Subject creation endpoint
- Face extraction endpoint
- Groups endpoint

### Rancher UI

Rancher UI structure may vary by version. Update selectors in `rancher_automation.py` if needed.

## Troubleshooting

### Login Issues

- Verify IP address and credentials in `config.yaml`
- Check network connectivity to OnWatch system
- Ensure SSL certificate issues are handled (script disables SSL verification)

### API Issues

- Verify API endpoints match your OnWatch version
- Check authentication mechanism (token vs cookie)
- Review API response formats

### Image Upload Issues

- Ensure image file paths in `config.yaml` are absolute or relative to script location
- Verify image files exist and are readable
- Check image format compatibility

## Logging

The script provides detailed logging:
- INFO: Normal operation messages
- WARNING: Non-critical issues
- ERROR: Critical failures

Logs are printed to console. To save logs to file:
```bash
python3 main.py 2>&1 | tee automation.log
```

## Notes

- The script disables SSL verification for self-signed certificates
- All automation is done via API calls (REST and GraphQL)
- Steps without API endpoints will log warnings and skip configuration

## Support

For issues or questions:
1. Check the logs for error messages
2. Verify configuration file format (YAML syntax)
3. Test individual components (API, UI, Rancher) separately
4. Review and adjust selectors/endpoints as needed

## Example Workflow

1. Install fresh OnWatch system
2. Update `config.yaml` with your settings and image paths
3. Run `python3 main.py`
4. Monitor console output for progress
5. Verify settings in OnWatch UI after completion

## Current Status

### ✅ Working Features (API-Based)
- **KV Parameters (Step 2)**: GraphQL API mutation
- **System Settings (Step 3)**: REST API with acknowledge actions and logo uploads
- **Watch List (Step 6)**: REST API with multiple images per subject

### 🚧 Steps Waiting for API Endpoints
- **Groups (Step 4)**: Will log warning and skip
- **Accounts (Step 5)**: Will log warning and skip
- **Devices (Step 7)**: Will log warning and skip
- **Inquiries (Step 8)**: Will log warning and skip
- **Mass Import (Step 9)**: Will log warning and skip
- **File Uploads (Step 11)**: Will log warning and skip

**Note**: These steps will be implemented once API endpoints are available.

### Configuration Notes
- **Privacy/GDPR Settings**: `privacyMode` and `gdprMode` are intentionally NOT modified
- **Mask Classifier**: `maskClassifier.access` is intentionally NOT modified
- **Logo Source**: Automatically uses `images/me.jpg` from "Yonatan" subject in watch_list
- **Translation Files**: Currently requires manual upload via bash script (no API endpoint)

## Future Enhancements

- Translation file upload via API or SSH/SCP
- Support for multiple environments (dev, staging, prod)
- Dry-run mode to preview changes
- Rollback functionality
- More robust error handling and retry logic
- API endpoints for Groups, Accounts, Devices, Inquiries, Mass Import

