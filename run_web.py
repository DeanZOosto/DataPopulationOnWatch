#!/usr/bin/env python3
"""
Start the OnWatch Data Population Hub (web UI).

Usage:
    python run_web.py

Then open http://127.0.0.1:5000 in your browser.
"""
import sys
from pathlib import Path

# Ensure project root is on path
PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT))

from web.app import main

if __name__ == "__main__":
    main()
