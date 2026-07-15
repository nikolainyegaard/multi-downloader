"""Manual smoke test for the admin panel auth. Not wired to any test runner.

Run: ADMIN_PASSWORD=test123 DATA_DIR=/tmp/mdl-data python tests/smoke_admin.py
"""

import os
import subprocess
import sys
import time
import urllib.parse
import urllib.request

BASE = "http://127.0.0.1:8000"


class Client:
    """Tiny cookie-jar HTTP client that does not follow redirects."""

    def __init__(self):
        self.cookies = {}

    def request(self, method, path, data=None, ctype=None):
        req = urllib.request.Request(BASE + path, data=data, method=method)
        if ctype:
            req.add_header("Content-Type", ctype)
        if self.cookies:
            req.add_header("Cookie", "; ".join(f"{k}={v}" for k, v in self.cookies.items()))
        opener = urllib.request.build_opener(NoRedirect)
        try:
            resp = opener.open(req)
        except urllib.error.HTTPError as e:
            resp = e
        for header in resp.headers.get_all("Set-Cookie") or []:
            k, v = header.split(";")[0].split("=", 1)
            self.cookies[k] = v
        return resp.status, resp.headers.get("Location", ""), resp.read().decode(errors="replace")


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def main():
    srv = subprocess.Popen([sys.executable, "-m", "uvicorn", "app.main:app", "--port", "8000"])
    try:
        for _ in range(50):
            time.sleep(0.2)
            try:
                urllib.request.urlopen(BASE + "/", timeout=1)
                break
            except Exception:
                continue

        c = Client()

        status, loc, _ = c.request("GET", "/admin/")
        print("PANEL-NOAUTH:", status, loc, "OK" if status in (302, 307) and loc.endswith("/admin/login") else "FAIL")

        status, _, body = c.request("GET", "/admin/login")
        print("LOGIN-PAGE:", status,
              "password-form" if 'action="login"' in body else "NO-FORM",
              "oidc-hidden" if 'href="oidc/login" hidden' in body else "oidc-visible")

        form = urllib.parse.urlencode({"username": "admin", "password": "wrong"}).encode()
        status, _, body = c.request("POST", "/admin/login", form, "application/x-www-form-urlencoded")
        print("BAD-LOGIN:", status, "rejected" if status == 401 and "Invalid credentials" in body else "FAIL")

        form = urllib.parse.urlencode({"username": "admin", "password": "test123"}).encode()
        status, loc, _ = c.request("POST", "/admin/login", form, "application/x-www-form-urlencoded")
        print("GOOD-LOGIN:", status, loc, "OK" if status == 303 else "FAIL")

        status, _, body = c.request("GET", "/admin/")
        print("PANEL-AUTHED:", status, "OK" if status == 200 and "sidebar" in body else "FAIL")

        status, _, body = c.request("GET", "/admin/api/config")
        print("API-AUTHED:", status, "OK" if status == 200 and "site_title" in body else "FAIL")

        status, _, _ = Client().request("GET", "/admin/api/config")
        print("API-NOAUTH:", status, "OK" if status == 401 else "FAIL")

        status, loc, _ = c.request("GET", "/admin/oidc/login")
        print("OIDC-DISABLED:", status, loc, "OK" if status in (302, 307) and loc.endswith("/admin/login") else "FAIL")

        status, loc, _ = c.request("POST", "/admin/logout")
        print("LOGOUT:", status, loc, "OK" if status == 303 else "FAIL")

        status, loc, _ = c.request("GET", "/admin/api/config")
        print("API-AFTER-LOGOUT:", status, "OK" if status == 401 else "FAIL")

        status, _, body = c.request("GET", "/")
        print("PUBLIC-SITE:", status, "OK" if status == 200 else "FAIL")
    finally:
        srv.terminate()


if __name__ == "__main__":
    main()
