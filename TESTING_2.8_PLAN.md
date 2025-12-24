# OnWatch 2.8 Compatibility Testing Plan

This document tracks the systematic testing and fixes needed to make the tool fully compatible with OnWatch 2.8.

## Testing Strategy

We'll test each automation step individually on a 2.8 system, identify failures, and fix them incrementally.

## Test Environment

- **OnWatch 2.8 IP:** (Update this with your 2.8 system IP)
- **Config:** `config.yaml` with `version: "2.8"`

## Step-by-Step Testing Checklist

### ✅ Step 1: API Initialization
**Command:** `python3 main.py --step init-api --verbose`

**Step ID:** `init-api`

**Status:** ⬜ Not Tested | ✅ Pass | ❌ Fail

**Notes:**
- Should successfully login
- Should log version correctly

**Issues Found:**
- 

---

### ✅ Step 2: KV Parameters
**Command:** `python3 main.py --step set-kv-params --verbose`

**Step ID:** `set-kv-params`

**Status:** ⬜ Not Tested | ✅ Pass | ❌ Fail

**Notes:**
- Tests version-specific endpoint handling
- Should set all KV parameters from config

**Issues Found:**
- 

---

### ✅ Step 3: System Settings
**Command:** `python3 main.py --step configure-system --verbose`

**Step ID:** `configure-system`

**Status:** ⬜ Not Tested | ✅ Pass | ❌ Fail

**Notes:**
- General settings
- Map settings
- Engine settings
- System interface (logos, favicon)

**Issues Found:**
- 

---

### ✅ Step 4: Devices
**Command:** `python3 main.py --step configure-devices --verbose`

**Step ID:** `configure-devices`

**Status:** ⬜ Not Tested | ✅ Pass | ❌ Fail

**Notes:**
- Device creation/configuration
- Camera configuration

**Issues Found:**
- 

---

### ✅ Step 5: Groups
**Command:** `python3 main.py --step configure-groups --verbose`

**Step ID:** `configure-groups`

**Status:** ⬜ Not Tested | ✅ Pass | ❌ Fail

**Notes:**
- Subject group creation
- Group membership

**Issues Found:**
- 

---

### ✅ Step 6: Accounts
**Command:** `python3 main.py --step configure-accounts --verbose`

**Step ID:** `configure-accounts`

**Status:** ⬜ Not Tested | ✅ Pass | ❌ Fail

**Notes:**
- User account creation
- Role assignment
- Permissions

**Issues Found:**
- 

---

### ✅ Step 7: Inquiries
**Command:** `python3 main.py --step configure-inquiries --verbose`

**Step ID:** `configure-inquiries`

**Status:** ⬜ Not Tested | ✅ Pass | ❌ Fail

**Notes:**
- Inquiry case creation
- File uploads
- Priority settings
- ROI/threshold configuration

**Issues Found:**
- 

---

### ✅ Step 8: Mass Import
**Command:** `python3 main.py --step upload-mass-import --verbose`

**Step ID:** `upload-mass-import`

**Status:** ⬜ Not Tested | ✅ Pass | ❌ Fail

**Notes:**
- Subject import from tar file
- Image processing

**Issues Found:**
- 

---

### ✅ Step 9: Watch List
**Command:** `python3 main.py --step populate-watchlist --verbose`

**Step ID:** `populate-watchlist`

**Status:** ⬜ Not Tested | ✅ Pass | ❌ Fail

**Notes:**
- Watch list population

**Issues Found:**
- 

---

### ✅ Step 10: Rancher Configuration
**Command:** `python3 main.py --step configure-rancher --verbose`

**Step ID:** `configure-rancher`

**Status:** ⬜ Not Tested | ✅ Pass | ❌ Fail

**Notes:**
- Environment variable configuration
- Kubernetes workload updates

**Issues Found:**
- 

---

### ✅ Step 11: Translation File Upload
**Command:** `python3 main.py --step upload-files --verbose`

**Step ID:** `upload-files`

---

### ✅ Step 12: Full Run
**Command:** `python3 main.py --verbose`

**Status:** ⬜ Not Tested | ✅ Pass | ❌ Fail

**Notes:**
- Complete automation run
- All steps in sequence

**Issues Found:**
- 

---

## Known Issues & Fixes

### Issue Template
```
**Step:** [Step name]
**Error:** [Error message]
**Root Cause:** [What's different in 2.8]
**Fix:** [Solution implemented]
**Status:** ⬜ Not Fixed | ✅ Fixed | 🔄 In Progress
```

---

## Version-Specific Differences Discovered

### API Endpoints
- 

### GraphQL Queries
- 

### Request/Response Formats
- 

### Behavior Differences
- 

---

## Next Steps

1. Start with Step 1 (API Initialization) - verify basic connectivity
2. Test each step individually
3. Document any failures with:
   - Error message
   - API endpoint called
   - Request/response (if available)
   - Expected vs actual behavior
4. Fix issues one by one
5. Re-test after each fix
6. Update `version_compat.py` with version-specific logic as needed

---

## Quick Test Commands

```bash
# Test single step
python3 main.py --step STEP_NAME --verbose

# Test with dry-run (no actual changes)
python3 main.py --step STEP_NAME --dry-run --verbose

# Full run
python3 main.py --verbose

# Validation only
python3 main.py --validate
```

---

## Notes

- Always use `--verbose` to see detailed API calls
- Test on a non-production system if possible
- Keep notes of what works and what doesn't
- Update this document as you test
