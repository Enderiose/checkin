# checkin

[English](README.md) · [简体中文](README_CN.md)

---

<a id="English"></a>

## English

Automatically complete the daily check-in for **Trae SOLO CN**, **WorkBuddy** and
**arbitrary web sites**.

> Formerly named `TWWB_checkin`. The project is now simply `checkin`; everything in this
> repository has been renamed accordingly. If you still have the old remote configured, point
> it at the renamed repository with
> `git remote set-url origin <new-repo-url>`.

### Features

- **Three kinds of check-in**: Trae SOLO CN, WorkBuddy, and a generic web check-in
- **Web check-in with graceful degradation**: a silent background HTTP request first, and a
  headless Chrome/Edge fallback when the silent attempt cannot confirm success
- **No browser driver required**: the web fallback drives the installed browser over the
  Chrome DevTools Protocol (CDP); Selenium is only a fallback if `websocket-client` is missing
- **Auto start on logon**: runs ~2 minutes after Windows user logon (never during logon, so the
  desktop is ready)
- **Detailed logging**: timestamp and status for each operation, written to a daily log file
- **Crash logging**: unhandled exceptions are logged with a full traceback and exit code 3

### Prerequisites

- Windows OS
- Python 3.11+ (3.11+ is required for the standard-library TOML parser used by `.config`)
- Node.js 18+ (Trae check-in only)
- Trae SOLO CN and/or WorkBuddy installed (only if you check them in)
- Chrome or Edge installed (for the web check-in browser fallback)
- `pip install websocket-client` is recommended for the driver-free web browser engine
  (Selenium is used automatically when it is absent)

### Quick Start

#### 1. Create the web check-in configuration

The site list is a TOML file named `.config` (git-ignored). Copy the committed template first:

```cmd
cp .config.example .config
```

On Windows `cmd.exe` (no `cp`) use:

```cmd
copy .config.example .config
```

Then edit `.config` and add one block per site — each site only needs a `name` and a `url`:

```toml
[[sites]]
name = "example"
url = "https://example.com/checkin"
```

For a "public welfare" site where simply being logged in and opening the page is the
daily check-in (no clickable check-in button), add `login_only = true`:

```toml
[[sites]]
name = "Any Router"
url = "https://anyrouter.top/console/topup"
login_only = true
```

With `login_only = true`, a successfully opened page counts as success, so a missing
check-in button never becomes a failure or a hang.

`url` is the **page** that shows the check-in button after you log in (for example
`https://wb.404-found.uk/hb/me`). By default the tool opens that page and clicks the
button, because some APIs carry a live token/signature that only the page can produce.

If the check-in is in fact a plain JSON API (often hidden behind a tab, or triggered by
the site's own JavaScript), declare it instead of relying on a button:

```toml
[[sites]]
name = "404"
url = "https://wb.404-found.uk/hb/me"
checkin_api = "/hb/api/v1/checkin"   # POST endpoint (relative to url, or absolute)
csrf_api    = "/hb/api/v1/me"        # optional: returns {"csrf": "..."} -> X-CSRF header

[[sites]]
name = "Any Router"
url = "https://anyrouter.top/console/topup"
login_only   = true
checkin_api  = "/api/user/sign_in"
browser_only = true                   # behind a WAF only a real browser can pass
```

`checkin_api` is called silently with the saved cookies first; when that fails it is
called again **from inside the browser**, so a WAF JS challenge or a login kept in
`localStorage` is already satisfied. `browser_only = true` skips the silent tier
entirely (use it when the host is known to reject plain HTTP clients).

#### How to find the check-in page

1. Log in to the site in your normal browser and open the page where the 签到 / check-in
   button is visible; copy that page's address bar value into `url`.
2. Do **not** copy the request you see in F12 -> Network: those endpoints need a live
   token, and a plain GET will not work.

Log in once per site so the tool can reuse your session:

```cmd
python scripts\web_checkin.py --login example
```

A browser window opens; log in there, come back to the console and press Enter. The cookies
are stored in `cookies\example.json` (git-ignored) and reused on later runs.

> You can skip this whole step if you only want the Trae / WorkBuddy check-ins.

#### 2. Validate Paths

```cmd
python scripts\test_paths.py
```

#### 3. Install Auto Check-in Task

```cmd
install_startup_task.bat
```

The installer shows an interactive **multi-select list**:

```
============================================================
Select what the scheduled task should check in
============================================================
  UP/DOWN = move    SPACE = toggle    ENTER = confirm

  > [x] Trae SOLO CN
    [x] WorkBuddy
    [x] Web sites (.config)
```

Use **Up/Down** to move, **Space** to select/deselect, and **Enter** to confirm. At least one
entry must be selected. (The old `[3] Both` entry is gone — selecting two entries does the
same thing.)

The selection can also be passed on the command line (unattended):

```cmd
install_startup_task.bat trae,web quiet
```

Accepted values: `trae`, `workbuddy`, `web`, `apps` (= trae + workbuddy), `all` (= everything),
`1`/`2`/`3` (= trae / workbuddy / web), or any comma-separated combination.

It then asks **when** the task should run:

```
============================================================
When should the check-in run?
============================================================
  [1] After logon (current behaviour, with a short delay)
  [2] Every day at a specific time
Choice [1/2] (default 1):
```

Choosing `[2]` asks for the time. Both 24-hour (`20:15`, `2130`) and 12-hour
(`9:30AM`, `8:30 PM`) input is accepted and normalised to 24-hour. On the command line a
time token also selects daily mode, e.g. `install_startup_task.bat all 21:30 quiet` or
`install_startup_task.bat all logon quiet`.

#### 4. Test Check-in

```cmd
python scripts\auto_checkin.py
```

### Web Check-in

Every site in `.config` is handled with two tiers:

1. **Silent** — `GET` the `url` with the saved cookies (`requests`). If the page says
   "already checked in" or "success", the run is done with no window at all. When the
   site declares `checkin_api`, that JSON endpoint is called instead of scraping the page.
2. **Headless browser** — if tier 1 cannot confirm (HTTP 401/403, a redirect to a login page,
   or unclear text), the `url` is opened in headless Chrome/Edge, the check-in button is
   clicked (or, for a `checkin_api` site, the API is called from inside the page), the
   result is read, and a screenshot is written to `screenshots\` (git-ignored).

> Token-based sites (most of them) simply fall through tier 1 and are handled by tier 2,
> which is the expected behaviour - you only need the page link, not the API.

Sites marked `login_only = true` use a fallback: when no check-in button exists, a page
that opened successfully in the browser is reported as **success** instead of "no
check-in button found". The silent tier no longer trusts a bare HTTP 200 for such sites:
a login form, a WAF challenge page and a real dashboard all answer 200, so only the
browser can tell them apart.

Useful commands:

```cmd
python scripts\web_checkin.py                  # check in every site
python scripts\web_checkin.py --site example   # one site
python scripts\web_checkin.py --login example  # log in once, save cookies
python scripts\web_checkin.py --list           # list configured sites
python scripts\web_checkin.py --dry-run        # validate .config, do not check in
python scripts\web_checkin.py --headful        # show the browser (debugging)
python scripts\web_checkin.py --headless       # force a headless browser
python scripts\web_checkin.py --force-browser  # skip the silent attempt
python scripts\web_checkin.py --silent-only    # never open a browser
```

### Project Structure

```
checkin/
├── config.py                  # Configuration (paths, timeouts, web options)
├── .config                    # Web site list (TOML, git-ignored, created from .config.example)
├── .config.example            # Committed template for .config
├── cookies/                   # Saved cookies + browser profiles (git-ignored)
├── screenshots/               # Web check-in screenshots (git-ignored)
├── logs/                      # Daily log files (git-ignored)
│   ├── auto_checkin_YYYY-MM-DD.log
│   └── web_checkin_YYYY-MM-DD.log
├── scripts/
│   ├── auto_checkin.py        # Main orchestrator (logging + crash handling)
│   ├── web_checkin.py         # Web check-in (silent HTTP -> headless browser)
│   ├── browser_engine.py      # CDP / Selenium browser engine
│   ├── select_targets.ps1     # Interactive target picker used by the installer
│   ├── test_paths.py          # Path validation
│   ├── diagnose_workbuddy.py  # Screenshot-only WorkBuddy diagnostics (never clicks)
│   └── full_test.py           # System test
├── patches/                   # Local patch snapshot for the vendored submodule
├── trae-daily-checkin/        # Trae library (3rd-party, see THIRD_PARTY_NOTICES.md)
├── workbuddy-checkin/         # WorkBuddy library (3rd-party, see THIRD_PARTY_NOTICES.md)
├── install_startup_task.bat   # Install task (logon + 2 min delay)
├── uninstall_startup_task.bat # Uninstall task
├── test_checkin.bat           # Test check-in
└── info.bat                   # Show info
```

### Logs and Exit Codes

Every run appends to `logs\auto_checkin_YYYY-MM-DD.log` and the web step writes
`logs\web_checkin_YYYY-MM-DD.log` (UTF-8, 30 days kept). Each entry records the environment
(session id, screen resolution, uptime after boot, resolved paths), every sub-process command
with its stdout/stderr and exit code, and any unhandled exception with a full traceback.

| Exit code | Meaning |
| --- | --- |
| `0` | All check-ins done, or at least one of them |
| `1` | All check-ins failed / application or script not found |
| `2` | Web check-in configuration problem (missing or invalid `.config`) |
| `3` | Unexpected crash - see the `[CRASH]` block in the log |

The last exit code of the scheduled run is also visible in Task Scheduler
(`schtasks /Query /TN AutoCheckinOnStartup /V /FO LIST`, field *Last Result*).

### Configuration

Edit `config.py` for application paths, timeouts and the web browser options:

```python
TRAE_EXE = r"Your Trae path"
WORKBUDDY_EXE = r"Your WorkBuddy path"
TRAE_TIMEOUT = 120
WORKBUDDY_TIMEOUT = 60

WEB_CONFIG_PATH = os.path.join(PROJECT_DIR, ".config")
WEB_TIMEOUT = 30           # per-request timeout
WEB_VERIFY_TIMEOUT = 15    # seconds to wait for the result after a click
WEB_CHECKIN_TIMEOUT = 300  # whole web step
WEB_HEADLESS = True        # False = show the browser for debugging
WEB_BROWSER = "auto"       # "chrome" to force Chrome, "edge" to force Edge
```

Edit `.config` for the list of web sites.

### Commands

| Command | Description |
|---------|-------------|
| `python scripts\test_paths.py` | Test paths |
| `python scripts\auto_checkin.py` | Manual check-in (all selected targets) |
| `python scripts\auto_checkin.py --target trae,web` | Manual check-in for a subset |
| `python scripts\web_checkin.py --login example` | Log in to a web site once and save cookies |
| `python scripts\full_test.py` | System test |
| `install_startup_task.bat` | Install task (interactive multi-select + schedule) |
| `install_startup_task.bat trae,web` | Install task without prompting |
| `install_startup_task.bat all 21:30` | Install a task that runs every day at 21:30 |
| `uninstall_startup_task.bat` | Uninstall task |

### Troubleshooting

1. **Path error**: edit `config.py` - and read the log, it names the exact missing path
2. **Check-in failed**: ensure apps are logged in
3. **Task not running**: check Python/Node.js in PATH
4. **Any unexplained failure**: open `logs\auto_checkin_YYYY-MM-DD.log`; it contains the full
   environment dump, every sub-process exit code and any crash traceback
5. **WorkBuddy clicks do nothing**: its click coordinates are hard-coded for 1920x1080, the
   script logs a warning when the screen differs
6. **WorkBuddy "no change" / check-in not visible**: run `python scripts\diagnose_workbuddy.py`,
   look at the generated screenshots and correct `WORKBUDDY_CHECKIN_X/Y` in `config.py`
7. **`.config` missing or empty**: `cp .config.example .config`, then add a `[[sites]]` block;
   the web step exits `2` and says so
8. **Web check-in always falls back to the browser**: no cookies yet - run
   `python scripts\web_checkin.py --login <name>`; the silent tier needs a saved session
9. **Web browser does not start**: install Chrome or Edge, and run
   `pip install websocket-client` for the driver-free CDP engine (without it, Selenium and a
   matching driver are required)
10. **The web fallback picked Edge instead of Chrome**: set `WEB_BROWSER = "chrome"` in
    `config.py`. Chrome is always tried first; Edge is only used when Chrome cannot start
    (e.g. its profile is locked by a leftover browser)
10. **The installer seems to do nothing**: open `logs\install_task.log` - it records the
    elevation state, the resolved Python/Node paths, and the exact `schtasks` command with its
    output and exit code. A cancelled UAC prompt now reports an explicit error instead of
    closing the window silently. A logon task only fires AT LOGON, so nothing happens until
    the next logon or reboot; a daily task fires at its time while the PC is on.
11. **A file named `nul` appeared and cannot be deleted**: it is created when a redirection
    like `2>nul` is run from a POSIX shell (git-bash/WSL) instead of `cmd.exe` - the shell does
    not know the NUL device and creates a real file. Windows then resolves the name to the
    device, so `del`/`rm`/`Remove-Item` do nothing. Run `python scripts\clean_strays.py`
    (it is also called automatically on every check-in run) to remove it.

### Technical Details

- **Trae**: Chrome DevTools Protocol (CDP) + Node.js
- **WorkBuddy**: Win32 API (ctypes) + Python
- **Web**: `requests` (silent tier) then CDP over the installed Chrome/Edge (headless tier),
  with Selenium as a fallback engine

### Notes

- The default schedule is **2 minutes after user logon** (adjustable: `STARTUP_DELAY` at the
  top of `install_startup_task.bat`). You can also install it as a **daily task at a fixed
  time** (24h or 12h AM/PM) - the installer asks for it, or pass `logon` / `21:30` on the
  command line
- The scheduled command starts in `C:\Windows\System32`; all paths are resolved from the
  project directory, never from the current directory
- WorkBuddy click coordinates live in `config.py` (`WORKBUDDY_MENU_X/Y`, `WORKBUDDY_CHECKIN_X/Y`)
  and are injected into the vendored script as environment variables
- `WORKBUDDY_SKIP_MENU = True` makes WorkBuddy check in straight from the home page,
  skipping the "click the avatar, wait for the menu" steps
- The WorkBuddy step is self-verifying (`WORKBUDDY_VERIFY = True`): it waits for the check-in
  button to render, makes sure the window is really in the foreground, clicks, then compares
  before/after screenshots and retries (up to `WORKBUDDY_MAX_TRIES`) when nothing changed
- `python scripts\diagnose_workbuddy.py` takes screenshots of the real WorkBuddy window with a
  crosshair drawn at the configured coordinates - it never clicks
- The web browser fallback clicks the first visible button/link whose text looks like a
  check-in control ("签到", "打卡", "领取", "check in", ...), skipping anything that already
  says "已签到" / "already"
- To re-measure a coordinate, hover the mouse over the target and run:
  `python -c "import ctypes,ctypes.wintypes as w,time; u=ctypes.windll.user32; time.sleep(5); p=w.POINT(); u.GetCursorPos(ctypes.byref(p)); print(p.x, p.y)"`
  (use `python`, not PowerShell - PowerShell is DPI-unaware and reports scaled coordinates)
- First use requires manual login
- Trae debug port only listens on 127.0.0.1

### Third-Party Code and Attribution

This repository vendors two upstream projects. All credit for the Trae and WorkBuddy check-in
implementations belongs to their authors; only the wrapper/scheduling layer (`config.py`,
`scripts/`, `*.bat`) is original to this project. `trae-daily-checkin/` carries three small
documented local fixes (waiting for the CDP page target, polling for the account UI, and making
`--close` actually control whether Trae is closed); `workbuddy-checkin/` carries two small
documented local patches (click coordinates and a flow switch, both driven by environment
variables so they stay configurable from `config.py`).

| Directory | Upstream repository | Author | License |
| --- | --- | --- | --- |
| `trae-daily-checkin/` | [BlueChonk/trae-daily-checkin](https://github.com/BlueChonk/trae-daily-checkin) | Cecilia | MIT |
| `workbuddy-checkin/` | [GitOfUser/workbuddy-checkin](https://github.com/GitOfUser/workbuddy-checkin) | GitOfUser | Upstream provides no license file (all rights reserved by the author) |

See [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) for version/commit details and trademark notes.

### License

The original parts of this project — the wrapper and scheduling layer (`config.py`, `scripts/`, `*.bat`) — are released under the [MIT License](LICENSE).

The vendored third-party code keeps the copyright and license of its respective authors (see the table above); the MIT License does not apply to it. In particular, `workbuddy-checkin/` ships without any upstream license file, so all rights to that code remain with its author.

---

## License / 许可证

The original part of this project (the wrapper and scheduling layer) is released under the MIT
License. The vendored third-party code remains under its authors' licenses - see
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
