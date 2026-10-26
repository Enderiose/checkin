#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Test Script - Validate application and script paths

All paths come from config.py, so this test can never drift away from what
scripts/auto_checkin.py actually uses.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from config import (
        PROJECT_DIR, TRAE_EXE, WORKBUDDY_EXE,
        TRAE_CHECKIN_SCRIPT, WORKBUDDY_CHECKIN_SCRIPT,
        PYTHON_EXE, NODE_EXE, LOG_DIR,
        WEB_CHECKIN_SCRIPT, WEB_CONFIG_PATH,
    )
except Exception as exc:                                       # noqa: BLE001
    print("[ERROR] Could not import config.py: %s: %s" % (type(exc).__name__, exc))
    sys.exit(1)


def test_path(path, name):
    """Test if path exists"""
    if path and os.path.exists(path):
        print("[OK] %s: %s" % (name, path))
        return True
    print("[ERROR] %s: %s not found" % (name, path))
    return False


def main():
    print("=" * 60)
    print("Path Validation Test")
    print("=" * 60)
    print()
    print("Project directory: %s" % PROJECT_DIR)
    print("Python executable: %s" % PYTHON_EXE)
    print("Node executable:   %s" % NODE_EXE)
    print()

    results = []

    print("Application Paths:")
    results.append(test_path(TRAE_EXE, "Trae SOLO CN"))
    results.append(test_path(WORKBUDDY_EXE, "WorkBuddy"))

    print()
    print("Check-in Script Paths:")
    results.append(test_path(TRAE_CHECKIN_SCRIPT, "Trae Check-in Script"))
    results.append(test_path(WORKBUDDY_CHECKIN_SCRIPT, "WorkBuddy Check-in Script"))
    results.append(test_path(WEB_CHECKIN_SCRIPT, "Web Check-in Script"))

    print()
    print("Web Check-in Config:")
    if os.path.exists(WEB_CONFIG_PATH):
        print("[OK] Web site config: %s" % WEB_CONFIG_PATH)
    else:
        print("[WARN] Web site config missing: %s" % WEB_CONFIG_PATH)
        print("       create it with:  cp .config.example .config")
        print("       (only needed for the web check-in; not counted as a failure)")

    print()
    print("Log Directory:")
    print("[OK] Logs are written to: %s" % LOG_DIR)

    print()
    print("=" * 60)

    success_count = sum(results)
    total_count = len(results)

    if success_count == total_count:
        print("All paths validated successfully!")
    else:
        print("Path validation failed: %d path(s) have issues" % (total_count - success_count))

    print("=" * 60)

    return 0 if success_count == total_count else 1


if __name__ == "__main__":
    sys.exit(main())