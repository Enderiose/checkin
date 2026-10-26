#!/usr/bin/env python3
"""
Full Test Script - Validate all components
"""

import os
import sys
import subprocess
from datetime import datetime

def log(message, level="INFO"):
    """Print log with timestamp"""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{timestamp}] [{level}] {message}")

def test_python():
    """Test Python environment"""
    log("Testing Python environment...")
    try:
        result = subprocess.run([sys.executable, "--version"], capture_output=True, text=True)
        if result.returncode == 0:
            log(f"Python version: {result.stdout.strip()}", "SUCCESS")
            return True
        else:
            log("Python test failed", "ERROR")
            return False
    except Exception as e:
        log(f"Python test exception: {str(e)}", "ERROR")
        return False

def test_node():
    """Test Node.js environment"""
    log("Testing Node.js environment...")
    try:
        result = subprocess.run(["node", "--version"], capture_output=True, text=True)
        if result.returncode == 0:
            log(f"Node.js version: {result.stdout.strip()}", "SUCCESS")
            return True
        else:
            log("Node.js test failed", "ERROR")
            return False
    except Exception as e:
        log(f"Node.js test exception: {str(e)}", "ERROR")
        return False

def test_config():
    """Test configuration file"""
    log("Testing configuration file...")
    try:
        sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        from config import TRAE_EXE, WORKBUDDY_EXE, TRAE_CHECKIN_SCRIPT, WORKBUDDY_CHECKIN_SCRIPT
        
        log(f"Trae path: {TRAE_EXE}")
        log(f"WorkBuddy path: {WORKBUDDY_EXE}")
        log(f"Trae check-in script: {TRAE_CHECKIN_SCRIPT}")
        log(f"WorkBuddy check-in script: {WORKBUDDY_CHECKIN_SCRIPT}")
        
        # Check if paths exist
        paths_to_check = [
            (TRAE_EXE, "Trae SOLO CN"),
            (WORKBUDDY_EXE, "WorkBuddy"),
            (TRAE_CHECKIN_SCRIPT, "Trae check-in script"),
            (WORKBUDDY_CHECKIN_SCRIPT, "WorkBuddy check-in script")
        ]
        
        all_ok = True
        for path, name in paths_to_check:
            if os.path.exists(path):
                log(f"[OK] {name}: {path}", "SUCCESS")
            else:
                log(f"[ERROR] {name}: {path} not found", "ERROR")
                all_ok = False
        
        return all_ok
        
    except ImportError as e:
        log(f"Config file import failed: {str(e)}", "ERROR")
        return False
    except Exception as e:
        log(f"Config file test exception: {str(e)}", "ERROR")
        return False

def test_trae_script():
    """Test Trae check-in script"""
    log("Testing Trae check-in script...")
    try:
        script_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 
                                   "trae-daily-checkin", "src", "auto-checkin.mjs")
        
        if not os.path.exists(script_path):
            log(f"Trae check-in script not found: {script_path}", "ERROR")
            return False
        
        # Test help command
        result = subprocess.run(["node", script_path, "--help"], capture_output=True, text=True, timeout=10)
        if result.returncode == 0:
            log("Trae check-in script help command test successful", "SUCCESS")
            return True
        else:
            log(f"Trae check-in script help command test failed: {result.stderr}", "ERROR")
            return False
            
    except Exception as e:
        log(f"Trae check-in script test exception: {str(e)}", "ERROR")
        return False

def test_workbuddy_script():
    """Test WorkBuddy check-in script"""
    log("Testing WorkBuddy check-in script...")
    try:
        script_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 
                                   "workbuddy-checkin", "scripts", "checkin_py.py")
        
        if not os.path.exists(script_path):
            log(f"WorkBuddy check-in script not found: {script_path}", "ERROR")
            return False
        
        # Test syntax check
        result = subprocess.run([sys.executable, "-m", "py_compile", script_path], 
                               capture_output=True, text=True, timeout=10)
        if result.returncode == 0:
            log("WorkBuddy check-in script syntax check successful", "SUCCESS")
            return True
        else:
            log(f"WorkBuddy check-in script syntax check failed: {result.stderr}", "ERROR")
            return False
            
    except Exception as e:
        log(f"WorkBuddy check-in script test exception: {str(e)}", "ERROR")
        return False

def test_web_script():
    """Test web check-in script (config may legitimately be empty)"""
    log("Testing web check-in script...")
    try:
        project = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        script_path = os.path.join(project, "scripts", "web_checkin.py")
        if not os.path.exists(script_path):
            log(f"Web check-in script not found: {script_path}", "ERROR")
            return False
        # --list exits 0 with sites and 2 when .config has none yet; both prove
        # the script and the config parser work.
        result = subprocess.run([sys.executable, script_path, "--list"],
                                capture_output=True, text=True, timeout=30)
        if result.returncode in (0, 2):
            log("Web check-in script loaded the config successfully", "SUCCESS")
            return True
        log(f"Web check-in script test failed (exit {result.returncode}): {result.stderr}", "ERROR")
        return False
    except Exception as e:
        log(f"Web check-in script test exception: {str(e)}", "ERROR")
        return False

def test_task_scheduler():
    """Test Task Scheduler"""
    log("Testing Task Scheduler...")
    try:
        # Check if task exists
        result = subprocess.run(["schtasks", "/Query", "/TN", "AutoCheckinOnStartup"], 
                               capture_output=True, text=True, timeout=10)
        if result.returncode == 0:
            log("Task Scheduler task exists", "SUCCESS")
            return True
        else:
            log("Task Scheduler task does not exist (needs installation)", "WARN")
            return False
            
    except Exception as e:
        log(f"Task Scheduler test exception: {str(e)}", "ERROR")
        return False

def main():
    """Main function"""
    log("=" * 60)
    log("Full Test Started")
    log("=" * 60)
    
    results = {}
    
    # Test environment
    results["python"] = test_python()
    results["node"] = test_node()
    results["config"] = test_config()
    results["trae_script"] = test_trae_script()
    results["workbuddy_script"] = test_workbuddy_script()
    results["web_script"] = test_web_script()
    results["task_scheduler"] = test_task_scheduler()
    
    # Output summary
    log("=" * 60)
    log("Test Results Summary:")
    
    for test_name, result in results.items():
        status = "[PASS]" if result else "[FAIL]"
        log(f"  {test_name}: {status}")
    
    # Count
    passed = sum(results.values())
    total = len(results)
    
    log(f"\nTotal: {passed}/{total} tests passed")
    
    if passed == total:
        log("All tests passed! System is ready.", "SUCCESS")
        return 0
    elif passed > 0:
        log(f"Partial tests passed ({passed}/{total})", "WARN")
        return 0
    else:
        log("All tests failed", "ERROR")
        return 1

if __name__ == "__main__":
    exit(main())
