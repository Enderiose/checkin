@echo off
rem ============================================================
rem Show Project Information
rem ============================================================
rem NOTE: deliberately no "chcp 65001" here - schtasks prints localized (GBK)
rem text and would become unreadable in a UTF-8 console.

echo ============================================================
echo checkin - Auto Check-in Tool
echo ============================================================
echo.
echo Project Directory: %~dp0
echo.
echo Files:
echo   config.py                - Configuration file
echo   .config                  - Web check-in site list (TOML, git-ignored)
echo   .config.example          - Template: copy .config.example .config
echo   scripts\auto_checkin.py  - Main check-in script
echo   scripts\web_checkin.py   - Web check-in (silent HTTP, headless browser)
echo   scripts\browser_engine.py - Browser engine (CDP, Selenium fallback)
echo   scripts\test_paths.py    - Path test script
echo   scripts\select_targets.ps1 - Interactive target picker for the installer
echo   scripts\select_schedule.ps1 - Schedule picker (logon / daily time)
echo   scripts\clean_strays.py  - Remove stray reserved-name files (nul, con, ...)
echo   logs\                    - Daily logs (auto_checkin_*.log, web_checkin_*.log)
echo   install_startup_task.bat - Install auto check-in task
echo   uninstall_startup_task.bat - Uninstall auto check-in task
echo   test_checkin.bat         - Test check-in functionality
echo   info.bat                 - Show project information
echo.
echo Documentation:
echo   README.md                - Project documentation
echo.
echo Reference Libraries:
echo   trae-daily-checkin\      - Trae check-in library
echo   workbuddy-checkin\       - WorkBuddy check-in library
echo.
echo ============================================================
echo Quick Start:
echo   1. Run python scripts\test_paths.py to validate paths
echo   2. For web check-in: copy .config.example .config and edit it
echo   3. Run python scripts\web_checkin.py --login NAME once per site
echo   4. Double-click install_startup_task.bat to install
echo   5. Run python scripts\auto_checkin.py to test
echo ============================================================
echo.
echo Startup Task (AutoCheckinOnStartup):
schtasks /Query /TN "AutoCheckinOnStartup" /V /FO LIST 2>nul
if errorlevel 1 echo   [WARN] Task not found - run install_startup_task.bat
echo.
echo Newest log file:
set "LOGFILE="
for /f "delims=" %%f in ('dir /b /o-d "%~dp0logs\auto_checkin_*.log" 2^>nul') do (
    if not defined LOGFILE set "LOGFILE=%~dp0logs\%%f"
)
if defined LOGFILE (
    echo   %LOGFILE%
    echo   ------------------------------------------------------------
    powershell -NoProfile -Command "[Console]::OutputEncoding=[Text.Encoding]::GetEncoding(936); Get-Content -Encoding UTF8 -Tail 15 -LiteralPath '%LOGFILE%'"
    echo   ------------------------------------------------------------
) else (
    echo   No log file found yet in %~dp0logs\
)
echo.
pause >nul