"""Manual smoke test for the admin panel auth. Not wired to any test runner.

Run: DATA_DIR=/tmp/mdl-data python tests/smoke_admin.py
"""

import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

BASE = "http://127.0.0.1:8000"


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


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


def start_server(extra_env=None):
    env = dict(os.environ)
    if extra_env:
        env.update(extra_env)
    srv = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main:app", "--port", "8000"],
        env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
    )
    # The credentials banner prints at import time, before uvicorn is ready
    password = None
    for _ in range(80):
        line = srv.stdout.readline()
        if not line:
            time.sleep(0.1)
            continue
        m = re.search(r"Password: (\S+)", line)
        if m:
            password = m.group(1)
        if "Uvicorn running" in line:
            break
    for _ in range(50):
        try:
            urllib.request.urlopen(BASE + "/", timeout=1)
            break
        except Exception:
            time.sleep(0.2)
    return srv, password


def login(c, username, password):
    form = urllib.parse.urlencode({"username": username, "password": password}).encode()
    return c.request("POST", "/admin/login", form, "application/x-www-form-urlencoded")


def save_cfg(c, **kwargs):
    body = {
        "enabled": False, "discovery_url": "", "client_id": "", "client_secret": "",
        "session_lifetime_days": 7, "external_url": "", "password_login": True,
        "admin_username": "admin", "new_password": "",
    }
    body.update(kwargs)
    return c.request("POST", "/admin/api/auth/config", json.dumps(body).encode(), "application/json")


def main():
    srv, generated = start_server()
    try:
        print("GENERATED-PW:", "captured" if generated else "MISSING")

        c = Client()
        status, _, body = login(c, "admin", "wrong")
        print("BAD-LOGIN:", status, "rejected" if status == 401 else "FAIL")

        status, loc, _ = login(c, "admin", generated)
        print("GENERATED-LOGIN:", status, "OK" if status == 303 else "FAIL")

        status, _, body = c.request("GET", "/admin/api/auth/config")
        flat = body.replace(" ", "")
        print("MUST-CHANGE-FLAG:", "OK" if '"must_change_password":true' in flat and '"password_set":true' in flat else flat[:200])

        status, _, body = save_cfg(c, new_password="short")
        print("SHORT-PASSWORD:", status, "OK" if status == 400 else body[:120])

        status, _, body = save_cfg(c, enabled=False, password_login=False)
        print("BOTH-DISABLED:", status, "OK" if status == 400 else body[:120])

        status, _, body = save_cfg(c, password_login=False, enabled=True,
                                   discovery_url="https://idp.example/.wk", client_id="cid", client_secret="sec")
        print("LOCKOUT-GUARD:", status, "OK" if status == 400 and "restart" in body else body[:120])

        status, _, body = save_cfg(c, new_password="newpassword123", admin_username="boss")
        print("CHANGE-CREDS:", status, "OK" if status == 200 else body[:120])

        status, _, body = c.request("GET", "/admin/api/auth/config")
        flat = body.replace(" ", "")
        print("FLAG-CLEARED:", "OK" if '"must_change_password":false' in flat and '"admin_username":"boss"' in flat else flat[:200])

        c2 = Client()
        status, _, _ = login(c2, "admin", generated)
        print("OLD-CREDS-REJECTED:", status, "OK" if status == 401 else "FAIL")
        status, _, _ = login(c2, "boss", "newpassword123")
        print("NEW-CREDS-LOGIN:", status, "OK" if status == 303 else "FAIL")

        status, _, _ = c2.request("GET", "/admin/api/config")
        print("API-AUTHED:", status, "OK" if status == 200 else "FAIL")
    finally:
        srv.terminate()
        srv.wait()

    # Second boot: no regeneration expected (credentials already stored)
    srv, pw2 = start_server()
    try:
        print("SECOND-BOOT-NO-REGEN:", "OK" if pw2 is None else "REGENERATED-FAIL")
        c = Client()
        status, _, _ = login(c, "boss", "newpassword123")
        print("PERSISTED-LOGIN:", status, "OK" if status == 303 else "FAIL")
    finally:
        srv.terminate()
        srv.wait()

    # AUTH_RESET boot: fresh credentials, OIDC disabled
    srv, pw3 = start_server({"AUTH_RESET": "1"})
    try:
        print("RESET-PW:", "captured" if pw3 else "MISSING")
        c = Client()
        status, _, _ = login(c, "admin", pw3)
        print("RESET-LOGIN:", status, "OK" if status == 303 else "FAIL")
        status, _, body = c.request("GET", "/admin/api/auth/config")
        flat = body.replace(" ", "")
        print("RESET-STATE:", "OK" if '"enabled":false' in flat and '"must_change_password":true' in flat else flat[:200])
    finally:
        srv.terminate()
        srv.wait()


if __name__ == "__main__":
    main()
