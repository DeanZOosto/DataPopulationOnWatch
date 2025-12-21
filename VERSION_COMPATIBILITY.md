# Version Compatibility Guide

This project supports both **OnWatch 2.6** and **OnWatch 2.8** systems.

## Overview

The automation tool automatically detects the OnWatch version or can be configured manually. Most functionality works identically across both versions, but some API endpoints and behaviors may differ.

## Version Detection

### Automatic Detection (Recommended)

The tool will automatically detect the OnWatch version after login by querying the API:

```bash
python3 main.py
# Output: API client initialized and logged in (OnWatch 2.6)
# or
# Output: API client initialized and logged in (OnWatch 2.8)
```

### Manual Configuration

If auto-detection fails or you want to specify the version explicitly, add it to `config.yaml`:

```yaml
onwatch:
  ip_address: "10.1.71.14"
  username: "Administrator"
  password: "pa$$word!"
  base_url: "https://10.1.71.14"
  version: "2.8"  # Specify "2.6" or "2.8"
```

## Supported Versions

- **OnWatch 2.6** - Fully supported (original development target)
- **OnWatch 2.8** - Fully supported (newer version)

## Version-Specific Behavior

### API Endpoints

Both versions use the same base API path (`/bt/api`), but endpoint priorities may differ:

- **KV Parameters**: Different REST endpoints may be preferred
- **GraphQL Queries**: Query patterns are optimized per version
- **System Settings**: Same endpoints, same behavior

### GraphQL Queries

The tool tries multiple GraphQL query patterns to find one that works. Version-specific optimizations:

- **2.6**: Uses standard query patterns
- **2.8**: May prefer alternative query patterns (if API differs)

### Priority Mappings

Inquiry case priorities use the same mapping for both versions:
- Low: 201
- Medium: 101
- High: 1

## Testing on Both Versions

### For OnWatch 2.6

```bash
# Option 1: Let it auto-detect
python3 main.py

# Option 2: Specify explicitly
# Edit config.yaml: version: "2.6"
python3 main.py
```

### For OnWatch 2.8

```bash
# Option 1: Let it auto-detect
python3 main.py

# Option 2: Specify explicitly
# Edit config.yaml: version: "2.8"
python3 main.py
```

## Known Differences

### API Response Formats

Some API responses may have slightly different structures between versions. The code handles these differences automatically.

### GraphQL Schema

The GraphQL schema may have minor differences. The tool tries multiple query patterns to ensure compatibility.

### Endpoint Availability

Some endpoints may be available in one version but not the other. The tool gracefully handles missing endpoints.

## Troubleshooting

### Version Detection Fails

**Symptom:** Tool defaults to 2.6 even on 2.8 system

**Solution:**
1. Manually specify version in `config.yaml`:
   ```yaml
   onwatch:
     version: "2.8"
   ```
2. Check API connectivity (version detection requires API access)

### API Calls Fail on 2.8

**Symptom:** Errors like "Endpoint not found" or "GraphQL error"

**Solution:**
1. Verify version is correctly detected/specified
2. Check if endpoint exists in 2.8 (may have changed)
3. Run with `--verbose` to see detailed API calls
4. Report the issue with version and error details

### Validation Fails on 2.8

**Symptom:** Validation script reports items as missing on 2.8

**Solution:**
1. Ensure version is specified in config.yaml used for validation
2. Check if API endpoints for validation differ in 2.8
3. Run validation with `--verbose` for details

## Version in Export Files

Export files now include the OnWatch version in metadata:

```yaml
metadata:
  generated_at: '2025-01-15 10:30:00'
  onwatch_ip: 10.1.71.14
  onwatch_version: 2.8  # Version used during population
  total_duration: 17.8s
```

This helps ensure validation uses the correct version-specific logic.

## Backward Compatibility

- **Default behavior**: If version is not specified, defaults to 2.6 (backward compatible)
- **Auto-detection**: Attempts to detect version but falls back to 2.6 if detection fails
- **Existing configs**: Work without modification (version is optional)

## Contributing Version-Specific Fixes

If you discover version-specific differences:

1. Update `version_compat.py` with version-specific logic
2. Add tests in `tests/test_version_compat.py`
3. Document differences in this guide
4. Test on both versions before submitting

## Support

For version-specific issues:
1. Check this guide first
2. Run with `--verbose` to see version detection
3. Verify version in export file metadata
4. Report issues with version information included
