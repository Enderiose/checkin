#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Cookie expiry notifications - pushed through the WeCom (企业微信) hook endpoint.

Only the Python standard library is used, so this module keeps working in the
same minimal environment as the rest of the project.

When does it notify?
    on = "expired"  (default) - the saved session cookie is expired/dead or is
                                about to expire. Failed check-ins that have
                                nothing to do with a dead session are NOT sent.
    on = "failure"            - every failed check-in run.
    on = "always"             - every run, including fully successful ones.
    enabled = false           - nothing is ever sent.

How the token is supplied (it is never written into the repository):
    1st: the CHECKIN_WEBHOOK_TOKEN environment variable
    2nd: a single-line, git-ignored file (default: <project>/.hook_token,
         created by copying .hook_token.example; blank lines and `#` comments
         are ignored, and an unedited `<...>` placeholder counts as "not set")
    The token is sent as the X-Hook-Token request header, never in the URL, so
    it cannot leak into request logs.

Endpoint contract (any JSON-POST endpoint works, not only the official WeCom
robot URL):
    POST <url>            header X-Hook-Token: <token>   (preferred)
    POST <url>?token=<token>

    Accepted bodies:
        {"text": "..."}                                    what we send
        {"msgtype": "text", "text": {"content": "..."}}    WeCom robot shape
        {"markdown": {"content": "..."}}
        a raw text body
    Optional fields: "to": "<chat>" (override target),
                     "mode": "notify" (default, no LLM) or "agent".

    Success: {"errcode": 0, "errmsg": "ok", "ok": true, ...}
    Errors : 40001/403 wrong token | 45009/429 rate limited | 40058/400 no text
             50001/503 token unset on host | 50002/500 no chat
             50003/502 send failed | 40006/413 body too large
    A GET without `text` is a connectivity probe and sends nothing.
    Typical limit: 30 requests / 60 s. We send at most ONE summary per run.

If delivery fails (bad token, host down, rate limited, token not configured) the
same message is shown as a Windows popup so nothing is lost silently - see
fallback_popup() / _maybe_popup() below.

Usage:
    python scripts/notify.py "构建完成"          # send one message
    python scripts/notify.py --selftest          # send a connectivity test
    python scripts/notify.py --dry-run "text"    # print the request, send nothing
    python scripts/notify.py --check-expiry       # report cookie expiry only

Logs: logs/notify_YYYY-MM-DD.log

Exit codes:
    0 = sent (or deliberately skipped)
    1 = could not send (bad token, endpoint down, ...)
    2 = not configured (disabled, or no token)
"""

import argparse
import datetime
import hashlib
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_PATH = os.path.join(PROJECT_DIR, ".config")
COOKIE_DIR = os.path.join(PROJECT_DIR, "cookies")
LOG_DIR = os.path.join(PROJECT_DIR, "logs")
STATE_PATH = os.path.join(LOG_DIR, ".notify_state.json")

# Windows message-box bits used by the local fallback notification.
MB_ICONWARNING = 0x00000030
MB_TOPMOST = 0x00040000
MB_SETFOREGROUND = 0x00010000
MB_SYSTEMMODAL = 0x00001000
CREATE_NO_WINDOW = 0x08000000
DEFAULT_POPUP_TIMEOUT = 60

# Values used when `.config` has no [notify] section at all.
DEFAULTS = {
    "enabled": True,
    "url": "http://192.168.2.6:8645/hook",
    "on": "expired",
    "expiry_warn_days": 3,
    "to": "",
    "timeout": 8,
    "retries": 2,
    "token_env": "CHECKIN_WEBHOOK_TOKEN",
    "token_file": os.path.join(PROJECT_DIR, ".hook_token"),
    "popup_fallback": True,
    "popup_timeout": DEFAULT_POPUP_TIMEOUT,
}

VALID_MODES = ("expired", "failure", "always")

# Short-lived anti-bot / WAF cookies (usually ~1 hour) say nothing about whether
# the login session is still alive, so they are ignored when the "session
# lifetime" of a site is estimated from its cookie file.
WAF_COOKIE_PREFIXES = (
    "acw_", "acw_sc__", "cdn_sec", "_abck", "bm_sz", "ak_bmsc",
    "cf_clearance", "__cf", "aws-waf", "incap_ses", "visid_incap",
)

# Rate limit of the endpoint is 30 requests / 60 s per process. One summary
# message per run is sent, so this is only a safety net for manual bursts.
BACKOFF_SECONDS = (2, 5)


# ============================================================
# Logging (file + console), crash-safe
# ============================================================

_log_path = None
_log_stream = None


def _log(message, level="INFO"):
    global _log_path, _log_stream
    line = "[%s] [%s] %s" % (datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"), level, message)
    if _log_stream is None and _log_path is None:
        try:
            os.makedirs(LOG_DIR, exist_ok=True)
            _log_path = os.path.join(LOG_DIR, "notify_%s.log" % datetime.date.today().isoformat())
            _log_stream = open(_log_path, "a", encoding="utf-8")
        except Exception:                                      # noqa: BLE001
            _log_path = ""
    if _log_stream is not None:
        try:
            _log_stream.write(line + "\n")
            _log_stream.flush()
        except Exception:                                      # noqa: BLE001
            pass
    try:
        print(line)
    except Exception:                                          # noqa: BLE001
        pass


def set_logger(func):
    """Let the caller (auto_checkin.py) route messages into its own daily log."""
    global _log
    if callable(func):
        _log = func


# ============================================================
# Configuration
# ============================================================

def load_config(path=None):
    """Return the effective notify settings (DEFAULTS + [notify] + env overrides)."""
    cfg = dict(DEFAULTS)
    path = path or CONFIG_PATH

    if os.path.exists(path):
        try:
            import tomllib
            with open(path, "rb") as fh:
                data = tomllib.load(fh)
            section = data.get("notify") or {}
            if isinstance(section, dict):
                for key, value in section.items():
                    cfg[str(key)] = value
        except Exception as exc:                               # noqa: BLE001
            _log("Could not read the [notify] section of %s: %s: %s"
                 % (path, type(exc).__name__, exc), "WARN")

    # Environment overrides keep secrets (and machine-specific URLs) out of files.
    for key, env_name in (
        ("enabled", "CHECKIN_NOTIFY_ENABLED"),
        ("url", "CHECKIN_NOTIFY_URL"),
        ("on", "CHECKIN_NOTIFY_ON"),
        ("to", "CHECKIN_NOTIFY_TO"),
        ("expiry_warn_days", "CHECKIN_NOTIFY_WARN_DAYS"),
        ("popup_fallback", "CHECKIN_NOTIFY_POPUP"),
    ):
        raw = os.environ.get(env_name)
        if raw is not None and raw.strip() != "":
            cfg[key] = raw.strip()

    cfg["enabled"] = _as_bool(cfg.get("enabled"), True)
    cfg["popup_fallback"] = _as_bool(cfg.get("popup_fallback"), True)
    cfg["popup_timeout"] = _as_int(cfg.get("popup_timeout"), DEFAULT_POPUP_TIMEOUT)
    cfg["on"] = str(cfg.get("on") or "expired").strip().lower()
    if cfg["on"] not in VALID_MODES:
        _log("Unknown notify mode %r, falling back to 'expired'" % cfg["on"], "WARN")
        cfg["on"] = "expired"
    cfg["expiry_warn_days"] = _as_int(cfg.get("expiry_warn_days"), 3)
    cfg["timeout"] = _as_int(cfg.get("timeout"), 8)
    cfg["retries"] = _as_int(cfg.get("retries"), 2)
    cfg["url"] = str(cfg.get("url") or DEFAULTS["url"]).strip()
    cfg["to"] = str(cfg.get("to") or "").strip()
    cfg["token_env"] = str(cfg.get("token_env") or DEFAULTS["token_env"]).strip()
    cfg["token_file"] = str(cfg.get("token_file") or DEFAULTS["token_file"]).strip()
    if not os.path.isabs(cfg["token_file"]):
        cfg["token_file"] = os.path.join(PROJECT_DIR, cfg["token_file"])
    return cfg


def _as_bool(value, default):
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    text = str(value).strip().lower()
    if text in ("1", "true", "yes", "on", "enabled"):
        return True
    if text in ("0", "false", "no", "off", "disabled"):
        return False
    return default


def _as_int(value, default):
    try:
        return int(str(value).strip())
    except Exception:                                          # noqa: BLE001
        return default


def resolve_token(cfg=None):
    """Return the hook token, or None. Env var wins over the token file.

    The token file may contain comments (`# ...`) and blank lines, so
    `.hook_token.example` can be copied to `.hook_token` as-is and only the
    placeholder line needs to be replaced.
    """
    cfg = cfg or load_config()
    raw = os.environ.get(cfg["token_env"])
    if raw and raw.strip():
        return raw.strip()
    try:
        with open(cfg["token_file"], "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if line.startswith("<") and line.endswith(">"):
                    _log("Token file %s still holds the placeholder %s - replace it "
                         "with the real token" % (cfg["token_file"], line), "WARN")
                    return None
                return line
    except FileNotFoundError:
        pass
    except Exception as exc:                                   # noqa: BLE001
        _log("Could not read the token file %s: %s: %s"
             % (cfg["token_file"], type(exc).__name__, exc), "WARN")
    return None


def site_display_names(path=None):
    """Map cookie file stems back to the site names used in `.config`.

    Cookie files are named after a filesystem-safe version of the site name
    ("Any Router" -> "Any_Router.json"), so notifications must translate back
    or they would tell you to run --login with a name that does not exist.
    """
    names = {}
    path = path or CONFIG_PATH
    try:
        import tomllib
        with open(path, "rb") as fh:
            data = tomllib.load(fh)
        import re
        for item in data.get("sites") or []:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or "").strip()
            if name:
                stem = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff._-]+", "_", name).strip("._") or "site"
                names[stem] = name
    except Exception:                                          # noqa: BLE001
        pass
    return names


# ============================================================
# Local fallback: a Windows message box when the webhook is dead
# ============================================================
# A dead webhook (expired token, host down, rate limited) must not swallow the
# alert - that is exactly the moment you need to hear about it. The popup runs in
# its own detached process, so it never blocks a check-in run and it survives the
# parent exiting (you may not be at the desk while the scheduled task runs).

def popup_supported():
    return sys.platform == "win32"


def show_popup(title, text, timeout=DEFAULT_POPUP_TIMEOUT):
    """Child-process body: a topmost box that closes itself after `timeout` seconds."""
    if not popup_supported():
        return 0
    import ctypes
    user32 = ctypes.windll.user32
    flags = MB_ICONWARNING | MB_TOPMOST | MB_SETFOREGROUND | MB_SYSTEMMODAL
    # MessageBoxTimeoutW is undocumented but present since Win2000 - it is the only
    # way to auto-close the box, which matters because nobody may be watching.
    try:
        fn = user32.MessageBoxTimeoutW
        fn.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_wchar_p,
                       ctypes.c_uint, ctypes.c_ushort, ctypes.c_uint]
        fn.restype = ctypes.c_int
        fn(None, text, title, flags, 0, max(1, int(timeout)) * 1000)
        return 0
    except Exception:                                          # noqa: BLE001
        pass
    try:
        user32.MessageBoxW(None, text, title, flags)
    except Exception:                                          # noqa: BLE001
        return 1
    return 0


def fallback_popup(title, text, timeout=DEFAULT_POPUP_TIMEOUT):
    """Spawn a detached popup process. Never blocks, never raises."""
    if not popup_supported():
        _log("Popup fallback is not available on %s" % sys.platform, "WARN")
        return False
    try:
        cmd = [sys.executable, os.path.abspath(__file__), "--popup",
               str(title or "checkin"), str(text or ""), str(int(timeout))]
        subprocess.Popen(
            cmd,
            creationflags=CREATE_NO_WINDOW,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            close_fds=True,
        )
        _log("Local popup shown as a fallback (auto-closes in %ss)" % timeout, "WARN")
        return True
    except Exception as exc:                                   # noqa: BLE001
        _log("Could not show the fallback popup: %s: %s" % (type(exc).__name__, exc), "ERROR")
        return False


def _maybe_popup(cfg, title, body, timeout=None):
    """Popup only when allowed; used from every failed delivery path."""
    if not cfg.get("popup_fallback", True):
        _log("Popup fallback disabled ([notify] popup_fallback = false); "
             "the message exists only in the log", "WARN")
        return False
    try:
        timeout = int(timeout if timeout is not None else cfg.get("popup_timeout"))
    except Exception:                                          # noqa: BLE001
        timeout = DEFAULT_POPUP_TIMEOUT
    return fallback_popup(title, body, timeout=timeout)


# ============================================================
# Sending
# ============================================================

def _post(cfg, token, payload, timeout):
    """One HTTP attempt. Returns (ok, detail, retryable)."""
    body = json.dumps(payload).encode("utf-8")
    headers = {
        "Content-Type": "application/json; charset=utf-8",
        "X-Hook-Token": token,
        "User-Agent": "checkin-notify/1.0",
    }
    request = urllib.request.Request(cfg["url"], data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read(4096).decode("utf-8", "replace")
            code = response.getcode()
        try:
            data = json.loads(raw) if raw else {}
        except Exception:                                      # noqa: BLE001
            data = {}
        errcode = data.get("errcode")
        if errcode in (0, None):
            return True, "HTTP %s, message_id=%s" % (code, data.get("message_id", "-")), False
        message = "%s (errcode=%s)" % (data.get("errmsg") or "rejected", errcode)
        return False, message, errcode == 45009
    except urllib.error.HTTPError as exc:
        raw = ""
        try:
            raw = exc.read(2048).decode("utf-8", "replace")
        except Exception:                                      # noqa: BLE001
            pass
        try:
            data = json.loads(raw) if raw else {}
        except Exception:                                      # noqa: BLE001
            data = {}
        message = "HTTP %s: %s" % (exc.code, data.get("errmsg") or raw[:200] or exc.reason)
        # 403 = bad token, never worth retrying. 429 = rate limit, back off.
        return False, message, exc.code in (429, 500, 502, 503, 504)
    except Exception as exc:                                   # noqa: BLE001
        return False, "%s: %s" % (type(exc).__name__, exc), True


def send_notification(text, dry_run=False, cfg=None, to=None, payload_shape="text"):
    """Send one message. Never raises - a broken notifier must not break check-in.

    Returns True when the endpoint accepted the message (or when a dry run was
    requested), False otherwise.
    """
    text = (text or "").strip()
    if not text:
        _log("Nothing to send (empty message)", "WARN")
        return False

    cfg = cfg or load_config()
    if not cfg["enabled"]:
        _log("Notifications are disabled in .config ([notify] enabled = false)")
        return False

    token = resolve_token(cfg)
    if not token and not dry_run:
        reason = ("webhook token 未配置：%s 环境变量为空，且 %s 不存在或为空"
                  % (cfg["token_env"], cfg["token_file"]))
        _log("No webhook token: set %s or write it into %s"
             % (cfg["token_env"], cfg["token_file"]), "ERROR")
        _maybe_popup(cfg, "checkin 通知无法发送：token 未配置",
                     "%s\n\n———— 原消息 ————\n%s" % (reason, text))
        return False

    target = (to or cfg["to"] or "").strip()
    if payload_shape == "markdown":
        payload = {"markdown": {"content": text}}
    else:
        payload = {"text": text}
    payload["mode"] = "notify"
    if target:
        payload["to"] = target

    if dry_run:
        preview = dict(payload)
        where = cfg["url"]
        _log("DRY RUN -> POST %s (token %s)"
             % (where, "present" if token else "MISSING"))
        _log("DRY RUN payload: %s" % json.dumps(preview, ensure_ascii=False))
        return True

    attempts = max(1, cfg["retries"] + 1)
    for attempt in range(1, attempts + 1):
        ok, detail, retryable = _post(cfg, token, payload, cfg["timeout"])
        if ok:
            _log("Notification sent (%s)" % detail, "SUCCESS")
            return True
        if not retryable or attempt == attempts:
            _log("Notification failed: %s" % detail, "ERROR")
            _maybe_popup(cfg, "checkin 通知发送失败：%s" % detail,
                         "%s\n\n———— 原消息 ————\n%s" % (detail, text))
            return False
        delay = BACKOFF_SECONDS[min(attempt - 1, len(BACKOFF_SECONDS) - 1)]
        _log("Notification attempt %d/%d failed (%s), retrying in %ss"
             % (attempt, attempts, detail, delay), "WARN")
        time.sleep(delay)
    return False


# ============================================================
# Cookie expiry inspection
# ============================================================

def _is_waf_cookie(name):
    low = (name or "").strip().lower()
    return any(low.startswith(prefix) for prefix in WAF_COOKIE_PREFIXES)


def cookie_expiry_report(cookie_dir=None, warn_days=3):
    """Inspect cookies/*.json and return (expired, expiring_soon) lists.

    Each entry is a dict: {"site", "expiry" (datetime), "days_left" (int)}.
    The session lifetime of a site is the *longest* cookie in its file, so the
    short-lived WAF cookies are naturally ignored. `site` is the name from
    `.config` whenever the cookie file can be mapped back to it.
    """
    cookie_dir = cookie_dir or COOKIE_DIR
    warn_days = max(0, int(warn_days))
    now = datetime.datetime.now()
    limit = now + datetime.timedelta(days=warn_days)
    expired, expiring = [], []
    display = site_display_names()

    if not os.path.isdir(cookie_dir):
        return expired, expiring

    for filename in sorted(os.listdir(cookie_dir)):
        if not filename.lower().endswith(".json"):
            continue
        site = filename[:-5]
        path = os.path.join(cookie_dir, filename)
        try:
            with open(path, "r", encoding="utf-8") as fh:
                items = json.load(fh)
        except Exception as exc:                               # noqa: BLE001
            _log("Could not read %s: %s: %s" % (path, type(exc).__name__, exc), "WARN")
            continue
        if not isinstance(items, list):
            continue

        longest = None
        for item in items:
            if not isinstance(item, dict):
                continue
            if _is_waf_cookie(item.get("name")):
                continue
            expiry = item.get("expiry")
            try:
                expiry = float(expiry)
            except Exception:                                  # noqa: BLE001
                continue                                           # session cookie: no expiry
            if expiry <= 0:
                continue
            if longest is None or expiry > longest:
                longest = expiry

        if longest is None:
            continue                                               # no dated session cookie
        expires_at = datetime.datetime.fromtimestamp(longest)
        days_left = int((expires_at - now).total_seconds() // 86400)
        entry = {"site": display.get(site, site), "expiry": expires_at, "days_left": days_left}
        if expires_at <= now:
            expired.append(entry)
        elif expires_at <= limit:
            expiring.append(entry)

    return expired, expiring


def format_expiry_report(expired, expiring, login_hint=True):
    """Render the cookie expiry findings as one Chinese notification body."""
    lines = []
    if expired:
        lines.append("[签到] ⚠ cookie 已过期（%d 个站点）" % len(expired))
        for entry in expired:
            if entry.get("expiry") is None:
                lines.append("• %s — 登录态被服务端拒绝" % entry["site"])
            else:
                lines.append("• %s — 已于 %s 过期"
                             % (entry["site"], entry["expiry"].strftime("%m-%d %H:%M")))
    if expiring:
        if lines:
            lines.append("")
        lines.append("[签到] cookie 即将到期（%d 个站点）" % len(expiring))
        for entry in expiring:
            lines.append("• %s — %s 到期（剩 %d 天）"
                         % (entry["site"], entry["expiry"].strftime("%m-%d"), entry["days_left"]))
    if not lines:
        return ""
    if login_hint:
        names = [entry["site"] for entry in expired + expiring]
        lines.append("")
        lines.append("续期：python scripts\\web_checkin.py --login %s" % names[0])
        if len(names) > 1:
            lines.append("其余：%s" % "、".join(names[1:]))
    return "\n".join(lines)


# ============================================================
# De-duplication (same day + same content is sent only once)
# ============================================================

def _fingerprint(*parts):
    digest = hashlib.sha1("\x1f".join(str(p) for p in parts).encode("utf-8")).hexdigest()
    return digest[:16]


def _read_state(path=None):
    path = path or STATE_PATH
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except FileNotFoundError:
        return {}
    except Exception:                                          # noqa: BLE001
        return {}


def _write_state(state, path=None):
    path = path or STATE_PATH
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(state, fh, ensure_ascii=False, indent=2, sort_keys=True)
        os.replace(tmp, path)
        return True
    except Exception as exc:                                   # noqa: BLE001
        _log("Could not write notification state %s: %s: %s"
             % (path, type(exc).__name__, exc), "WARN")
        return False


def already_sent(kind, fingerprint, today=None, path=None):
    today = today or datetime.date.today().isoformat()
    return _read_state(path).get(today, {}).get(kind) == fingerprint


def mark_sent(kind, fingerprint, today=None, path=None):
    today = today or datetime.date.today().isoformat()
    state = _read_state(path)
    # Keep the file tiny: only today's entry is needed for de-duplication.
    state = {today: state.get(today, {})}
    state[today][kind] = fingerprint
    return _write_state(state, path)


# ============================================================
# High-level entry point used by auto_checkin.py
# ============================================================

def notify_cookie_status(expired_sites=None, log_path=None, dry_run=False,
                         cfg=None, logger=None):
    """Single decision point: should we notify, what to say, and has it been said?

    expired_sites - site names that failed because their session is dead
                    (as reported by web_checkin.py's LOGIN_REQUIRED lines).
    Returns True when a message was actually sent.
    """
    if logger:
        set_logger(logger)
    cfg = cfg or load_config()
    if not cfg["enabled"]:
        _log("Notifications disabled, nothing to send")
        return False

    dead = sorted(set(expired_sites or []))
    reported_expired, reported_soon = cookie_expiry_report(warn_days=cfg["expiry_warn_days"])

    # A site the server actually rejected is "expired", even when its cookie file
    # still carries a future expiry (revoked session / server-side logout).
    dead_set = set(dead)
    reported_soon = [entry for entry in reported_soon if entry["site"] not in dead_set]
    already_expired = {entry["site"] for entry in reported_expired}
    for site in dead:
        if site not in already_expired:
            reported_expired.append({"site": site, "expiry": None, "days_left": None})

    if not reported_expired and not reported_soon:
        _log("Cookie status is fine, no notification needed")
        return False

    body = format_expiry_report(reported_expired, reported_soon)
    if log_path:
        body += "\n日志：%s" % log_path

    fingerprint = _fingerprint(
        [entry["site"] for entry in reported_expired],
        [entry["site"] for entry in reported_soon],
    )
    if already_sent("cookie_status", fingerprint):
        _log("The same cookie status was already notified today, skipping")
        return False

    if dry_run:
        _log("DRY RUN message:\n%s" % body)
        return True

    if send_notification(body, cfg=cfg):
        mark_sent("cookie_status", fingerprint)
        return True
    return False


# ============================================================
# CLI
# ============================================================

def main(argv=None):
    parser = argparse.ArgumentParser(description="Check-in cookie expiry notifications (WeCom hook)")
    parser.add_argument("text", nargs="?", help="message to send")
    parser.add_argument("--selftest", action="store_true", help="send a connectivity test message")
    parser.add_argument("--dry-run", action="store_true", help="print the request, send nothing")
    parser.add_argument("--check-expiry", action="store_true", help="inspect cookies/*.json and exit")
    parser.add_argument("--to", help="override the target chat")
    parser.add_argument("--popup", nargs=3, metavar=("TITLE", "TEXT", "TIMEOUT"),
                        help="internal: show a local Windows message box and exit")
    parser.add_argument("--show-config", action="store_true", help="print effective settings")
    args = parser.parse_args(argv)

    if args.popup:
        # Internal mode, executed by fallback_popup() in a detached process.
        try:
            timeout = int(args.popup[2])
        except Exception:                                      # noqa: BLE001
            timeout = DEFAULT_POPUP_TIMEOUT
        return show_popup(args.popup[0], args.popup[1], timeout)

    cfg = load_config()

    if args.show_config:
        safe = dict(cfg)
        safe["token_file"] = cfg["token_file"]
        _log("Effective notify configuration: %s" % json.dumps(safe, ensure_ascii=False))
        _log("Token available: %s" % ("yes" if resolve_token(cfg) else "no"))
        return 0

    if args.check_expiry:
        expired, expiring = cookie_expiry_report(warn_days=cfg["expiry_warn_days"])
        body = format_expiry_report(expired, expiring)
        if not body:
            _log("All saved cookie sessions look healthy (warn window: %d day(s))"
                 % cfg["expiry_warn_days"])
            return 0
        _log(body)
        return 0

    if args.selftest:
        text = args.text or "接口连通测试（checkin 通知自检）"
    elif args.text:
        text = args.text
    else:
        parser.error("give a message, or use --selftest / --check-expiry / --show-config")
        return 2

    ok = send_notification(text, dry_run=args.dry_run, cfg=cfg, to=args.to)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
