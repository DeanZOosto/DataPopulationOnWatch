# Testing Guide for OnWatch 2.8

This guide helps you test the version compatibility features on an OnWatch 2.8 system.

## Pre-Testing Checklist

- [ ] OnWatch 2.8 system is accessible
- [ ] You have the IP address of the 2.8 system
- [ ] You have admin credentials for the 2.8 system
- [ ] Network connectivity is verified

## Step-by-Step Testing

### Step 1: Update Configuration

Update the IP address in `config.yaml`:

```bash
# Quick method - updates all IPs at once
python3 main.py --set-ip YOUR_2.8_IP_ADDRESS

# Or manually edit config.yaml
# Update: onwatch.ip_address, onwatch.base_url, ssh.ip_address, rancher.base_url
```

**Important:** For initial testing, you can either:
- **Option A:** Let it auto-detect version (recommended for first test)
- **Option B:** Explicitly set version in config.yaml:
  ```yaml
  onwatch:
    version: "2.8"  # Uncomment and set this
  ```

### Step 2: Validate Configuration

```bash
python3 main.py --validate
```

This ensures your config is valid before running.

### Step 3: Test Version Detection (Dry Run)

Run with verbose mode to see version detection:

```bash
python3 main.py --verbose --dry-run
```

Look for:
- `Using OnWatch version from config: 2.8` (if manually set)
- `Detected OnWatch version: 2.8` (if auto-detected)
- `API client initialized and logged in (OnWatch 2.8)`

### Step 4: Test a Single Step First

Test with a simple, low-risk step first:

```bash
# Test API connection and version detection
python3 main.py --step init-api --verbose
```

**Expected output:**
```
[Step 1/11] Initializing API client...
Detected OnWatch version: 2.8  # or "Using OnWatch version from config: 2.8"
✓ Successfully logged in to the OnWatch server at IP: YOUR_IP
API client initialized and logged in (OnWatch 2.8)
```

### Step 5: Test KV Parameters (Low Risk)

KV parameters are a good test because they're simple and reversible:

```bash
python3 main.py --step set-kv-params --verbose
```

**What to watch for:**
- Version detection works
- KV parameters are set successfully
- No version-specific errors

### Step 6: Test Full Automation (If Step 5 Works)

If the initial steps work, test full automation:

```bash
python3 main.py --verbose
```

**Monitor for:**
- Version detection/usage messages
- Any version-specific errors
- Successful completion of all steps

### Step 7: Verify Export File

Check that the export file includes version information:

```bash
# Find the most recent export file
ls -lt onwatch_data_export_*.yaml | head -1

# Check the metadata section
cat onwatch_data_export_YYYY-MM-DD_HH-MM-SS.yaml | grep -A 10 "metadata:"
```

**Expected:**
```yaml
metadata:
  generated_at: '2025-12-18 14:30:00'
  onwatch_ip: YOUR_2.8_IP
  onwatch_version: 2.8  # Should show 2.8
  total_duration: ...
```

### Step 8: Test Validation Script

Test that validation works with the 2.8 system:

```bash
# Use the export file from Step 7
python3 validate_data.py onwatch_data_export_YYYY-MM-DD_HH-MM-SS.yaml --verbose
```

**What to watch for:**
- Version detection in validation
- All items validate successfully
- No version-specific validation errors

## What to Look For

### ✅ Success Indicators

1. **Version Detection:**
   - Logs show "OnWatch 2.8" (not 2.6)
   - Export file includes `onwatch_version: 2.8`

2. **API Calls:**
   - All API calls succeed
   - No "endpoint not found" errors
   - GraphQL queries work

3. **Functionality:**
   - All steps complete successfully
   - Data is created correctly
   - Validation passes

### ⚠️ Potential Issues to Watch For

1. **Version Detection Fails:**
   - **Symptom:** Logs show "OnWatch 2.6" on a 2.8 system
   - **Solution:** Manually set `version: "2.8"` in config.yaml

2. **API Endpoint Errors:**
   - **Symptom:** "404 Not Found" or "Endpoint not available"
   - **Action:** Note which endpoint failed, may need version-specific fix

3. **GraphQL Errors:**
   - **Symptom:** "GraphQL error" or "Cannot query field"
   - **Action:** Note the query pattern that failed, may need 2.8-specific query

4. **Value Mismatches:**
   - **Symptom:** Validation shows value mismatches
   - **Action:** Check if 2.8 uses different value formats

## Debugging Tips

### Enable Verbose Logging

Always use `--verbose` when testing:

```bash
python3 main.py --verbose
```

This shows:
- Version detection attempts
- API endpoint calls
- GraphQL queries
- Detailed error messages

### Check Version Detection

If version detection seems wrong:

```bash
# Check what version is being used
python3 main.py --step init-api --verbose 2>&1 | grep -i version
```

### Save Logs

Save logs for analysis:

```bash
python3 main.py --verbose --log-file test_2.8.log
# Review the log file
cat test_2.8.log | grep -i version
cat test_2.8.log | grep -i error
```

## Reporting Issues

If you find version-specific issues, please note:

1. **Version Information:**
   - OnWatch version (2.8.x)
   - Version detection method (auto or manual)

2. **Error Details:**
   - Exact error message
   - Which step failed
   - API endpoint/GraphQL query that failed

3. **Logs:**
   - Relevant log excerpts
   - Full error stack traces (if any)

4. **Configuration:**
   - Relevant config.yaml sections (sanitize passwords)

## Quick Test Script

Here's a quick test sequence:

```bash
# 1. Update IP
python3 main.py --set-ip YOUR_2.8_IP

# 2. Validate config
python3 main.py --validate

# 3. Test version detection
python3 main.py --step init-api --verbose

# 4. Test one simple step
python3 main.py --step set-kv-params --verbose

# 5. If successful, test full run
python3 main.py --verbose --log-file test_2.8.log

# 6. Verify export file
ls -lt onwatch_data_export_*.yaml | head -1 | xargs cat | grep -A 5 "metadata:"

# 7. Test validation
python3 validate_data.py $(ls -t onwatch_data_export_*.yaml | head -1) --verbose
```

## Expected Behavior

### On First Run (Auto-Detection)

```
[Step 1/11] Initializing API client...
Detected OnWatch version: 2.8
✓ Successfully logged in to the OnWatch server at IP: YOUR_IP
API client initialized and logged in (OnWatch 2.8)
```

### In Export File

```yaml
metadata:
  onwatch_version: 2.8
```

### In Validation

```
Initializing API client...
Detected OnWatch version: 2.8
✓ Connected to OnWatch API (OnWatch 2.8)
```

## Next Steps After Testing

1. **If everything works:** Great! The version compatibility is working correctly.

2. **If issues found:**
   - Document the specific issue
   - Note which API endpoint/query failed
   - Check if it's a version-specific difference
   - Update `version_compat.py` if needed

3. **If version detection fails:**
   - Use manual version specification
   - Report the detection issue (may need API endpoint update)

## Rollback Plan

If something goes wrong:

1. **Stop the automation** (Ctrl+C)
2. **Check what was created** (review logs)
3. **Manually clean up** if needed (via UI)
4. **Report the issue** with details

The tool is designed to be safe - it skips existing items, so re-running shouldn't cause duplicates.
