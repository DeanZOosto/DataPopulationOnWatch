# Post-Upgrade Validation Guide

This guide explains how to validate OnWatch system data after running the population automation and after system upgrades.

## Overview

The validation process ensures that all data populated by the automation tool is still present and correct after:
- Initial population
- System upgrades
- Configuration changes
- Any system maintenance

## Prerequisites

- Python 3.9 or higher
- Access to the OnWatch system (same network/IP as used during population)
- The output YAML file generated after running the population script
- OnWatch admin credentials (same as used during population)

## Quick Start

### Step 1: Run Population Script

First, run the population automation to create the baseline data:

```bash
python3 main.py
```

This generates an output file like: `onwatch_data_export_2025-01-15_10-30-00.yaml`

### Step 2: Validate After Population

Immediately after population, validate that everything was created correctly:

```bash
python3 validate_data.py onwatch_data_export_2025-01-15_10-30-00.yaml
```

### Step 3: Validate After Upgrade

After upgrading your OnWatch system, run validation again:

```bash
python3 validate_data.py onwatch_data_export_2025-01-15_10-30-00.yaml
```

This ensures the upgrade didn't cause data loss or modifications.

## Usage

### Basic Validation

```bash
# Validate using the most recent export file
python3 validate_data.py onwatch_data_export_2025-01-15_10-30-00.yaml
```

### With Custom Config File

If your OnWatch system IP or credentials have changed:

```bash
python3 validate_data.py output.yaml --config my-config.yaml
```

### Verbose Mode

For detailed validation output:

```bash
python3 validate_data.py output.yaml --verbose
```

### Help

```bash
python3 validate_data.py --help
```

## What Gets Validated

The validation script checks the following:

### 1. KV Parameters
- Verifies all key-value parameters exist
- Compares values (handles type conversions: string vs number)
- Validates `DEFAULT/` prefixed parameters via REST API
- Validates `applicationSettings/` parameters via GraphQL

### 2. System Settings
- General settings (thresholds, retention periods)
- System interface (product name, logos, favicon)
- Engine settings (video storage, detection storage)

### 3. Subject Groups
- Verifies groups exist by name
- Checks authorization and visibility settings

### 4. User Accounts
- Verifies users exist by username
- Validates role assignments

### 5. Watch List Subjects
- Verifies subjects exist by name
- Validates image count matches expected
- Checks subject group assignments

### 6. Cameras/Devices
- Verifies cameras exist by name
- Validates video URLs and modes

### 7. Inquiry Cases
- Verifies inquiry cases exist by name
- Case-insensitive matching

### 8. Mass Import
- Verifies mass import exists by name or ID

### 9. Rancher Environment Variables
- Connects to Rancher API
- Validates environment variables in Kubernetes workload
- Compares values from config.yaml

## Validation Output

### Success Example

```
================================================================================
OnWatch Data Validation
================================================================================

Loading output YAML: onwatch_data_export_2025-01-15_10-30-00.yaml
✓ Output YAML loaded successfully

Initializing API client...
✓ Successfully logged in to the OnWatch server at IP: 10.1.71.14

🔧 Validating 5 KV parameters...
  ✓ KV parameter 'applicationSettings/watchVideo/secondsAfterDetection' = '6'
  ✓ KV parameter 'applicationSettings/defaultFaceThreshold' = '0.6'
  ...

🔍 Validating 1 inquiry cases...
  ✓ Inquiry case 'upgrade test' exists

📊 Validation Summary:
  Total Items: 25
  ✅ Passed: 25
  ❌ Failed: 0
  ⚠️  Warnings: 0

✅ VALIDATION PASSED - All data is present and correct
================================================================================
```

### Failure Example

```
❌ ERROR Details (2):
  • KV parameter 'applicationSettings/test': NOT FOUND
  • Subject 'Test Subject': NOT FOUND

📊 Validation Summary:
  Total Items: 25
  ✅ Passed: 23
  ❌ Failed: 2
  ⚠️  Warnings: 0

❌ VALIDATION FAILED - 2 item(s) are missing or incorrect
================================================================================
```

## Understanding Validation Results

### ✅ Passed
- Item exists and values match (or are equivalent after type conversion)
- All checks passed successfully

### ❌ Failed
- Item not found in system
- Value mismatch (after type conversion)
- Configuration error

### ⚠️ Warnings
- Non-critical issues
- Items that may need manual review

## Common Issues and Solutions

### KV Parameter Not Found

**Error:** `KV parameter 'DEFAULT/collate-service/TRACKS_RETENTION_TIME_MS': NOT FOUND`

**Possible Causes:**
- Parameter was never set
- Parameter was deleted
- API endpoint changed

**Solution:**
- Verify parameter exists in config.yaml
- Re-run population script to set the parameter
- Check if parameter name is correct

### Subject Not Found

**Error:** `Subject 'Test Subject': NOT FOUND`

**Possible Causes:**
- Subject was never created
- Subject was deleted
- Subject name mismatch (case-sensitive)

**Solution:**
- Verify subject exists in config.yaml
- Re-run population script: `python3 main.py --step populate-watchlist`
- Check subject name spelling (validation is case-insensitive)

### Rancher Environment Variables Not Found

**Error:** `Environment variable 'ENABLE_DVR': NOT FOUND`

**Possible Causes:**
- Rancher API not accessible
- Workload path incorrect
- Environment variable not set

**Solution:**
- Verify Rancher configuration in config.yaml
- Check Rancher API connectivity
- Re-run: `python3 main.py --step configure-rancher`

### Value Mismatch

**Error:** `KV parameter 'applicationSettings/test': Value mismatch (expected: '6', actual: '7')`

**Possible Causes:**
- Value was changed manually
- Value was changed by another process
- Type conversion issue

**Solution:**
- Verify expected value in output YAML
- Check if value was intentionally changed
- Re-run population to restore value: `python3 main.py --step set-kv-params`

## Best Practices

### 1. Validate Immediately After Population

Always validate right after running the population script to catch any issues early:

```bash
# Run population
python3 main.py

# Immediately validate
python3 validate_data.py onwatch_data_export_2025-01-15_10-30-00.yaml
```

### 2. Validate Before Upgrade

Before upgrading, validate to establish a baseline:

```bash
python3 validate_data.py onwatch_data_export_2025-01-15_10-30-00.yaml > validation_before_upgrade.log
```

### 3. Validate After Upgrade

After upgrading, validate again to ensure data integrity:

```bash
python3 validate_data.py onwatch_data_export_2025-01-15_10-30-00.yaml > validation_after_upgrade.log
```

### 4. Compare Results

Compare before/after validation results:

```bash
diff validation_before_upgrade.log validation_after_upgrade.log
```

### 5. Keep Export Files

Keep all export files for reference:

- `onwatch_data_export_2025-01-15_10-30-00.yaml` - Initial population
- `onwatch_data_export_2025-01-20_14-30-00.yaml` - After upgrade
- etc.

## Troubleshooting

### Validation Script Fails to Connect

**Error:** `Login failed to OnWatch system`

**Solution:**
- Verify IP address in config.yaml matches current system IP
- Check network connectivity
- Verify credentials are correct

### Output YAML File Not Found

**Error:** `File not found: onwatch_data_export_2025-01-15_10-30-00.yaml`

**Solution:**
- Check file name (case-sensitive)
- Verify file exists in current directory
- Use full path: `python3 validate_data.py /path/to/file.yaml`

### Rancher Validation Fails

**Error:** `Could not discover project_id from default namespace`

**Solution:**
- Verify Rancher API is accessible
- Check Rancher credentials in config.yaml
- Ensure namespace 'default' exists

## Advanced Usage

### Validate Specific Categories

The validation script validates all categories by default. To focus on specific areas, you can modify the validation script or use verbose mode to see detailed output for each category.

### Custom Validation

For custom validation needs, you can:
1. Modify `validate_data.py` to add custom checks
2. Use the `DataValidator` class programmatically
3. Create custom validation scripts using the same API clients

## Integration with CI/CD

The validation script can be integrated into CI/CD pipelines:

```bash
# Exit code 0 = success, 1 = failure
python3 validate_data.py output.yaml
if [ $? -eq 0 ]; then
    echo "Validation passed"
else
    echo "Validation failed"
    exit 1
fi
```

## Support

For issues with validation:
1. Run with `--verbose` flag for detailed output
2. Check error messages (they include troubleshooting hints)
3. Verify config.yaml matches the system configuration
4. Ensure export YAML file is from the same system

## Related Documentation

- **USER_GUIDE.md** - How to run the population automation
- **README.md** - Quick start and overview
- **TESTING.md** - Information about the test suite
