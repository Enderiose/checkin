#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Web check-in - silent background first, headless browser as fallback.

The site list lives in `.config` (TOML, no third-party parser needed):

    [[sites]]
    name = "example"
    url  = "https://example.com/checkin"

    # Optional: a "public welfare" site where simply being logged in / opening
    # the page counts as the daily check-in (no clickable button exists).
    # When true, a successfully opened page is treated as success instead of
    # "no check-in button found".
    [[sites]]
    name = "login-only-site"
    url  = "https://example.org/console/topup"
    login_only = true

Usage:
    python scripts/web_checkin.py                  # check in every configured site
    python scripts/web_checkin.py --site example   # check in one site
    python scripts/web_checkin.py --login example  # headed browser: log in once, save cookies
    python scripts/web_checkin.py --list           # list configured sites
    python scripts/web_checkin.py --dry-run        # validate .config only, do not check in

How one site is processed:
    1. silent   - GET the url with the saved cookies (requests). If the page says
                  "already checked in" or "success", we are done. No window at all.
    2. headless - if step 1 cannot confirm (401/403, login redirect, unknown text),
                  open the url in headless Chrome/Edge, click the check-in button and
                  read the result. A screenshot is written to screenshots/ either way.

Login-only sites (login_only = true in .config):
    Some "public welfare" sites have no check-in button - being logged in and
    opening the page is the daily check-in. For those, a successfully opened page
    (silent 2xx/3xx or a loaded browser page) counts as success, so a missing
    check-in button never turns into a failure or a hang.

Logs: logs/web_checkin_YYYY-MM-DD.log

Exit codes:
    0 = every attempted site done, or at least one done
    1 = every attempted site failed
    2 = configuration problem (missing/invalid .config)
    3 = unexpected crash (full traceback written to the log)
"""

import argparse
import atexit
import json
import os
import re
import sys
import tempfile
import time
import traceback
from datetime import datetime
from urllib.parse import urljoin

# ============================================================
# Paths / configuration
# ============================================================

SCRIPT_PATH = os.path.abspath(__file__)
PROJECT_DIR = os.path.dirname(os.path.dirname(SCRIPT_PATH))

CONFIG_ERROR = None
try:
    if PROJECT_DIR not in sys.path:
        sys.path.insert(0, PROJECT_DIR)
    from config import (  # noqa: E402
        WEB_CONFIG_PATH, WEB_TIMEOUT, WEB_HEADLESS, WEB_BROWSER,
        WEB_COOKIE_DIR, WEB_SCREENSHOT_DIR, LOG_DIR, LOG_KEEP_DAYS, LOG_CONSOLE,
    )
    try:
        from config import WEB_VERIFY_TIMEOUT
    except ImportError:
        WEB_VERIFY_TIMEOUT = 15
except Exception as _exc:                                      # noqa: BLE001
    CONFIG_ERROR = "%s: %s" % (type(_exc).__name__, _exc)
    WEB_CONFIG_PATH = os.path.join(PROJECT_DIR, ".config")
    WEB_TIMEOUT = 30
    WEB_HEADLESS = True
    WEB_BROWSER = "auto"
    WEB_VERIFY_TIMEOUT = 15
    WEB_COOKIE_DIR = os.path.join(PROJECT_DIR, "cookies")
    WEB_SCREENSHOT_DIR = os.path.join(PROJECT_DIR, "screenshots")
    LOG_DIR = os.path.join(PROJECT_DIR, "logs")
    LOG_KEEP_DAYS = 30
    LOG_CONSOLE = True

LOG_FILE_PREFIX = "web_checkin_"

# Browser engine (CDP first, Selenium fallback) lives in a sibling module.
sys.path.insert(0, os.path.dirname(SCRIPT_PATH))
from browser_engine import BrowserError, open_browser  # noqa: E402

# ============================================================
# Result classification keywords
# ============================================================
# Order matters: "already" is checked before "success", because an already
# checked-in page often still contains the word "签到".
ALREADY_KEYWORDS = [
    "已签到", "已经签到", "今日已签", "今天已签", "重复签到", "已打卡",
    "already checked", "already signed", "already check", "already done",
]
SUCCESS_KEYWORDS = [
    "签到成功", "签到完成", "打卡成功", "领取成功", "已领取", "签到获得",
    "check-in success", "checkin success", "checked in successfully",
    "check in successfully", "success",
]
FAILURE_KEYWORDS = [
    "签到失败", "打卡失败", "领取失败", "check-in failed", "checkin failed",
    "请先登录", "请登录", "未登录", "登录后", "not logged in", "login required",
    "sign in first", "failed",
]
LOGIN_URL_MARKERS = ["login", "signin", "sign-in", "passport", "sso", "auth", "account"]

# Text fragments that identify a clickable check-in button
CHECKIN_BUTTON_TEXTS = [
    "立即签到", "签到", "打卡", "领取", "立即领取", "领取奖励",
    "check in", "check-in", "checkin", "daily check",
]
# A button containing one of these is an "already done" marker, never a target
ALREADY_BUTTON_MARKERS = ["已签到", "已签", "已打卡", "已领取", "already"]


# ============================================================
# Logging (file + console), crash-safe
# ============================================================

_log_path = None
_log_stream = None
CONSOLE = bool(LOG_CONSOLE)


def _open_log_file():
    global _log_path, _log_stream
    today = datetime.now().strftime("%Y-%m-%d")
    for directory in (LOG_DIR, os.path.join(tempfile.gettempdir(), "checkin_logs")):
        try:
            os.makedirs(directory, exist_ok=True)
            path = os.path.join(directory, "%s%s.log" % (LOG_FILE_PREFIX, today))
            _log_stream = open(path, "a", encoding="utf-8", errors="replace")
            _log_path = path
            return
        except Exception:                                      # noqa: BLE001
            continue
    _log_stream = None
    _log_path = None


def _emit(line):
    if CONSOLE:
        try:
            print(line, flush=True)
        except Exception:                                      # noqa: BLE001
            pass
    if _log_stream is not None:
        try:
            _log_stream.write(line + "\n")
            _log_stream.flush()
        except Exception:                                      # noqa: BLE001
            pass


def log(message, level="INFO"):
    _emit("[%s] [%s] %s" % (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), level, message))


def log_block(text, indent="      | "):
    for line in str(text).replace("\r\n", "\n").replace("\r", "\n").rstrip("\n").split("\n"):
        _emit(indent + line)


def log_separator(char="=", level="INFO"):
    log(char * 70, level)


def _log_crash(exc_type, exc_value, exc_tb, origin="unhandled exception"):
    log_separator("!", "CRASH")
    log("SCRIPT ABORTED - %s" % origin, "CRASH")
    log("Reason  : %s: %s" % (getattr(exc_type, "__name__", exc_type), exc_value), "CRASH")
    log("Time    : %s" % datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "CRASH")
    log("Python  : %s (%s)" % (sys.version.split()[0], sys.executable), "CRASH")
    log("Command : %s" % " ".join(sys.argv), "CRASH")
    log("CWD     : %s" % os.getcwd(), "CRASH")
    log("Traceback:", "CRASH")
    log_block("".join(traceback.format_exception(exc_type, exc_value, exc_tb)))
    log_separator("!", "CRASH")


def _shutdown_log():
    global _log_stream
    if _log_stream is not None:
        try:
            _log_stream.flush()
            _log_stream.close()
        except Exception:                                      # noqa: BLE001
            pass
        _log_stream = None


def _install_crash_handlers():
    def excepthook(exc_type, exc_value, exc_tb):
        if issubclass(exc_type, KeyboardInterrupt):
            log("Interrupted by user (Ctrl+C)", "WARN")
        else:
            _log_crash(exc_type, exc_value, exc_tb)
        _shutdown_log()
        os._exit(3)

    sys.excepthook = excepthook

    try:
        import faulthandler
        if _log_stream is not None:
            faulthandler.enable(file=_log_stream, all_threads=True)
        else:
            faulthandler.enable()
    except Exception:                                          # noqa: BLE001
        pass

    atexit.register(_shutdown_log)


def _prune_old_logs(keep_days):
    if not keep_days or keep_days <= 0:
        return
    try:
        cutoff = time.time() - keep_days * 86400
        directory = os.path.dirname(_log_path) if _log_path else LOG_DIR
        for name in os.listdir(directory):
            if not (name.startswith(LOG_FILE_PREFIX) and name.endswith(".log")):
                continue
            full = os.path.join(directory, name)
            if full == _log_path:
                continue
            if os.path.isfile(full) and os.path.getmtime(full) < cutoff:
                os.remove(full)
                log("Removed expired log file: %s" % name)
    except Exception as exc:                                   # noqa: BLE001
        log("Log pruning skipped: %s" % exc, "WARN")


# ============================================================
# .config (TOML) loading
# ============================================================

class ConfigError(Exception):
    """Raised for a missing or invalid .config."""


def _toml_load(path):
    """Read a TOML file with the Python 3.11+ stdlib (tomllib)."""
    try:
        import tomllib
    except ImportError:                                        # Python < 3.11
        raise ConfigError(
            "reading .config requires Python 3.11+ (tomllib); this is %s"
            % sys.version.split()[0])
    with open(path, "rb") as fh:
        return tomllib.load(fh)


def load_sites(path=None):
    """Load and validate the site list from .config."""
    path = path or WEB_CONFIG_PATH
    if not os.path.exists(path):
        raise ConfigError(
            "config file not found: %s\n"
            "  create it first:  cp .config.example .config   (Windows: copy .config.example .config)"
            % path)

    try:
        data = _toml_load(path)
    except ConfigError:
        raise
    except Exception as exc:                                   # noqa: BLE001
        raise ConfigError("could not parse %s as TOML: %s: %s" % (path, type(exc).__name__, exc))

    raw = data.get("sites")
    if not raw:
        raise ConfigError("%s contains no [[sites]] entries (see .config.example)" % path)

    sites = []
    for index, item in enumerate(raw, start=1):
        if not isinstance(item, dict):
            raise ConfigError("site #%d is not a table" % index)
        name = str(item.get("name", "")).strip()
        url = str(item.get("url", "")).strip()
        if not name:
            raise ConfigError("site #%d has no name" % index)
        if not url:
            raise ConfigError("site '%s' has no url" % name)
        if not re.match(r"^https?://", url, re.I):
            raise ConfigError("site '%s' url must start with http:// or https:// (got %r)" % (name, url))
        sites.append({
            "name": name,
            "url": url,
            "enabled": bool(item.get("enabled", True)),
            # Login-only site: opening the page (while logged in) IS the check-in,
            # so a successfully opened page must not be reported as a failure just
            # because no check-in button was found.
            "login_only": bool(item.get("login_only", False)),
            # Optional JSON endpoint that performs the check-in (relative to url
            # or absolute). Called silently with the saved cookies and, when that
            # fails, from inside the browser (so WAF/JS challenges are already done).
            "checkin_api": str(item.get("checkin_api", "")).strip(),
            # Optional JSON endpoint whose response carries a "csrf" token that
            # must be sent as the X-CSRF header with the check-in request.
            "csrf_api": str(item.get("csrf_api", "")).strip(),
            # Optional: never try the silent HTTP tier for this site (it is known
            # to be behind a WAF that only a real browser can pass).
            "browser_only": bool(item.get("browser_only", False)),
        })
    return sites


def safe_name(name):
    """Turn a site name into a filesystem-safe token."""
    token = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff._-]+", "_", name).strip("._")
    return token or "site"


# ============================================================
# Cookie persistence (shared by requests and Selenium)
# ============================================================

def cookie_path(name):
    return os.path.join(WEB_COOKIE_DIR, "%s.json" % safe_name(name))


def load_cookies(name):
    path = cookie_path(name)
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, list) else []
    except Exception as exc:                                   # noqa: BLE001
        log("Could not read cookie file %s: %s" % (path, exc), "WARN")
        return []


def save_cookies(name, cookies):
    """Persist a list of cookie dicts (name/value/domain/path/secure/expiry)."""
    if not cookies:
        log("No cookies to save for '%s'" % name, "WARN")
        return False
    keep = ("name", "value", "domain", "path", "secure", "expiry", "httpOnly", "sameSite")
    cleaned = []
    for cookie in cookies:
        entry = {k: cookie[k] for k in keep if k in cookie and cookie[k] is not None}
        if entry.get("name"):
            cleaned.append(entry)
    if not cleaned:
        log("No usable cookies to save for '%s'" % name, "WARN")
        return False
    os.makedirs(WEB_COOKIE_DIR, exist_ok=True)
    path = cookie_path(name)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(cleaned, fh, ensure_ascii=False, indent=2)
    log("Saved %d cookie(s) to %s" % (len(cleaned), path))
    return True


def cookies_to_requests(session, cookies):
    from requests.cookies import create_cookie
    count = 0
    for cookie in cookies:
        try:
            session.cookies.set_cookie(create_cookie(
                name=cookie["name"],
                value=cookie.get("value", ""),
                domain=cookie.get("domain"),
                path=cookie.get("path", "/"),
                secure=bool(cookie.get("secure", False)),
                expires=cookie.get("expiry"),
            ))
            count += 1
        except Exception:                                      # noqa: BLE001
            continue
    return count


def cookies_from_requests(session):
    out = []
    for cookie in session.cookies:
        entry = {
            "name": cookie.name,
            "value": cookie.value,
            "domain": cookie.domain,
            "path": cookie.path or "/",
            "secure": bool(cookie.secure),
        }
        if cookie.expires:
            entry["expiry"] = cookie.expires
        out.append(entry)
    return out


# ============================================================
# Result classification
# ============================================================

def classify_text(text):
    """Return 'already' | 'success' | 'failure' | 'unknown' for a page body."""
    low = (text or "").lower()
    if any(k.lower() in low for k in ALREADY_KEYWORDS):
        return "already"
    if any(k.lower() in low for k in SUCCESS_KEYWORDS):
        return "success"
    if any(k.lower() in low for k in FAILURE_KEYWORDS):
        return "failure"
    return "unknown"


def classify_json(data):
    """Classify a JSON check-in API response.

    Returns (verdict, text) with verdict in success/already/failure/unknown.
    Handles both shapes seen in the wild:
      * {"ok": true, "replay": false, "points": 201}          (404 API)
      * {"success": true, "message": "签到成功，获得 ..."}    (new-api sites)
    """
    if not isinstance(data, dict):
        return "unknown", ""
    text = " ".join(str(data.get(k) or "") for k in
                    ("message", "msg", "detail", "error", "reason")).strip()
    # An explicit replay/already flag wins over everything else.
    if data.get("replay") is True or data.get("already") is True or data.get("checked") is True:
        return "already", text
    verdict = classify_text(text) if text else "unknown"
    if verdict in ("already", "success", "failure"):
        return verdict, text
    for key in ("ok", "success"):
        if data.get(key) is True:
            return "success", text
        if data.get(key) is False:
            return "failure", text
    return "unknown", text


def looks_like_login_url(url):
    low = (url or "").lower()
    return any(marker in low for marker in LOGIN_URL_MARKERS)


def response_body(response):
    """Decode a response as UTF-8 when possible.

    Many Chinese sites omit the charset in Content-Type, which makes requests
    fall back to ISO-8859-1 and turn the page into mojibake, so keyword matching
    would silently fail.
    """
    try:
        return response.content.decode("utf-8")
    except (UnicodeDecodeError, AttributeError):
        return response.text


def looks_like_html(body, content_type):
    """True when the response is a full web page rather than a check-in result.

    A page's HTML contains template strings and framework data (e.g. an SPA
    bundle with the literal text "已签到"), so keyword matching on it produces
    false "already checked in" results. Those pages must be rendered by the
    browser, which only sees the visible text.
    """
    content_type = (content_type or "").lower()
    if "json" in content_type:
        return False
    head = (body or "")[:2000].lower()
    return ("<!doctype" in head) or ("<html" in head) or ("<head" in head)


# ============================================================
# Tier 1 - silent background request
# ============================================================

def try_silent(site, timeout):
    """GET the check-in url with the saved cookies.

    When the site declares a JSON `checkin_api`, that endpoint is called instead
    of scraping the page. Returns (status, detail) with status in
    success/already/fallback.
    """
    try:
        import requests
    except ImportError:
        return "fallback", "requests is not installed, using the browser"

    cookies = load_cookies(site["name"])
    session = requests.Session()
    session.headers.update({
        "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                       "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    })
    if cookies:
        loaded = cookies_to_requests(session, cookies)
        log("Silent attempt: loaded %d cookie(s) from %s" % (loaded, cookie_path(site["name"])))
    else:
        log("Silent attempt: no saved cookies - run --login %s to create them" % site["name"], "WARN")

    if site.get("checkin_api"):
        return _silent_api(site, session, timeout)

    try:
        response = session.get(site["url"], timeout=timeout, allow_redirects=True)
    except Exception as exc:                                   # noqa: BLE001
        return "fallback", "request failed: %s: %s" % (type(exc).__name__, exc)

    log("Silent attempt: HTTP %s -> %s" % (response.status_code, response.url))

    if response.status_code in (401, 403):
        return "fallback", "HTTP %s (needs a real browser session)" % response.status_code
    if looks_like_login_url(response.url) and response.url != site["url"]:
        return "fallback", "redirected to a login page: %s" % response.url

    body = response_body(response)
    content_type = response.headers.get("Content-Type", "")
    if looks_like_html(body, content_type):
        # A plain 200 HTML page proves nothing: it may be a login form, a WAF
        # challenge page or an SPA that only checks in once its JavaScript has
        # run. Only a real browser can tell those apart, so always fall through.
        if site.get("login_only", False):
            return "fallback", "login-only site: an HTML page needs a real browser to confirm"
        return "fallback", "the url returns a full web page, not a check-in result"

    verdict = classify_text(body)
    if verdict in ("success", "already"):
        return verdict, "matched keywords in the response"
    if verdict == "failure":
        return "fallback", "response looks like a failure page"
    return "fallback", "response is inconclusive"


def _silent_api(site, session, timeout):
    """Call the site's JSON check-in API with the saved cookies.

    Optionally fetches a CSRF token first (site['csrf_api']) and sends it as the
    X-CSRF header. Returns (status, detail) just like try_silent.
    """
    api_url = urljoin(site["url"], site["checkin_api"])
    headers = {"Content-Type": "application/json"}

    if site.get("csrf_api"):
        csrf_url = urljoin(site["url"], site["csrf_api"])
        try:
            csrf_response = session.get(csrf_url, timeout=timeout)
        except Exception as exc:                               # noqa: BLE001
            return "fallback", "csrf request failed: %s: %s" % (type(exc).__name__, exc)
        log("Silent API: GET %s -> HTTP %s" % (csrf_url, csrf_response.status_code))
        if csrf_response.status_code >= 400:
            return "fallback", "csrf endpoint returned HTTP %s" % csrf_response.status_code
        try:
            token = (csrf_response.json() or {}).get("csrf")
        except Exception:                                      # noqa: BLE001
            token = None
        if not token:
            return "fallback", "no csrf token in the response"
        headers["X-CSRF"] = token

    try:
        response = session.post(api_url, json={}, headers=headers, timeout=timeout)
    except Exception as exc:                                   # noqa: BLE001
        return "fallback", "check-in request failed: %s: %s" % (type(exc).__name__, exc)

    log("Silent API: POST %s -> HTTP %s" % (api_url, response.status_code))
    try:
        data = response.json()
    except Exception:                                          # noqa: BLE001
        body = response_body(response)
        verdict = classify_text(body)
        if verdict in ("success", "already"):
            return verdict, "matched keywords in the API response"
        return "fallback", "the check-in API returned a non-JSON body"

    verdict, text = classify_json(data)
    if verdict in ("success", "already"):
        return verdict, "API said: %s" % (text or verdict)
    if verdict == "failure":
        return "fallback", "the check-in API rejected the request (%s)" % (text or "no message")
    return "fallback", "the check-in API returned an inconclusive result"


# ============================================================
# Tier 2 - headless browser (CDP first, Selenium fallback)
# ============================================================

def profile_dir(site):
    return os.path.join(WEB_COOKIE_DIR, "browser", safe_name(site["name"]))


def profile_has_state(site):
    """True when the per-site browser profile already contains a session.

    A successful --login keeps the session in the profile (cookies and
    localStorage), so the absence of a cookies/<name>.json file does not mean
    the site has to be logged in again.
    """
    path = profile_dir(site)
    try:
        with os.scandir(path) as entries:
            return any(entries)
    except Exception:                                          # noqa: BLE001
        return False


def screenshot(browser, site, tag):
    try:
        os.makedirs(WEB_SCREENSHOT_DIR, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = os.path.join(WEB_SCREENSHOT_DIR, "%s_%s_%s.png" % (safe_name(site["name"]), tag, stamp))
        browser.screenshot(path)
        log("Screenshot: %s" % path)
        return path
    except Exception as exc:                                   # noqa: BLE001
        log("Screenshot failed: %s" % exc, "WARN")
        return None


def try_browser(site, headless=True, keep_open=False):
    """Open the check-in url in a browser, click the button, read the result."""
    cookies = load_cookies(site["name"])
    try:
        browser = open_browser(profile_dir(site), headless=headless, timeout=WEB_TIMEOUT,
                               prefer=WEB_BROWSER)
    except BrowserError as exc:
        raise RuntimeError(str(exc))

    log("Browser engine: %s" % getattr(browser, "label", type(browser).__name__))
    try:
        log("Opening %s" % site["url"])
        browser.goto(site["url"])
        time.sleep(2)

        if cookies:
            added = browser.set_cookies(cookies)
            log("Injected %d cookie(s) into the browser" % added)
            if added:
                browser.goto(site["url"])
                time.sleep(2)
        else:
            if profile_has_state(site):
                log("No cookie file, but the saved browser profile already holds "
                    "the session - using it as is")
            else:
                log("No saved cookies - if the page asks for a login run: "
                    "python scripts\\web_checkin.py --login %s" % site["name"], "WARN")

        if site.get("checkin_api"):
            return _browser_api_signin(browser, site)

        # Prefer acting on a real check-in button; only read the page text when
        # there is no clickable button. A page that merely mentions "已签到"
        # somewhere must not stop a genuine check-in.
        label = browser.click_by_text(CHECKIN_BUTTON_TEXTS, ALREADY_BUTTON_MARKERS)
        if not label:
            verdict = classify_text(browser.text())
            if verdict == "already":
                log("Page already reports a completed check-in", "SUCCESS")
                screenshot(browser, site, "already")
                return "already", "already checked in"
            if verdict == "success":
                log("Page reports success without any click", "SUCCESS")
                screenshot(browser, site, "success")
                return "success", "success on page load"
            if site.get("login_only", False):
                # Fallback for "login counts as check-in" sites: the page opened
                # successfully, so count it as done instead of failing because no
                # check-in button exists.
                if verdict == "failure":
                    log("Login-only site: page opened, but it may not be logged in "
                        "(no check-in button)", "WARN")
                else:
                    log("Login-only site: no check-in button, page opened successfully",
                        "SUCCESS")
                screenshot(browser, site, "opened")
                return "success", "page opened (login-only site)"
            screenshot(browser, site, "no_button")
            if verdict == "failure":
                return "fallback", "no check-in button and the page looks like a failure/login page"
            return "fallback", "no check-in button found on the page"

        log("Clicked check-in button: %r" % label)

        deadline = time.time() + WEB_VERIFY_TIMEOUT
        final = "unknown"
        while time.time() < deadline:
            time.sleep(1)
            final = classify_text(browser.text())
            if final in ("success", "already", "failure"):
                break

        screenshot(browser, site, final if final != "unknown" else "after_click")

        if final in ("success", "already"):
            log("Browser check-in reported: %s" % final, "SUCCESS")
            return final, "browser click verified"
        if final == "failure":
            return "fallback", "the page still reports a failure after the click"
        return "fallback", "clicked, but the result is inconclusive"

    finally:
        if keep_open:
            log("Browser kept open (--keep-open); close it manually")
        else:
            browser.close()


def _browser_api_signin(browser, site):
    """Run the site's JSON check-in API from inside the loaded page.

    Doing the fetch in the page's own context is what makes WAF-protected sites
    (and sites that keep their session in localStorage) work: by now the browser
    has passed the JS challenge and holds every cookie the API expects.
    """
    api_url = urljoin(site["url"], site["checkin_api"])
    csrf_url = urljoin(site["url"], site["csrf_api"]) if site.get("csrf_api") else ""
    script = """(async () => {
  const api = %s, csrfUrl = %s;
  const headers = {"Content-Type": "application/json"};
  if (csrfUrl) {
    try {
      const c = await fetch(csrfUrl, {credentials: "same-origin"});
      const j = await c.json();
      if (j && j.csrf) headers["X-CSRF"] = j.csrf;
    } catch (e) {}
  }
  try {
    const r = await fetch(api, {method: "POST", credentials: "same-origin",
                                headers: headers, body: "{}"});
    const t = await r.text();
    return JSON.stringify({status: r.status, body: t.slice(0, 2000)});
  } catch (e) {
    return JSON.stringify({status: 0, body: String(e)});
  }
})()""" % (json.dumps(api_url), json.dumps(csrf_url))

    log("Calling the check-in API from inside the browser: POST %s" % api_url)
    try:
        raw = browser.evaluate(script)
    except Exception as exc:                                   # noqa: BLE001
        return "fallback", "in-browser API call failed: %s: %s" % (type(exc).__name__, exc)

    try:
        result = json.loads(raw) if isinstance(raw, str) else raw
        status_code = int(result.get("status") or 0)
        body = result.get("body") or ""
    except Exception:                                          # noqa: BLE001
        return "fallback", "unexpected in-browser result: %r" % (raw,)

    log("In-browser check-in: HTTP %s" % status_code)
    if status_code in (401, 403):
        log("Response body: %s" % (body[:200] or "<empty>"))
        return "fallback", ("HTTP %s - the browser session is not logged in "
                            "(run: python scripts\\web_checkin.py --login %s)"
                            % (status_code, site["name"]))
    try:
        data = json.loads(body)
    except Exception:                                          # noqa: BLE001
        verdict = classify_text(body)
        if verdict in ("success", "already"):
            return verdict, "matched keywords in the in-browser response"
        return "fallback", "the check-in API returned a non-JSON body in the browser"

    verdict, text = classify_json(data)
    if verdict in ("success", "already"):
        return verdict, "in-browser API said: %s" % (text or verdict)
    if verdict == "failure":
        return "fallback", ("the check-in API rejected the request (%s) - run "
                            "--login %s if the browser session is not logged in"
                            % (text or "no message", site["name"]))
    return "fallback", "the in-browser check-in API returned an inconclusive result"


# ============================================================
# Login helper (headed browser, saves cookies)
# ============================================================

def login_site(site, keep_open=False):
    log_separator("-")
    log("Login mode for '%s'" % site["name"])
    log("A browser window will open. Log in there, then come back here and press Enter.")
    try:
        browser = open_browser(profile_dir(site), headless=False, timeout=WEB_TIMEOUT,
                               prefer=WEB_BROWSER)
    except BrowserError as exc:
        log("Could not start a browser: %s" % exc, "ERROR")
        return False
    log("Browser engine: %s" % getattr(browser, "label", type(browser).__name__))
    try:
        browser.goto(site["url"])
        log("Log in inside the browser window, then press Enter HERE to save the cookies.")
        log("Keep the browser window OPEN until the cookies have been saved.", "WARN")
        try:
            input(">>> Press Enter once you are logged in (keep the window open)... ")
        except EOFError:
            log("No console input available; waiting %ss instead" % 120, "WARN")
            time.sleep(120)
        try:
            cookies = browser.get_cookies()
        except BrowserError as exc:
            log("Could not read the cookies: %s" % exc, "ERROR")
            log("The browser must stay open until the cookies are saved - run --login again "
                "and only close the window afterwards.", "ERROR")
            return False
        save_cookies(site["name"], cookies)
        log("Login cookies stored. Future runs can check in silently.", "SUCCESS")
        return True
    except BrowserError as exc:
        log("Login failed: %s" % exc, "ERROR")
        return False
    finally:
        if keep_open:
            log("Browser kept open (--keep-open)")
        else:
            browser.close()


# ============================================================
# Orchestration
# ============================================================

def process_site(site, args):
    """Run both tiers for one site. Returns (ok, status_text)."""
    log_separator("-")
    log("Site: %s -> %s" % (site["name"], site["url"]))

    login_only = site.get("login_only", False)
    if site.get("checkin_api"):
        log("Mode: JSON check-in API %s" % site["checkin_api"])
    elif login_only:
        log("Mode: login-only site - a successfully opened page counts as checked in")

    if site.get("browser_only") or args.force_browser:
        reason = "--force-browser" if args.force_browser else "browser_only site"
        log("Silent attempt skipped (%s)" % reason)
    else:
        status, detail = try_silent(site, args.timeout)
        log("Silent result: %s (%s)" % (status, detail))
        if status in ("success", "already"):
            return True, status
        if login_only and status == "opened":
            return True, "opened"
        if args.silent_only:
            return False, "silent attempt failed (%s)" % detail
        log("Falling back to the headless browser", "WARN")

    try:
        status, detail = try_browser(site, headless=args.headless_mode, keep_open=args.keep_open)
    except Exception as exc:                                   # noqa: BLE001
        log("Browser fallback failed: %s: %s" % (type(exc).__name__, exc), "ERROR")
        return False, "browser fallback failed"
    log("Browser result: %s (%s)" % (status, detail))
    return status in ("success", "already", "opened"), status


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="Web check-in: silent HTTP first, headless browser as fallback")
    parser.add_argument("--site", action="append", default=None,
                        help="only handle this site (repeatable); default = all sites")
    parser.add_argument("--login", metavar="NAME",
                        help="open a visible browser to log in and save cookies for NAME")
    parser.add_argument("--list", action="store_true", help="list the configured sites and exit")
    parser.add_argument("--dry-run", action="store_true",
                        help="validate .config and print the plan, then exit")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--headful", action="store_true",
                      help="show the browser during the fallback (debugging)")
    mode.add_argument("--headless", action="store_true",
                      help="force a headless browser (overrides WEB_HEADLESS in config.py)")
    parser.add_argument("--keep-open", action="store_true",
                        help="do not close the browser window (debugging)")
    parser.add_argument("--force-browser", action="store_true",
                        help="skip the silent HTTP attempt")
    parser.add_argument("--silent-only", action="store_true",
                        help="never fall back to the browser")
    parser.add_argument("--timeout", type=int, default=None,
                        help="per-request timeout in seconds (default from config.py)")
    return parser.parse_args(argv)


def main(argv=None):
    started = time.time()
    args = parse_args(argv)
    if args.timeout is None:
        args.timeout = WEB_TIMEOUT
    # --headful / --headless win; otherwise config.py's WEB_HEADLESS decides.
    args.headless_mode = (not args.headful) if (args.headful or args.headless) else bool(WEB_HEADLESS)

    _open_log_file()
    _install_crash_handlers()
    _prune_old_logs(LOG_KEEP_DAYS)

    log_separator()
    log("Web Check-in Started")
    log_separator()
    log("Config file : %s" % WEB_CONFIG_PATH)
    if CONFIG_ERROR:
        log("config.py import error: %s" % CONFIG_ERROR, "WARN")
    log("Python      : %s (%s)" % (sys.version.split()[0], sys.executable))
    log("Log file    : %s" % (_log_path or "<unavailable>"))

    try:
        sites = load_sites()
    except ConfigError as exc:
        log_separator("!", "ERROR")
        log("CONFIGURATION PROBLEM", "ERROR")
        log_block(str(exc), indent="      ")
        log_separator("!", "ERROR")
        return 2

    log("Configured sites: %d" % len(sites))

    if args.list:
        for site in sites:
            log("  - %s -> %s%s" % (site["name"], site["url"], "" if site["enabled"] else "  (disabled)"))
        return 0

    if args.login:
        match = next((s for s in sites if s["name"] == args.login), None)
        if match is None:
            log("No site named '%s' in %s" % (args.login, WEB_CONFIG_PATH), "ERROR")
            return 2
        ok = login_site(match, keep_open=args.keep_open)
        return 0 if ok else 1

    selected = sites
    if args.site:
        wanted = set(args.site)
        selected = [s for s in sites if s["name"] in wanted]
        missing = wanted - {s["name"] for s in selected}
        if missing:
            log("Unknown site(s): %s" % ", ".join(sorted(missing)), "ERROR")
            return 2
    selected = [s for s in selected if s.get("enabled", True)]
    if not selected:
        log("No enabled site to process", "ERROR")
        return 2

    if args.dry_run:
        for site in selected:
            log("  would check in: %s -> %s" % (site["name"], site["url"]))
        log("Dry run finished, nothing was checked in", "SUCCESS")
        return 0

    results = []
    for site in selected:
        try:
            ok, status = process_site(site, args)
        except Exception as exc:                               # noqa: BLE001
            _log_crash(type(exc), exc, exc.__traceback__, "crash while handling '%s'" % site["name"])
            ok, status = False, "crash"
        results.append((site["name"], ok, status))

    log_separator()
    log("Web Check-in Results:")
    for name, ok, status in results:
        log("  %-24s %s" % (name, "OK (%s)" % status if ok else "FAILED (%s)" % status))
    log_separator()

    success_count = sum(1 for _, ok, _ in results if ok)
    if success_count == len(results):
        log("All web check-ins completed!", "SUCCESS")
        code = 0
    elif success_count > 0:
        log("Partial web check-ins completed (%d/%d)" % (success_count, len(results)), "WARN")
        code = 0
    else:
        log("All web check-ins failed", "ERROR")
        code = 1

    log("Finished with exit code %s after %.1fs" % (code, time.time() - started))
    return code


if __name__ == "__main__":
    sys.exit(main())
