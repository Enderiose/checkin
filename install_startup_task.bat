@echo off
chcp 65001 >nul
setlocal
rem ============================================================
rem Install Auto Check-in Task on Windows Startup
rem ============================================================
rem The task runs either AFTER USER LOGON (delayed by STARTUP_DELAY) or EVERY DAY at a
rem fixed time, whichever is picked during the install.
rem The logon delay exists because running the check-in during the first seconds of a logon
rem makes the GUI automation (Trae launch / WorkBuddy clicks) fail, because the desktop
rem shell and the background services are not ready yet.
rem
rem Every run writes a diagnostic log to  logs\install_task.log
rem so that a failed install is never silent again.
rem ============================================================

rem ---- Settings (edit here if needed) ------------------------
set "TASK_NAME=AutoCheckinOnStartup"
rem Delay after logon before the check-in starts, format MINUTES:SECONDS
set "STARTUP_DELAY=0002:00"
rem Default check-in target when nothing is chosen: all | apps | trae | workbuddy | web
set "DEFAULT_TARGET=all"
rem Default schedule when nothing is chosen: logon | daily
rem   logon = after logon + STARTUP_DELAY
rem   daily = every day at a fixed time (asked interactively / given on the command line)
set "DEFAULT_SCHEDULE=logon"
rem ------------------------------------------------------------

rem Keep our own path BEFORE any SHIFT (shift also moves %0)
set "SELF=%~f0"

rem ---- Project paths + install log ---------------------------
set "PROJECT_DIR=%~dp0"
if "%PROJECT_DIR:~-1%"=="\" set "PROJECT_DIR=%PROJECT_DIR:~0,-1%"
set "SCRIPT_PATH=%PROJECT_DIR%\scripts\auto_checkin.py"
set "LOG_DIR=%PROJECT_DIR%\logs"
if not exist "%LOG_DIR%" mkdir "%LOG_DIR%" >nul 2>nul
set "LOG=%LOG_DIR%\install_task.log"

rem ---- Command line arguments --------------------------------
rem   quiet     : never wait for a key press (unattended / elevated use)
rem   elevated  : internal flag set by the re-launch after UAC elevation (ignored)
rem   trae      : install a task that only checks in Trae
rem   workbuddy : install a task that only checks in WorkBuddy
rem   web       : install a task that only checks in the .config web sites
rem   all       : install a task that checks in everything (default)
rem   apps      : install a task that checks in Trae + WorkBuddy
rem   trae web  : any combination of targets is accepted (a quoted "trae,web" too)
rem   1|2|3     : same as the single-item menu entries
rem   logon     : run after logon (default)
rem   daily     : run every day at a time (asks for the time)
rem   21:30     : run every day at that time (also 9:30PM)
set "TARGET="
set "QUIET="
set "SCHEDULE_MODE="
set "SCHEDULE_TIME="
rem cmd splits unquoted arguments on commas, so both "trae web" and the quoted
rem form "trae,web" are accepted; every token is accumulated into TARGET.
:parse_args
if "%~1"=="" goto args_done
for %%t in (%~1) do (
    if /i "%%t"=="quiet" set "QUIET=1"
    if /i "%%t"=="trae" call :add_target trae
    if /i "%%t"=="1" call :add_target trae
    if /i "%%t"=="workbuddy" call :add_target workbuddy
    if /i "%%t"=="2" call :add_target workbuddy
    if /i "%%t"=="web" call :add_target web
    if /i "%%t"=="3" call :add_target web
    if /i "%%t"=="all" call :add_target trae
    if /i "%%t"=="all" call :add_target workbuddy
    if /i "%%t"=="all" call :add_target web
    if /i "%%t"=="apps" call :add_target trae
    if /i "%%t"=="apps" call :add_target workbuddy
    if /i "%%t"=="both" call :add_target trae
    if /i "%%t"=="both" call :add_target workbuddy
    call :add_schedule "%%t"
)
shift
goto parse_args
:args_done
call :log "==== start : args=[%*]"

rem ---- Target selection (interactive when not given) --------
if defined TARGET goto target_done
if defined QUIET (
    set "TARGET=%DEFAULT_TARGET%"
    goto target_done
)
set "SELECT_PS=%PROJECT_DIR%\scripts\select_targets.ps1"
if not exist "%SELECT_PS%" (
    call :log "target selector missing, using default %DEFAULT_TARGET%"
    set "TARGET=%DEFAULT_TARGET%"
    goto target_done
)
set "TARGET_FILE=%TEMP%\checkin_target_%RANDOM%%RANDOM%.txt"
if exist "%TARGET_FILE%" del "%TARGET_FILE%" >nul 2>nul
powershell -NoProfile -ExecutionPolicy Bypass -File "%SELECT_PS%" -OutFile "%TARGET_FILE%" -Default "%DEFAULT_TARGET%"
if exist "%TARGET_FILE%" (
    set /p TARGET=<"%TARGET_FILE%"
    del "%TARGET_FILE%" >nul 2>nul
)
if not defined TARGET set "TARGET=%DEFAULT_TARGET%"
echo.
:target_done
rem ---- Schedule selection (interactive when not given) ------
set "SCHEDULE="
if /i "%SCHEDULE_MODE%"=="logon" set "SCHEDULE=logon"
if defined SCHEDULE goto sched_done
if defined QUIET if /i not "%SCHEDULE_MODE%"=="daily" set "SCHEDULE=%DEFAULT_SCHEDULE%"
if defined SCHEDULE goto sched_done
call :pick_schedule
if not defined SCHEDULE (
    call :log "schedule selection failed, using default %DEFAULT_SCHEDULE%"
    set "SCHEDULE=%DEFAULT_SCHEDULE%"
)
:sched_done
call :log "target=%TARGET% schedule=%SCHEDULE% quiet=%QUIET%"

rem ---- Elevation ---------------------------------------------
rem Only pass "quiet" on to the elevated window when the caller asked for it,
rem so that a double-click keeps the elevated window (and its errors) visible.
set "ELEV_ARGS=elevated"
if defined QUIET set "ELEV_ARGS=elevated quiet"
if defined SCHEDULE set "ELEV_ARGS=%ELEV_ARGS% %SCHEDULE%"

net session >nul 2>nul
if %errorlevel% neq 0 (
    call :log "not elevated : requesting UAC"
    echo [INFO] Requesting administrator privileges...
    echo [INFO] Please click [Yes] on the UAC window.
    powershell -NoProfile -Command "try { Start-Process -FilePath '%SELF%' -Verb RunAs -ArgumentList '%ELEV_ARGS% %TARGET%' -ErrorAction Stop; exit 0 } catch { Write-Host '[ERROR] Could not elevate:' $_.Exception.Message; exit 1 }"
    if errorlevel 1 (
        call :log "UAC request FAILED - cancelled or blocked"
        echo.
        echo ============================================================
        echo [ERROR] Elevation failed or was cancelled.
        echo [ERROR] The scheduled task was NOT installed - nothing changed.
        echo [ERROR] Diagnostics: %LOG%
        echo ============================================================
        call :wait
        exit /b 1
    )
    call :log "UAC accepted : elevated window launched, original window exits"
    exit /b 0
)
call :log "running elevated"

rem ---- Paths / runtimes --------------------------------------
set "PYTHON_EXE=python"

where python >nul 2>nul
if errorlevel 1 (
    call :log "ERROR python not found on PATH"
    echo [ERROR] Python not found. Please install Python and add to PATH.
    call :wait
    exit /b 1
)
for /f "delims=" %%p in ('where python') do call :log "python = %%p"

rem Check if Node.js is available (needed for the Trae check-in only)
set "NEED_NODE="
if /i "%TARGET%"=="all" set "NEED_NODE=1"
if /i "%TARGET%"=="apps" set "NEED_NODE=1"
echo %TARGET% | findstr /i /c:"trae" >nul
if not errorlevel 1 set "NEED_NODE=1"
if not defined NEED_NODE goto node_check_done
where node >nul 2>nul
if errorlevel 1 (
    call :log "ERROR node not found on PATH"
    echo [ERROR] Node.js not found. Please install Node.js and add to PATH.
    rem NOTE: keep round brackets out of any echo/rem line inside an if block -
    rem cmd miscounts them and lines after the block then run unconditionally.
    echo [ERROR] Only needed for the Trae check-in - pick WorkBuddy only to skip it.
    call :wait
    exit /b 1
)
for /f "delims=" %%p in ('where node') do call :log "node = %%p"
:node_check_done

if not exist "%SCRIPT_PATH%" (
    call :log "ERROR check-in script missing: %SCRIPT_PATH%"
    echo [ERROR] Check-in script not found: %SCRIPT_PATH%
    call :wait
    exit /b 1
)

rem ---- Build the schedule arguments -------------------------
for /f "tokens=1,2" %%a in ("%SCHEDULE%") do (
    set "SCHED_MODE=%%a"
    set "SCHED_AT=%%b"
)
if /i "%SCHED_MODE%"=="daily" (
    set "SCHED_ARGS=/SC DAILY /ST %SCHED_AT%"
    set "SCHED_DESC=every day at %SCHED_AT%"
) else (
    set "SCHED_ARGS=/SC ONLOGON /DELAY %STARTUP_DELAY%"
    set "SCHED_DESC=at user logon + %STARTUP_DELAY% delay"
)

echo ============================================================
echo Install Auto Check-in Task
echo ============================================================
echo.
echo Task Name : %TASK_NAME%
echo Trigger   : %SCHED_DESC%
echo Target    : %TARGET%
echo Command   : python "%SCRIPT_PATH%" --startup --target %TARGET%
echo Log files : %PROJECT_DIR%\logs\auto_checkin_YYYY-MM-DD.log
echo Install log: %LOG%
echo.

rem NOTE: no explicit /Delete here - schtasks /Create /F overwrites the task,
rem so a failed create can never leave the machine without a working task.
echo Creating task (%SCHED_DESC%, target %TARGET%)...
call :log "create: schtasks /Create /TN %TASK_NAME% %SCHED_ARGS% /RL HIGHEST /F /TR [%PYTHON_EXE%] [%SCRIPT_PATH%] --startup --target %TARGET%"
schtasks /Create /TN "%TASK_NAME%" ^
    /TR "\"%PYTHON_EXE%\" \"%SCRIPT_PATH%\" --startup --target %TARGET%" ^
    %SCHED_ARGS% /RL HIGHEST /F >>"%LOG%" 2>&1
call :log "create errorlevel=%errorlevel%"
if errorlevel 1 goto create_retry
goto create_done

:create_retry
if /i not "%SCHED_MODE%"=="daily" (
    rem ONLOGON /DELAY is rejected on some systems; retry without the delay.
    echo.
    echo [WARN] Could not create the task with the %STARTUP_DELAY% delay.
    echo [WARN] Retrying without the delay (the script still waits for the desktop)...
    call :log "retry create without delay"
    schtasks /Create /TN "%TASK_NAME%" ^
        /TR "\"%PYTHON_EXE%\" \"%SCRIPT_PATH%\" --startup --target %TARGET%" ^
        /SC ONLOGON /RL HIGHEST /F >>"%LOG%" 2>&1
    call :log "create (no delay) errorlevel=%errorlevel%"
    if not errorlevel 1 goto create_done
)
echo.
echo ============================================================
echo [ERROR] Task creation failed.
echo [ERROR] Full output: %LOG%
echo ============================================================
call :wait
exit /b 1
:create_done

echo.
echo [OK] Task created. Current definition:
echo ------------------------------------------------------------
schtasks /Query /TN "%TASK_NAME%" /V /FO LIST
echo ------------------------------------------------------------
call :log "query errorlevel=%errorlevel%"

echo.
echo ============================================================
echo Task installed successfully!
echo ============================================================
echo.
echo Notes:
echo   - Selected target: %TARGET%
echo   - Schedule: %SCHED_DESC%
echo   - Logon mode fires AT LOGON only - reboot or sign out/in to arm it.
echo   - Daily mode runs at the given time while the PC is on and the user is logged in.
echo   - The script also waits for the Windows desktop shell to be ready.
echo   - Failed runs, crashes and every sub-process exit code are written to:
echo       %PROJECT_DIR%\logs\auto_checkin_YYYY-MM-DD.log
echo   - Install diagnostics are written to:
echo       %LOG%
echo   - Change STARTUP_DELAY at the top of this file to adjust the delay.
echo.
echo Useful commands:
echo   View task  : schtasks /Query /TN "%TASK_NAME%" /V
echo   Run now    : schtasks /Run /TN "%TASK_NAME%"
echo   Remove task: uninstall_startup_task.bat
echo   Change target/time : install_startup_task.bat [trae|workbuddy|web|apps|all] [logon|daily|21:30]
echo.
call :wait
exit /b 0

rem ============================================================
:pick_schedule
rem Ask scripts/select_schedule.ps1 for the schedule (interactive or from args).
rem Writes "logon" or "daily HH:MM" into SCHEDULE.
set "SELECT_SCHED=%PROJECT_DIR%\scripts\select_schedule.ps1"
if not exist "%SELECT_SCHED%" (
    call :log "schedule selector missing, using default %DEFAULT_SCHEDULE%"
    goto :eof
)
set "SCHED_FILE=%TEMP%\checkin_sched_%RANDOM%%RANDOM%.txt"
if exist "%SCHED_FILE%" del "%SCHED_FILE%" >nul 2>nul
set "PS_MODE=auto"
if /i "%SCHEDULE_MODE%"=="daily" set "PS_MODE=daily"
if defined SCHEDULE_TIME (
    powershell -NoProfile -ExecutionPolicy Bypass -File "%SELECT_SCHED%" -Mode %PS_MODE% -Time "%SCHEDULE_TIME%" -OutFile "%SCHED_FILE%"
) else (
    powershell -NoProfile -ExecutionPolicy Bypass -File "%SELECT_SCHED%" -Mode %PS_MODE% -OutFile "%SCHED_FILE%"
)
if exist "%SCHED_FILE%" (
    set /p SCHEDULE=<"%SCHED_FILE%"
    del "%SCHED_FILE%" >nul 2>nul
)
goto :eof

:add_schedule
rem Recognize a schedule token: "logon", "daily", or a time (contains ":").
set "TOK=%~1"
if /i "%TOK%"=="logon" set "SCHEDULE_MODE=logon"
if /i "%TOK%"=="daily" set "SCHEDULE_MODE=daily"
if not "%TOK::=%"=="%TOK%" set "SCHEDULE_MODE=daily"
if not "%TOK::=%"=="%TOK%" set "SCHEDULE_TIME=%TOK%"
goto :eof

:add_target
rem Append a canonical target to TARGET unless it is already present.
if not defined TARGET (
    set "TARGET=%~1"
    goto :eof
)
echo %TARGET% | findstr /i /c:"%~1" >nul
if errorlevel 1 set "TARGET=%TARGET%,%~1"
goto :eof

:log
rem Append one timestamped line to the install log.
rem The message is re-quoted on purpose: the caller's quotes are stripped by the
rem first argument, so a redirection character in the message would otherwise
rem overwrite a file instead of being logged.
rem Keep log messages free of double quotes as well.
>>"%LOG%" echo [%date% %time%] "%~1"
goto :eof

:wait
rem Wait for a key press unless running in quiet mode
if not defined QUIET pause >nul
goto :eof
