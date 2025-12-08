# OnWatch Data Population Automation

Automated data population script for OnWatch on-premise software. This tool automates the configuration and data setup process that was previously done manually through the UI.

## Features

### ✅ Fully Implemented (API-Based)
- **KV Parameters**: GraphQL API mutation for key-value settings
- **System Settings**: General, Map, Engine, and Interface settings via PATCH API
- **Acknowledge Actions**: Enable/disable and create acknowledge actions
- **Logo Uploads**: Company, sidebar, and favicon logos (two-step upload process)
- **Watch List**: Add subjects with multiple images via API
- **Groups Configuration** (Step 4): Subject groups creation via POST API
- **Accounts Configuration** (Step 5): User creation via POST API with role and user group mapping
- **Devices/Cameras Configuration** (Step 7): Camera creation via GraphQL mutation with full configuration support
- **Inquiries Configuration** (Step 8): Inquiry case creation with file uploads and custom file configuration (ROI, threshold)
- **Mass Import** (Step 9): Mass import file upload (processing continues in background; issues may need manual resolution)
- **Rancher Configuration** (Step 10): Kubernetes pod environment variables via Rancher REST API
- **Translation File Upload** (Step 11): Translation file upload via SSH/SCP to device

### 🚧 Not Yet Implemented (Requires API Endpoints)
- **Icons Directory Upload** (Step 11): Icons directory upload - currently requires manual setup (no API endpoint available)

**Note**: This project uses **API-only approach** for all steps. All automation is done via REST API, GraphQL API, or Rancher REST API.

### 📋 Future Enhancements
- **Icons Directory Upload** (Step 11): Currently requires manual setup
  - Future: Implement SSH/SCP upload or wait for API endpoint

## Prerequisites

- Python 3.9 or higher
- Access to OnWatch system (REST API and GraphQL API)
- Access to Rancher API (for Step 10 - Kubernetes workload configuration)

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

2. **SSH Connection** (for translation file upload):
   - Update `ssh.ip_address` (usually same as onwatch IP)
   - Update `ssh.username` and `ssh.password` if needed
   - Update `ssh.translation_util_path` if script is in different location

3. **Rancher Connection**:
   - Update `rancher.ip_address` and `port` if needed
   - Update credentials if different

4. **KV Parameters**: Add/modify key-value pairs as needed

5. **System Settings**: Configure all system settings sections
   - Set `system_interface.translation_file` to path of translation file (e.g., "assets/Polski-updated3.json.json")

6. **Devices**: Add/modify camera configurations

7. **Watch List**: 
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
   - Camera groups (Step 7)
   - Inquiry case creation and file uploads (Step 8)
   - Mass import file uploads (Step 9)
2. **GraphQL API**: 
   - KV parameters (mutation `updateSingleSetting`) (Step 2)
   - Camera creation (mutation `createCamera`) (Step 7)
   - File media data updates (mutation `updateFileMediaData`) (Step 8)
   - Mass import status queries (query `getMassImportLists`) (Step 9)
3. **Rancher REST API**: 
   - For setting Kubernetes pod environment variables (Step 10) - uses Rancher v3 API to update workload configurations
4. **SSH/SCP**: 
   - For uploading translation files (Step 11) - uses SSH to copy file to device and run translation-util script

## Customization

### API Endpoints

If your OnWatch API endpoints differ from the defaults, update them in `client_api.py`:
- Login endpoint
- Subject creation endpoint
- Face extraction endpoint
- Groups endpoint

### Rancher API

Rancher API (Step 10) uses the Rancher v3 REST API to update workload environment variables. Ensure Rancher credentials and environment variables are configured in `config.yaml`. The API client supports both token-based and basic authentication.

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
- All automation is done via API calls (REST API, GraphQL API, and Rancher REST API)
- Steps without API endpoints will log warnings and skip configuration
- **Mass Import**: After uploading, processing continues in the background. You may need to manually resolve issues in the mass import report via the UI after processing completes.

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
- **Groups (Step 4)**: Subject groups creation via POST API (works on clean system)
- **Accounts (Step 5)**: User creation via POST API with role/user group mapping
- **Watch List (Step 6)**: REST API with multiple images per subject
- **Devices (Step 7)**: Camera creation via GraphQL with full configuration (threshold, location, calibration, security access)
- **Inquiries (Step 8)**: Inquiry case creation with file uploads, priority setting, and custom file configuration (ROI, threshold)
- **Mass Import (Step 9)**: Mass import file upload (processing continues in background; check UI for status and manually resolve any issues if needed)
- **Rancher (Step 10)**: Kubernetes pod environment variables configuration via Rancher REST API
- **Translation File Upload (Step 11)**: Translation file upload via SSH/SCP to device

### 🚧 Steps Waiting for API Endpoints
- **Icons Directory Upload (Step 11)**: Icons directory upload - will log warning and skip (requires manual setup or future API endpoint)

**Note**: These steps will be implemented once API endpoints are available.

### Configuration Notes
- **Privacy/GDPR Settings**: `privacyMode` and `gdprMode` are intentionally NOT modified
- **Mask Classifier**: `maskClassifier.access` is intentionally NOT modified
- **Logo Source**: Automatically uses `assets/images/me.jpg` from "Yonatan" subject in watch_list
- **Translation Files**: Uploaded via SSH/SCP (Step 11)

## Future Enhancements

- Icons directory upload via SSH/SCP (translation file upload already implemented)
- Support for multiple environments (dev, staging, prod)
- Dry-run mode to preview changes
- Rollback functionality
- More robust error handling and retry logic
- API endpoints for Inquiries and Mass Import

