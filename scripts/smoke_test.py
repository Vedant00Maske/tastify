"""Smoke test of a running SONIQUEO deployment (spec §14 step 9; DEPLOYMENT.md "Smoke test").

Exercises the critical journeys through the real edge proxy: pages and their security headers,
health, the API's isolation of /metrics, registration, e-mail verification and password reset
through the real worker and mail server, playlists, recommendations, data export, error
reporting and account deletion. The test account is deleted at the end.

    python scripts/smoke_test.py --base http://127.0.0.1:8080 --mailpit http://127.0.0.1:8025
    python scripts/smoke_test.py --base https://soniqueo.example.com      # without mail checks

Exit status 0 when every check passes. (Checks are assertions; do not run with python -O.)
"""

import argparse
import re
import sys
import time
import uuid
from collections.abc import Callable

import httpx

PASSWORD = "smoke test password 1"
NEW_PASSWORD = "smoke test password 2"


class Smoke:
    def __init__(self, base: str, mailpit: str | None) -> None:
        self.base = base.rstrip("/")
        origin = self.base
        self.client = httpx.Client(
            base_url=self.base,
            timeout=30.0,
            headers={"Origin": origin},
            follow_redirects=False,
        )
        self.mailpit = (
            httpx.Client(base_url=mailpit.rstrip("/"), timeout=10.0)
            if mailpit
            else None
        )
        self.failures: list[str] = []
        self.email = f"smoke-{uuid.uuid4().hex[:10]}@example.com"

    def check(self, name: str, test: Callable[[], None]) -> None:
        started = time.perf_counter()
        try:
            test()
        except Exception as error:  # report every failure, keep going  # noqa: BLE001
            self.failures.append(f"{name}: {error}")
            print(f"FAIL {name}: {error}")
            return
        print(f"ok   {name} ({(time.perf_counter() - started) * 1000:.0f} ms)")

    # --- checks ------------------------------------------------------------------------------

    def pages(self) -> None:
        root = self.client.get("/")
        assert root.status_code in (302, 303, 307, 308), root.status_code
        assert root.headers["location"].endswith("/login"), root.headers["location"]
        login = self.client.get("/login")
        assert login.status_code == 200, login.status_code
        csp = login.headers.get("content-security-policy", "")
        assert "frame-ancestors 'none'" in csp, csp
        assert "default-src 'self'" in csp, csp
        assert login.headers.get("x-frame-options") == "DENY"
        assert "x-powered-by" not in login.headers
        assert (
            "server" not in login.headers
            or "caddy" not in login.headers["server"].lower()
        )

    def health(self) -> None:
        ready = self.client.get("/api/v1/health/ready")
        assert ready.status_code == 200, ready.text
        assert ready.json()["checks"] == {"database": "ok", "redis": "ok"}
        assert len(ready.headers.get("x-request-id", "")) >= 8
        assert ready.headers.get("x-content-type-options") == "nosniff"

    def internals_hidden(self) -> None:
        # /metrics is not routed to the API: the web app answers (redirect or 404), never data.
        scrape = self.client.get("/metrics")
        assert "soniqueo_http_requests_total" not in scrape.text, scrape.status_code
        assert scrape.status_code != 200 or "text/html" in scrape.headers.get(
            "content-type", ""
        )

    def register(self) -> None:
        response = self.client.post(
            "/api/v1/auth/register",
            json={"email": self.email, "password": PASSWORD, "accept_terms": True},
        )
        assert response.status_code == 201, response.text
        me = self.client.get("/api/v1/users/me")
        assert me.status_code == 200, me.text
        assert me.json()["email"] == self.email

    def _mail_token(self, subject_part: str, path: str) -> str:
        assert self.mailpit is not None
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            listing = self.mailpit.get(
                "/api/v1/search", params={"query": f"to:{self.email}"}
            )
            listing.raise_for_status()
            for message in listing.json().get("messages", []):
                if subject_part in message["Subject"]:
                    body = self.mailpit.get(f"/api/v1/message/{message['ID']}").json()[
                        "Text"
                    ]
                    match = re.search(
                        rf"{re.escape(path)}\?token=([A-Za-z0-9_-]+)", body
                    )
                    assert match, body
                    self.mailpit.delete(
                        "/api/v1/messages", params={"IDs": message["ID"]}
                    )
                    return match.group(1)
            time.sleep(1)
        raise AssertionError(
            f"no '{subject_part}' e-mail within 60 s (worker or SMTP down?)"
        )

    def verify_email(self) -> None:
        token = self._mail_token("Confirm your e-mail", "/verify-email")
        verified = self.client.post("/api/v1/auth/email/verify", json={"token": token})
        assert verified.status_code == 204, verified.text
        assert self.client.get("/api/v1/users/me").json()["email_verified"] is True

    def reset_password(self) -> None:
        forgot = self.client.post(
            "/api/v1/auth/password/forgot", json={"email": self.email}
        )
        assert forgot.status_code == 202, forgot.text
        token = self._mail_token("Reset your SONIQUEO password", "/reset-password")
        reset = self.client.post(
            "/api/v1/auth/password/reset",
            json={"token": token, "new_password": NEW_PASSWORD},
        )
        assert reset.status_code == 204, reset.text
        assert (
            self.client.get("/api/v1/users/me").status_code == 401
        )  # signed out everywhere
        login = self.client.post(
            "/api/v1/auth/login", json={"email": self.email, "password": NEW_PASSWORD}
        )
        assert login.status_code == 200, login.text
        self.password = NEW_PASSWORD

    def playlists(self) -> None:
        created = self.client.post("/api/v1/playlists", json={"name": "Smoke test"})
        assert created.status_code == 201, created.text
        pid = created.json()["id"]
        renamed = self.client.patch(
            f"/api/v1/playlists/{pid}", json={"name": "Smoke test 2"}
        )
        assert renamed.status_code == 200, renamed.text
        assert self.client.delete(f"/api/v1/playlists/{pid}").status_code == 204

    def recommendations(self) -> None:
        moods = self.client.get("/api/v1/recommendations/moods")
        assert moods.status_code == 200, moods.text
        # An empty deployment has no models yet (503); a seeded one answers with a mix.
        mix = self.client.get("/api/v1/recommendations/for-you")
        assert mix.status_code in (200, 503), mix.text
        if mix.status_code == 200:
            assert mix.headers.get("x-cache") in ("hit", "miss")

    def export_and_errors(self) -> None:
        export = self.client.get("/api/v1/users/me/export")
        assert export.status_code == 200, export.text
        assert export.json()["account"]["email"] == self.email
        report = self.client.post(
            "/api/v1/client-errors",
            json={"kind": "render", "message": "smoke test report", "path": "/home"},
        )
        assert report.status_code == 202, report.text

    def csrf(self) -> None:
        response = self.client.post(
            "/api/v1/playlists",
            json={"name": "x"},
            headers={"Origin": "https://evil.example"},
        )
        assert response.status_code == 403, response.status_code

    def delete_account(self) -> None:
        password = getattr(self, "password", PASSWORD)
        deleted = self.client.request(
            "DELETE", "/api/v1/users/me", json={"password": password}
        )
        assert deleted.status_code == 204, deleted.text
        assert self.client.get("/api/v1/users/me").status_code == 401

    def run(self) -> int:
        self.check("pages and security headers", self.pages)
        self.check("health", self.health)
        self.check("internals not exposed", self.internals_hidden)
        self.check("register", self.register)
        if self.mailpit:
            self.check("e-mail verification (worker + SMTP)", self.verify_email)
            self.check("password reset", self.reset_password)
        self.check("playlists", self.playlists)
        self.check("recommendations", self.recommendations)
        self.check("export and error reporting", self.export_and_errors)
        self.check("cross-site requests refused", self.csrf)
        self.check("account deletion", self.delete_account)
        print(f"\n{len(self.failures)} failure(s)")
        return 1 if self.failures else 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--base", default="http://127.0.0.1:8080")
    parser.add_argument(
        "--mailpit", help="Mailpit URL: check e-mail journeys end to end"
    )
    args = parser.parse_args()
    sys.exit(Smoke(args.base, args.mailpit).run())
