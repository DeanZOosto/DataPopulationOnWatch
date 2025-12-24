# Version Compatibility Guide

This project supports both **OnWatch 2.6** and **OnWatch 2.8** systems.

## Overview

The automation tool requires you to manually specify the OnWatch version in `config.yaml`. Most functionality works identically across both versions, but some API endpoints and behaviors may differ.

## Version Configuration (Required)

**You must specify the OnWatch version in `config.yaml`:**

```yaml
onwatch:
  ip_address: "10.1.71.14"
  username: "Administrator"
  password: "pa$$word!"
  base_url: "https://10.1.71.14"
  version: "2.8"  # Required: Specify "2.6" or "2.8"
```

**Important:** The version field is **required**. The tool will raise an error if version is not specified.

To determine your OnWatch version:
- Check the UI (usually shown in Settings page or About section)
- Look for version string like "Version 2.8.0-0" or "Version 2.6.5"
- Use the major.minor version (e.g., "2.8" or "2.6")

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
# Edit config.yaml: version: "2.6"
python3 main.py
```

### For OnWatch 2.8

```bash
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

### Version Not Specified

**Symptom:** Error: "OnWatch version is required. Set 'onwatch.version' in config.yaml"

**Solution:**
1. Add version to `config.yaml`:
   ```yaml
   onwatch:
     version: "2.8"  # or "2.6"
   ```
2. Determine your OnWatch version from the UI (Settings or About page)

### API Calls Fail on 2.8

**Symptom:** Errors like "Endpoint not found" or "GraphQL error"

**Solution:**
1. Verify version is correctly specified in `config.yaml`
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

## Migration from Previous Versions

If you're upgrading from a version that had auto-detection:

1. **Add version to config.yaml** - This is now required:
   ```yaml
   onwatch:
     version: "2.6"  # or "2.8"
   ```

2. **Determine your OnWatch version** - Check the UI or system documentation

3. **Update all config files** - Ensure version is set in any config files you use

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
