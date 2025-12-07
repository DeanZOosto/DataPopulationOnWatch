# OnWatch Data Population Automation

Automated data population script for OnWatch on-premise software. This tool automates the configuration and data setup process that was previously done manually through the UI.

## Features

### ✅ Fully Implemented (API-Based)
- **KV Parameters**: GraphQL API mutation for key-value settings
- **System Settings**: General, Map, Engine, and Interface settings via PATCH API
- **Acknowledge Actions**: Enable/disable and create acknowledge actions
- **Logo Uploads**: Company, sidebar, and favicon logos (two-step upload process)
- **Watch List**: Add subjects with multiple images via API

### 🚧 Partially Implemented
- **System Settings UI Automation**: Available as fallback if API fails
- **Groups, Accounts, Devices, Inquiries, Mass Import**: UI automation methods exist but need API endpoints

### 📋 Future Enhancements
- **Translation File Upload**: Currently requires manual bash script upload to service
  - Translation file: `/Users/deanzion/Downloads/Polski-updated3.json.json`
  - Future: Implement SSH/SCP upload or wait for API endpoint

## Prerequisites

- Python 3.9 or higher
- Chrome browser installed on macOS
- Access to OnWatch system
- Access to Rancher UI

## Installation

1. Clone or navigate to this directory:
```bash
cd /Users/deanzion/Work/DataPopulationOnWatch
```

2. Install Python dependencies:
```bash
pip install -r requirements.txt
```

3. Install Playwright browsers:
```bash
playwright install chromium
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
python main.py
```

### With Custom Config File

```bash
python main.py --config my-config.yaml
```

### Headless Mode

Run browser automation in headless mode (no visible browser):
```bash
python main.py --headless
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

The automation primarily uses **REST API** and **GraphQL** for fast, reliable configuration:

1. **REST API** (via `ClientApi`): 
   - Watch list population
   - System settings (PATCH `/bt/api/settings`)
   - Acknowledge actions
   - Logo uploads
2. **GraphQL API**: 
   - KV parameters (mutation `updateSingleSetting`)
3. **Browser Automation** (via Playwright): 
   - Fallback for operations without API endpoints
   - Available for future UI-based configurations
4. **Rancher Automation**: 
   - For setting Kubernetes pod environment variables (when implemented)

## Customization

### API Endpoints

If your OnWatch API endpoints differ from the defaults, update them in `client_api.py`:
- Login endpoint
- Subject creation endpoint
- Face extraction endpoint
- Groups endpoint

### UI Selectors

The UI automation uses CSS selectors to find elements. If your UI structure differs, update selectors in `ui_automation.py`:
- Login form selectors
- Settings page selectors
- Device configuration selectors

### Rancher UI

Rancher UI structure may vary by version. Update selectors in `rancher_automation.py` if needed.

## Troubleshooting

### Login Issues

- Verify IP address and credentials in `config.yaml`
- Check network connectivity to OnWatch system
- Ensure SSL certificate issues are handled (script disables SSL verification)

### UI Automation Issues

- Run without `--headless` flag to see what's happening
- Check browser console for errors
- Verify UI selectors match your OnWatch version
- Adjust timeouts in `ui_automation.py` if pages load slowly

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
python main.py 2>&1 | tee automation.log
```

## Notes

- The script disables SSL verification for self-signed certificates
- Browser automation runs in visible mode by default for debugging
- Some UI selectors may need adjustment based on your OnWatch version
- File upload functionality may need implementation based on your UI structure

## Support

For issues or questions:
1. Check the logs for error messages
2. Verify configuration file format (YAML syntax)
3. Test individual components (API, UI, Rancher) separately
4. Review and adjust selectors/endpoints as needed

## Example Workflow

1. Install fresh OnWatch system
2. Update `config.yaml` with your settings and image paths
3. Run `python main.py`
4. Monitor console output for progress
5. Verify settings in OnWatch UI after completion

## Current Status

### Working Features
- ✅ KV Parameters (Step 2) - GraphQL API
- ✅ System Settings (Step 3) - REST API with acknowledge actions and logo uploads
- ✅ Watch List (Step 6) - REST API with multiple images per subject

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

