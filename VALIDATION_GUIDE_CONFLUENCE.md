# OnWatch Data Validation Guide

## Overview

Validation checks that data created by the population script is still present and correct after:
- Initial population
- System upgrades
- Configuration changes or maintenance

**Prerequisites:** Python 3.9+, network access to OnWatch, the export YAML from the population run, OnWatch admin credentials (in `config.yaml`).

---

## Quick Start

**1. After population** (use the export file printed at the end of the run, or the latest one):

```
python3 validate_data.py $(ls -t onwatch_data_export_*.yaml | head -1)
```

Or with an explicit file:

```
python3 validate_data.py onwatch_data_export_2025-01-15_10-30-00.yaml
```

**2. After upgrade** – Run the same command with the same (or relevant) export file to confirm no data loss.

**Custom config or verbose:**

```
python3 validate_data.py output.yaml --config my-config.yaml
python3 validate_data.py output.yaml --verbose
python3 validate_data.py --help
```

---

## What Gets Validated

| Category | What is checked |
|----------|------------------|
| **KV parameters** | Keys exist, values match (REST + GraphQL). |
| **System settings** | General thresholds, product name, logos, favicon. |
| **Groups** | Subject groups and **user groups** (Account management → User groups) exist by name/title. |
| **User accounts** | Users exist by username, roles. |
| **Watch list subjects** | Subjects exist by name, image count. |
| **Cameras** | Cameras exist by name. |
| **Inquiry cases** | Inquiry cases exist by name (case-insensitive). |
| **Mass import** | Exists by ID when present in export. |
| **Rancher env vars** | **Not verified via API.** If the export shows they were set during population, you get a **manual check** reminder to confirm in Rancher UI. |
| **Translation file** | **Not verified via API.** You get a **manual check** reminder to confirm on the server (uploaded via SSH). |

---

## Understanding Results

- **Passed** – Item exists and matches (or equivalent).
- **Failed** – Not found, value mismatch, or error (see log for details).
- **Skipped** – Could not run (e.g. no ID in export); verify manually if needed.
- **Acknowledged** – Recorded in export but not checked on server (Rancher env vars, translation file); **manual check recommended.**

At the end you may see a **Manual verification checklist** for items that could not be verified (e.g. Rancher env vars, translation file). Use it to confirm those in the UI/server.

---

## Exit Codes

| Code | Meaning |
|------|---------|
| **0** | All checked categories passed. |
| **1** | One or more validation failures. |
| **2** | Passed but some categories skipped or acknowledged – manual verification recommended. |

---

## Common Issues

| Error / behaviour | What to do |
|-------------------|------------|
| **KV parameter NOT FOUND** | Re-run population for KV params; check parameter name in config/export. |
| **Subject / User group NOT FOUND** | Confirm name in config; re-run the relevant step (e.g. populate-watchlist, configure-accounts). |
| **Inquiry case NOT FOUND** | Confirm name; check config and export. |
| **Value mismatch** | Compare export vs current system; re-run population to restore if needed. |
| **Login/connection failed** | Check IP, credentials, and network (config.yaml). |
| **Export file not found** | Use correct path or `ls -t onwatch_data_export_*.yaml \| head -1` for latest. |
| **Rancher / translation** | No API check; use the **manual verification checklist** and confirm in Rancher UI and on the server. |

---

## Best Practices

1. **Validate right after population** – Use the export path printed at the end of `python3 main.py`.
2. **Before/after upgrade** – Run validation before and after, save logs, then `diff` them.
3. **Keep export files** – Name them so you know which run or upgrade they belong to.
4. **Manual checks** – When you see “Acknowledged” or the checklist, confirm Rancher env vars and translation file in the UI/server.
