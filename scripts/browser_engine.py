#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Small browser abstraction used by scripts/web_checkin.py.

Two interchangeable engines, chosen automatically:

  * CdpBrowser      - drives the installed Chrome/Edge over the Chrome DevTools
                      Protocol (CDP). No driver binary, no download, no version
                      matching: it talks to the browser we already have. Used when
                      the `websocket-client` package is importable (it is a tiny,
                      optional dependency). This is the preferred engine.
  * SeleniumBrowser - falls back to Selenium when websocket-client is missing. If
                      the chromedriver found in PATH is stale, it asks Selenium
                      Manager to resolve a matching driver (--skip-driver-in-path).

Both expose the same tiny interface:

    browser.goto(url)
    browser.text()                       -> page text
    browser.click_by_text(include, exclude) -> clicked label or None
    browser.screenshot(path)
    browser.set_cookies(list) / browser.get_cookies()
    browser.close()

Cookies use one canonical shape everywhere:

    {"name","value","domain","path","secure","expiry","httpOnly","sameSite"}
"""

import base64
import json
import os
import socket
import subprocess
import tempfile
import time
import urllib.request


class BrowserError(Exception):
    """Raised when no browser engine could be started."""


# ============================================================
# Browser discovery
# ============================================================

def find_browser_binaries(prefer=None):
    """Return a list of (label, path) for every installed Chrome/Edge.

    Chrome entries always come first; `prefer` ("chrome" / "edge") can force a
    single browser family.
    """
    env = os.environ
    candidates = [
        ("Chrome", os.path.join(env.get("PROGRAMFILES", r"C:\Program Files"),
                                "Google", "Chrome", "Application", "chrome.exe")),
        ("Chrome", os.path.join(env.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)"),
                                "Google", "Chrome", "Application", "chrome.exe")),
        ("Chrome", os.path.join(env.get("LOCALAPPDATA", ""),
                                "Google", "Chrome", "Application", "chrome.exe")),
        ("Edge", os.path.join(env.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)"),
                              "Microsoft", "Edge", "Application", "msedge.exe")),
        ("Edge", os.path.join(env.get("PROGRAMFILES", r"C:\Program Files"),
                              "Microsoft", "Edge", "Application", "msedge.exe")),
    ]
    found, seen = [], set()
    for label, path in candidates:
        if path and os.path.exists(path) and path not in seen:
            seen.add(path)
            found.append((label, path))
    prefer = (prefer or "auto").lower()
    if prefer in ("chrome", "edge"):
        found = [item for item in found if item[0].lower() == prefer]
    return found


def _websocket_available():
    try:
        import websocket  # noqa: F401
        return True
    except Exception:                                          # noqa: BLE001
        return False


def _free_port():
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return port


# ============================================================
# Shared page-script snippets
# ============================================================

def _click_expression(include, exclude):
    """JS IIFE: click the first visible element whose text matches `include`."""
    return """
(function(){
  var include = %s, exclude = %s;
  var nodes = document.querySelectorAll('button,a,[role=button],[onclick],[class*=btn],[class*=button],input[type=submit]');
  for (var i = 0; i < nodes.length; i++) {
    var el = nodes[i];
    var rect = el.getBoundingClientRect();
    if (rect.width <= 0 || rect.height <= 0) continue;
    var style = window.getComputedStyle(el);
    if (style.visibility === 'hidden' || style.display === 'none') continue;
    var text = (el.innerText || el.textContent || el.value || '').trim();
    if (!text || text.length > 24) continue;
    var low = text.toLowerCase();
    var skip = false;
    for (var j = 0; j < exclude.length; j++) {
      if (low.indexOf(exclude[j]) >= 0) { skip = true; break; }
    }
    if (skip) continue;
    for (var k = 0; k < include.length; k++) {
      if (low.indexOf(include[k]) >= 0) {
        el.scrollIntoView({block: 'center'});
        try { el.click(); } catch (e) {
          el.dispatchEvent(new MouseEvent('click', {bubbles: true, cancelable: true}));
        }
        return text;
      }
    }
  }
  return null;
})()
""" % (json.dumps([t.lower() for t in include]), json.dumps([t.lower() for t in exclude]))


_TEXT_EXPRESSION = "document.body ? (document.body.innerText || document.body.textContent || '') : ''"
_READY_EXPRESSION = "document.readyState"


def _canonical_cookie(cookie):
    """Normalise a cookie dict to the canonical shape (expiry, not expires)."""
    out = {
        "name": cookie.get("name", ""),
        "value": cookie.get("value", ""),
        "domain": cookie.get("domain", ""),
        "path": cookie.get("path", "/"),
        "secure": bool(cookie.get("secure", False)),
    }
    expiry = cookie.get("expiry", cookie.get("expires"))
    if isinstance(expiry, (int, float)) and expiry > 0:
        out["expiry"] = int(expiry)
    if cookie.get("httpOnly") is not None:
        out["httpOnly"] = bool(cookie.get("httpOnly"))
    same_site = cookie.get("sameSite")
    if same_site in ("Strict", "Lax", "None"):
        out["sameSite"] = same_site
    return out


# ============================================================
# Engine 1: CDP (no driver)
# ============================================================

class CdpBrowser:
    """Drive Chrome/Edge directly over the DevTools Protocol."""

    def __init__(self, label, binary, profile_dir, headless=True, timeout=30):
        import websocket  # imported here so the module stays optional

        self.label = label
        self.timeout = timeout
        self._ws = None
        self._proc = None
        self._id = 0
        self._url = "about:blank"

        os.makedirs(profile_dir, exist_ok=True)
        port = _free_port()
        # Keep the flag list minimal: flags like --disable-blink-features or
        # --no-sandbox make Chrome show the "unsupported command-line flag"
        # warning bar ("稳定性和安全会有所降低"). CDP needs none of them.
        args = [
            binary,
            "--remote-debugging-port=%d" % port,
            "--remote-allow-origins=*",
            "--user-data-dir=%s" % profile_dir,
            "--no-first-run",
            "--no-default-browser-check",
            "--window-size=1280,900",
        ]
        if headless:
            args.append("--headless=new")
            args.append("--disable-gpu")
        args.append("about:blank")

        creationflags = 0x08000000 if os.name == "nt" else 0   # CREATE_NO_WINDOW
        self._proc = subprocess.Popen(
            args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            creationflags=creationflags)

        base = "http://127.0.0.1:%d" % port
        self._wait_for_endpoint(base, timeout)

        pages = json.load(urllib.request.urlopen(base + "/json/list", timeout=5))
        page = next((p for p in pages if p.get("type") == "page" and p.get("webSocketDebuggerUrl")), None)
        if page is None:
            raise BrowserError("%s started but exposed no page target" % label)

        self._ws = websocket.create_connection(
            page["webSocketDebuggerUrl"], timeout=timeout,
            http_no_proxy=["127.0.0.1", "localhost"], suppress_origin=True)
        self._cmd("Page.enable")
        self._cmd("Runtime.enable")
        self._cmd("Network.enable")

    # -- low level -------------------------------------------------
    def _wait_for_endpoint(self, base, timeout):
        deadline = time.time() + timeout
        last = None
        while time.time() < deadline:
            if self._proc.poll() is not None:
                raise BrowserError("%s exited immediately (exit code %s)" % (self.label, self._proc.returncode))
            try:
                urllib.request.urlopen(base + "/json/version", timeout=2).read()
                return
            except Exception as exc:                           # noqa: BLE001
                last = exc
                time.sleep(0.4)
        raise BrowserError("%s did not open its debug port in %ss (%s)" % (self.label, timeout, last))

    def _cmd(self, method, params=None):
        import websocket
        self._id += 1
        msg_id = self._id
        try:
            self._ws.send(json.dumps({"id": msg_id, "method": method, "params": params or {}}))
        except Exception as exc:                               # noqa: BLE001
            raise BrowserError("the browser window was closed before '%s' could run (%s)"
                               % (method, exc))
        deadline = time.time() + self.timeout
        while time.time() < deadline:
            try:
                raw = self._ws.recv()
            except websocket.WebSocketTimeoutException:
                continue
            except Exception as exc:                           # noqa: BLE001
                raise BrowserError("lost the connection to the browser during '%s' "
                                   "(was the window closed?): %s" % (method, exc))
            if not raw:
                continue
            message = json.loads(raw)
            if message.get("id") == msg_id:
                if "error" in message:
                    raise BrowserError("%s: %s" % (method, message["error"]))
                return message.get("result", {})
        raise BrowserError("%s timed out" % method)

    def _eval(self, expression):
        result = self._cmd("Runtime.evaluate", {
            "expression": expression, "returnByValue": True, "awaitPromise": True})
        return result.get("result", {}).get("value")

    # -- public API ------------------------------------------------
    def goto(self, url):
        self._url = url
        self._cmd("Page.navigate", {"url": url})
        deadline = time.time() + self.timeout
        while time.time() < deadline:
            try:
                if self._eval(_READY_EXPRESSION) in ("complete", "interactive"):
                    break
            except Exception:                                  # noqa: BLE001
                pass
            time.sleep(0.4)

    def text(self):
        try:
            return self._eval(_TEXT_EXPRESSION) or ""
        except Exception:                                      # noqa: BLE001
            return ""

    def click_by_text(self, include, exclude):
        try:
            return self._eval(_click_expression(include, exclude))
        except Exception:                                      # noqa: BLE001
            return None

    def screenshot(self, path):
        result = self._cmd("Page.captureScreenshot", {"format": "png"})
        with open(path, "wb") as fh:
            fh.write(base64.b64decode(result["data"]))

    def evaluate(self, expression):
        """Run a JavaScript expression inside the page and return its value.

        Promises are awaited, so callers can use an async IIFE to run fetch()
        requests in the page's own origin (the only place where the site's WAF
        cookies and localStorage state are guaranteed to be present).
        """
        return self._eval(expression)

    def set_cookies(self, cookies):
        payload = []
        for cookie in cookies:
            entry = _canonical_cookie(cookie)
            if not entry["name"]:
                continue
            item = {"name": entry["name"], "value": entry["value"],
                    "domain": entry["domain"], "path": entry["path"],
                    "secure": entry["secure"]}
            if "expiry" in entry:
                item["expires"] = entry["expiry"]
            if "httpOnly" in entry:
                item["httpOnly"] = entry["httpOnly"]
            if "sameSite" in entry:
                item["sameSite"] = entry["sameSite"]
            payload.append(item)
        if not payload:
            return 0
        self._cmd("Network.setCookies", {"cookies": payload})
        return len(payload)

    def get_cookies(self):
        result = self._cmd("Network.getCookies", {"urls": [self._url]})
        return [_canonical_cookie(c) for c in result.get("cookies", [])]

    def close(self):
        try:
            if self._ws is not None:
                self._ws.close()
        except Exception:                                      # noqa: BLE001
            pass
        self._ws = None
        if self._proc is not None and self._proc.poll() is None:
            try:
                self._proc.terminate()
                self._proc.wait(timeout=10)
            except Exception:                                  # noqa: BLE001
                try:
                    self._proc.kill()
                except Exception:                              # noqa: BLE001
                    pass
        self._proc = None


# ============================================================
# Engine 2: Selenium (fallback)
# ============================================================

class SeleniumBrowser:
    """Drive Chrome/Edge through Selenium (used when websocket-client is absent)."""

    def __init__(self, profile_dir, headless=True, timeout=30, prefer="auto"):
        from selenium import webdriver
        from selenium.webdriver.chrome.options import Options as ChromeOptions
        from selenium.webdriver.edge.options import Options as EdgeOptions

        self.timeout = timeout
        self._driver = None
        self._url = "about:blank"
        os.makedirs(profile_dir, exist_ok=True)

        attempts = [
            ("Chrome", webdriver.Chrome, ChromeOptions, "chrome"),
            ("Edge", webdriver.Edge, EdgeOptions, "edge"),
        ]
        prefer = (prefer or "auto").lower()
        if prefer in ("chrome", "edge"):
            attempts = [a for a in attempts if a[3] == prefer] or attempts

        errors = []
        for label, factory, options_cls, browser_key in attempts:
            options = options_cls()
            if headless:
                options.add_argument("--headless=new")
                options.add_argument("--disable-gpu")
            options.add_argument("--window-size=1280,900")
            options.add_argument("--user-data-dir=%s" % profile_dir)

            for attempt, service in (("path driver", None), ("resolved driver", browser_key)):
                try:
                    if service is None:
                        driver = factory(options=options)
                    else:
                        driver = factory(options=options,
                                         service=self._service(label, browser_key))
                    driver.set_page_load_timeout(timeout)
                    self._driver = driver
                    self.label = label
                    return
                except Exception as exc:                       # noqa: BLE001
                    errors.append("%s (%s): %s" % (label, attempt, str(exc).splitlines()[0][:160]))
        raise BrowserError("Selenium could not start a browser -> " + " | ".join(errors))

    @staticmethod
    def _service(label, browser_key):
        """Ask Selenium Manager for a matching driver, ignoring PATH drivers."""
        from selenium.webdriver.common.selenium_manager import SeleniumManager
        from selenium.webdriver.chrome.service import Service as ChromeService
        from selenium.webdriver.edge.service import Service as EdgeService

        paths = SeleniumManager().binary_paths(["--browser", browser_key, "--skip-driver-in-path"])
        driver_path = paths.get("driver_path")
        if not driver_path or not os.path.exists(driver_path):
            raise BrowserError("Selenium Manager returned no %s driver" % browser_key)
        return ChromeService(executable_path=driver_path) if browser_key == "chrome" \
            else EdgeService(executable_path=driver_path)

    def goto(self, url):
        self._url = url
        self._driver.get(url)

    def text(self):
        try:
            from selenium.webdriver.common.by import By
            return self._driver.find_element(By.TAG_NAME, "body").text or ""
        except Exception:                                      # noqa: BLE001
            try:
                return self._driver.page_source or ""
            except Exception:                                  # noqa: BLE001
                return ""

    def click_by_text(self, include, exclude):
        try:
            return self._driver.execute_script("return " + _click_expression(include, exclude))
        except Exception:                                      # noqa: BLE001
            return None

    def screenshot(self, path):
        self._driver.save_screenshot(path)

    def evaluate(self, expression):
        """Run a JavaScript expression inside the page and return its value.

        Promises are awaited through Selenium's async script callback, so an
        async IIFE (e.g. one that awaits fetch()) works the same way it does on
        the CDP engine.
        """
        wrapper = ("(function(){var cb=arguments[arguments.length-1];"
                   "Promise.resolve(%s).then(function(v){cb(v===undefined?null:v)})"
                   ".catch(function(e){cb(null)});})()" % expression)
        return self._driver.execute_async_script(wrapper)

    def set_cookies(self, cookies):
        count = 0
        for cookie in cookies:
            entry = _canonical_cookie(cookie)
            if not entry["name"]:
                continue
            payload = {"name": entry["name"], "value": entry["value"],
                       "domain": entry["domain"], "path": entry["path"],
                       "secure": entry["secure"]}
            if "expiry" in entry:
                payload["expiry"] = entry["expiry"]
            try:
                self._driver.add_cookie(payload)
                count += 1
            except Exception:                                  # noqa: BLE001
                continue
        return count

    def get_cookies(self):
        try:
            return [_canonical_cookie(c) for c in self._driver.get_cookies()]
        except Exception:                                      # noqa: BLE001
            return []

    def close(self):
        try:
            if self._driver is not None:
                self._driver.quit()
        except Exception:                                      # noqa: BLE001
            pass
        self._driver = None


# ============================================================
# Factory
# ============================================================

def open_browser(profile_dir, headless=True, timeout=30, prefer="auto"):
    """Start the best available engine: CDP first, Selenium as fallback.

    Chrome is always tried before Edge. For each Chrome install (then Edge) the
    per-site profile is tried first, so a login kept in the browser profile
    (localStorage, etc.) survives; a fresh temporary profile is only used when
    the per-site profile is locked by a leftover browser. `prefer` ("chrome" /
    "edge") restricts the browser family.
    """
    prefer = (prefer or "auto").lower()
    binaries = find_browser_binaries(prefer)
    if not binaries:
        binaries = find_browser_binaries()

    temp_profile = os.path.join(tempfile.gettempdir(),
                                "checkin_browser_%d_%d" % (os.getpid(), int(time.time())))
    errors = []

    if _websocket_available():
        for label, binary in binaries:
            for directory, tag in ((profile_dir, "site profile"), (temp_profile, "temp profile")):
                try:
                    return CdpBrowser(label, binary, directory, headless=headless, timeout=timeout)
                except Exception as exc:                       # noqa: BLE001
                    errors.append("CDP/%s (%s): %s" % (label, tag, exc))
    else:
        errors.append("CDP skipped: websocket-client is not installed")

    try:
        return SeleniumBrowser(profile_dir, headless=headless, timeout=timeout, prefer=prefer)
    except Exception as exc:                                   # noqa: BLE001
        errors.append("Selenium: %s" % exc)

    raise BrowserError("no browser engine available -> " + " | ".join(errors))
