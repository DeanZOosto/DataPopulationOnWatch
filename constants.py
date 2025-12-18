#!/usr/bin/env python3
"""
Constants used throughout the OnWatch Data Population Automation project.
"""

# Inquiry Case Priority Values
# These map to the actual API values used by OnWatch
INQUIRY_PRIORITY_HIGH = 1
INQUIRY_PRIORITY_MEDIUM = 101
INQUIRY_PRIORITY_LOW = 201

INQUIRY_PRIORITY_MAP = {
    "low": INQUIRY_PRIORITY_LOW,
    "medium": INQUIRY_PRIORITY_MEDIUM,
    "high": INQUIRY_PRIORITY_HIGH
}

# Default priority if not specified
INQUIRY_PRIORITY_DEFAULT = INQUIRY_PRIORITY_MEDIUM

# Timeouts and Delays (in seconds)
API_REQUEST_TIMEOUT = 30
FILE_UPLOAD_TIMEOUT = 300
ANALYSIS_WAIT_DELAY = 2
FILE_STATUS_CHECK_DELAY = 1
RETRY_DELAY = 2

# File Upload Settings
MAX_FILE_UPLOAD_RETRIES = 3
FILE_ANALYSIS_CHECK_INTERVAL = 5
FILE_ANALYSIS_MAX_WAIT = 300  # 5 minutes

# Subject Image Settings
MAX_SUBJECT_IMAGES = 10  # Maximum images per subject

# Default Values
DEFAULT_FACE_THRESHOLD = 0.6
DEFAULT_BODY_THRESHOLD = 0.61
DEFAULT_LIVENESS_THRESHOLD = 0.55

# API Endpoints
KV_PARAMETER_ENDPOINTS = [
    "/settings/kv",
    "/key-value-settings",
    "/kv-parameters",
    "/settings/key-value",
]
