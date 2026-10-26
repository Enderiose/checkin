# checkin - Auto Check-in Configuration File
# Modify the following configuration to suit your environment
#
# Third-party notice: the check-in implementation scripts referenced below come from
# upstream projects. See THIRD_PARTY_NOTICES.md for sources, authors and licenses.
#   - trae-daily-checkin       : https://github.com/BlueChonk/trae-daily-checkin
#   - workbuddy-checkin        : https://github.com/GitOfUser/workbuddy-checkin

import os
import sys

# ============================================================
# Project Directory
# ============================================================
# All project-relative paths are resolved from the location of THIS file,
# so the project keeps working no matter where it is moved/renamed and
# no matter what the current working directory is (the scheduled task
# starts in C:\Windows\System32).
PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))

# ============================================================
# Application Path Configuration
# ============================================================

# Trae SOLO CN path
# Default: C:\Users\Administrator\AppData\Local\Programs\TRAE SOLO CN\TRAE SOLO CN.exe
TRAE_EXE = r"C:\Users\Administrator\AppData\Local\Programs\TRAE SOLO CN\TRAE SOLO CN.exe"

# WorkBuddy path
# Default: C:\Users\Administrator\AppData\Local\Programs\WorkBuddy\WorkBuddy.exe
WORKBUDDY_EXE = r"C:\Users\Administrator\AppData\Local\Programs\WorkBuddy\WorkBuddy.exe"

# ============================================================
# Runtime (interpreter) Configuration
# ============================================================

# Python used to launch the WorkBuddy check-in script.
# Prefers the very same interpreter that runs auto_checkin.py (works even when
# "python" is not on PATH inside the scheduled-task environment).
_PYTHON = sys.executable if sys.executable else "python"
PYTHON_EXE = os.environ.get("CHECKIN_PYTHON_EXE", _PYTHON)

# Node.js used to launch the Trae check-in script (must be on PATH).
NODE_EXE = os.environ.get("CHECKIN_NODE_EXE", "node")

# ============================================================
# Check-in Script Path Configuration
# ============================================================

# Trae check-in script path (relative to this project directory, usually no need to modify)
# Vendored from https://github.com/BlueChonk/trae-daily-checkin (MIT)
TRAE_CHECKIN_SCRIPT = os.path.join(PROJECT_DIR, "trae-daily-checkin", "src", "auto-checkin.mjs")

# WorkBuddy check-in script path (relative to this project directory, usually no need to modify)
# Vendored from https://github.com/GitOfUser/workbuddy-checkin
WORKBUDDY_CHECKIN_SCRIPT = os.path.join(PROJECT_DIR, "workbuddy-checkin", "scripts", "checkin_py.py")

# ============================================================
# Check-in Coordinate Configuration (WorkBuddy only)
# ============================================================
# These values ARE applied: scripts/auto_checkin.py injects them into the vendored
# script through the WORKBUDDY_* environment variables (small local patch at the top
# of workbuddy-checkin/scripts/checkin_py.py). Change them here, not in the script.
#
# Values below were measured on THIS machine (2560x1440, 125% scaling) by hovering the
# mouse over the target and reading GetCursorPos - see README for the one-liner.

# WorkBuddy user-menu (avatar) coordinates - only used when WORKBUDDY_SKIP_MENU is False
WORKBUDDY_MENU_X = 67
WORKBUDDY_MENU_Y = 1330

# WorkBuddy check-in button coordinates
# On this machine WorkBuddy shows the check-in button directly on the home page.
WORKBUDDY_CHECKIN_X = 259
WORKBUDDY_CHECKIN_Y = 1250

# Skip the "click the avatar to open the user menu" step and check in directly from the
# home page (True = current WorkBuddy layout, measured above; False = upstream behaviour:
# avatar click, 3s menu wait, re-activate window, then click the check-in button).
WORKBUDDY_SKIP_MENU = True

# ============================================================
# Check-in Reliability (WorkBuddy only)
# ============================================================
# The upstream script clicks blindly: it reports success whenever no exception is raised,
# so an unloaded page or a window that is not in the foreground silently "succeeds".
# With verification enabled the script waits for the white check-in button to appear,
# makes sure the window is really in the foreground, clicks, compares screenshots before/
# after and retries when nothing changed. Set to False to restore the upstream behaviour.
WORKBUDDY_VERIFY = True

# Seconds to wait for the check-in button to render before giving up (button missing is
# treated as "already checked in today", which is the normal state after a check-in).
WORKBUDDY_READY_TIMEOUT = 20

# How many times the click is retried while the UI shows no change.
WORKBUDDY_MAX_TRIES = 3

# Seconds to wait after a successful check-in before closing WorkBuddy (lets it sync).
WORKBUDDY_CLOSE_DELAY = 3

# Resolution the coordinates above were calibrated on. auto_checkin.py warns when this
# machine's screen differs, because a maximized WorkBuddy window lays its buttons out
# differently and the hard-coded clicks would then miss their target.
WORKBUDDY_COORD_BASELINE = (2560, 1440)

# ============================================================
# Web Check-in (silent HTTP first, headless browser fallback)
# ============================================================
# The site list lives in `.config` (TOML, read with the Python 3.11+ stdlib).
# Copy the template once and edit it:
#     cp .config.example .config        (Windows: copy .config.example .config)
# Each site only needs a name and a url; see .config.example for the format.

# Site list file (git-ignored; the committed template is .config.example)
WEB_CONFIG_PATH = os.path.join(PROJECT_DIR, ".config")

# Web check-in script (relative to this project directory, usually no need to modify)
WEB_CHECKIN_SCRIPT = os.path.join(PROJECT_DIR, "scripts", "web_checkin.py")

# Per-request timeout (seconds) for the silent HTTP attempt and for page loads
WEB_TIMEOUT = 30

# Seconds to wait for the result after clicking a check-in button in the browser
WEB_VERIFY_TIMEOUT = 15

# Total timeout (seconds) for the whole web check-in child process
WEB_CHECKIN_TIMEOUT = 300

# Use a headless browser for the fallback (False = show the window, for debugging)
WEB_HEADLESS = True

# Which browser the web fallback uses:
#   "auto"   = Chrome first, Edge only if Chrome cannot start (default)
#   "chrome" = only Chrome
#   "edge"   = only Edge
WEB_BROWSER = "auto"

# Saved cookies (cookies/<site>.json) and browser profiles. Git-ignored.
WEB_COOKIE_DIR = os.path.join(PROJECT_DIR, "cookies")

# Fallback screenshots (screenshots/<site>_<tag>_<timestamp>.png). Git-ignored.
WEB_SCREENSHOT_DIR = os.path.join(PROJECT_DIR, "screenshots")

# ============================================================
# Timeout Configuration (seconds)
# ============================================================

# Trae check-in timeout
TRAE_TIMEOUT = 120

# WorkBuddy check-in timeout
WORKBUDDY_TIMEOUT = 60

# Wait time between check-in tasks
WAIT_BETWEEN_TASKS = 5

# ============================================================
# Log Configuration
# ============================================================

# Directory for daily log files (auto-created). Logs record every run, every
# sub-process exit code and every unhandled exception with full traceback.
LOG_DIR = os.path.join(PROJECT_DIR, "logs")

# Log files older than this many days are deleted automatically (0 = keep forever)
LOG_KEEP_DAYS = 30

# Also echo log lines to stdout (console window). Set to False to write files only.
LOG_CONSOLE = True

# ============================================================
# Startup (scheduled task) Behaviour
# ============================================================
# Used only when the script is started by the scheduled task (--startup).

# Wait until the interactive desktop is actually ready before touching the GUI apps.
# This is what protects against "started too early right after logon".
WAIT_FOR_DESKTOP = True

# Maximum seconds to wait for the desktop (Windows shell) to become ready.
DESKTOP_READY_TIMEOUT = 300

# Polling interval while waiting for the desktop (seconds)
DESKTOP_POLL_INTERVAL = 3

# Extra settle time after the desktop is detected, so Explorer finishes launching (seconds)
DESKTOP_SETTLE_SECONDS = 5