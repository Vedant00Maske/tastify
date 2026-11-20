# Security audit (Milestone 7)

Performed 2026-11-19 on the code at Milestone 7 (ADR-020). Scope: the API, the web app, the
deployment stack and the supply chain, against the spec's security testing list (§11.6), its
security architecture (§12) and the OWASP Top 10 (2021). Every check below is automated in CI
unless marked as a manual review.

## Findings and fixes

| # | Severity | Finding | Fix | Regression test |
| --- | --- | --- | --- | --- |
| 1 | High | **Open redirect after sign-in.** `safeNext` accepted `/\evil.example`; browsers read a backslash as a slash, so it meant `//evil.example`. | Backslashes and control characters are refused and the path must resolve to the same origin. | `logic.test.ts`, journey "sign-in never redirects to another site" |
| 2 | Medium | **Password guessing through a stolen session.** Password change and account deletion verify the password but were not rate limited. | 10 confirmations per user per 15 minutes, shared by both. | `test_password_confirmations_are_rate_limited` |
| 3 | Medium | **OAuth codes and search terms in logs.** uvicorn's access log printed full URLs, including `?code=…&state=…` on the OAuth callback. | uvicorn's access log replaced by an access line with the route template; a redaction filter masks bearer tokens, `code=`, `token=`, passwords and session cookies in every message and traceback; Caddy's log drops query strings and cookies; `httpx` request logging silenced. | `test_secrets_never_reach_the_logs`, `test_secrets_are_redacted` |
| 4 | Medium | **Denial of service through Argon2.** Hashing (64 MiB, tens of ms) ran on the event loop: a burst of logins stalled every request in the process. | Hashing runs in a thread pool, at most four at a time per process. | Load test (`load-test.md`) |
| 5 | Low | **Rate-limit counters could lose their expiry.** `INCR` and `EXPIRE` were separate calls; a crash between them locked a key out forever. | One atomic Lua script; a counter without expiry gets one. | `test_rate_limit_counters_always_expire` |
| 6 | Low | **Unbounded request bodies.** | 1 MiB limit in the API (declared or streamed, `413`) and 2 MB at Caddy. | `test_oversized_bodies_are_refused` |
| 7 | Low | **Expensive endpoints without limits** (search, prompt playlists, MusicBrainz search, imports, exports, data export, feedback). | Per-client or per-user limits (`app/domains/auth/rate_limit.py`), failing open if Redis is down. | `test_search_and_prompts_are_rate_limited` |
| 8 | Low | **Interactive API docs and OpenAPI schema public in production.** | Disabled in production (`API_DOCS_ENABLED_OVERRIDE` to re-enable). | `test_deployment_settings_are_checked` |
| 9 | Low | **Missing security headers.** | API: `nosniff`, `DENY` framing, `no-referrer`, `no-store`, `default-src 'none'` CSP, HSTS when deployed. Pages: CSP (same-origin only), framing denied, referrer limited, permissions policy, COOP. | `test_responses_carry_security_headers_and_a_request_id`, smoke test |
| 10 | Info | **Unsafe production configuration was possible** (HTTP origins, insecure cookies, default database password). | The API refuses to start in production while any are present; `python -m app.cli check-config`. | `test_production_refuses_unsafe_settings`, CI deploy-smoke |
| 11 | Info | **Unhandled errors** returned Starlette's plain 500. | Generic JSON 500 with the request id; details only in logs and error tracking. | `test_unhandled_errors_are_generic_and_traceable` |

No critical findings. Nothing found indicated that data had been exposed.

## Spec §11.6 checklist

| Area | How it is tested | Result |
| --- | --- | --- |
| Broken access control | Route sweep: every operation in the OpenAPI schema is either listed as public or must answer `401` without a session (a new route fails the test until classified). Forged session cookies are rejected. | Pass |
| Insecure direct object references, unauthorized playlist changes | A second user tries all ten playlist operations (read, rename, add, remove, reorder, regenerate, suggestions, export, exports, delete) on another user's playlist: all `404`, nothing changes. Personal routes take the user from the session only (`/users/me/…`). | Pass |
| SQL injection | Classic payloads in track and artist search, lookup, genre paths and prompts: no `5xx`, no rows matched, tables intact. All SQL is parameterized (SQLAlchemy; the few `text()` queries use bound parameters). | Pass |
| Cross-site scripting | Script payloads in display names and playlist names are stored and returned verbatim as JSON with `nosniff` and a `default-src 'none'` CSP; React escapes text; no `dangerouslySetInnerHTML` in the app (manual review). | Pass |
| CSRF | State-changing requests from another origin are refused (`403`); session cookies are `SameSite=Lax`. Verified in the API tests and the production smoke test. | Pass |
| OAuth state validation | Single-use state bound to the user, PKCE (Milestone 5 tests: replay, another user's state, expired state). | Pass |
| Token leakage | Provider tokens never in responses or exports (Milestone 5 tests); passwords, cookies, reset tokens and OAuth codes never in logs (test above); reset and verification tokens are removed from the address bar after use and only their hashes are stored. | Pass |
| Rate-limit bypass | Inventing `X-Forwarded-For` addresses from an untrusted peer does not escape the limit; Caddy replaces client-supplied forwarding headers. | Pass |
| Account enumeration | Login does the same work for unknown e-mails; reset requests answer `202` either way and do the work after the response; the per-address reset limit is silent. | Pass |

## Supply chain and infrastructure

- `pip-audit` (backend and ML requirements) and `npm audit --omit=dev`: no known vulnerabilities
  on 2026-11-19; both run in CI on every change, Dependabot proposes weekly updates.
- New dependencies pinned to releases at least two weeks old: `prometheus-client 0.26.0`,
  `sentry-sdk 2.74.0`. Infrastructure images pinned by version (Caddy 2.11, Prometheus v3.15.1,
  Alertmanager v0.34.2, Grafana 13.1, Mailpit v1.32.0).
- gitleaks scans the full history in CI; secrets live only in `.env` / `.env.production`
  (git-ignored).
- Containers: non-root, read-only root filesystems, `no-new-privileges`; only Caddy publishes
  ports; PostgreSQL and Redis require passwords and are unreachable from outside; Grafana and
  Prometheus bind to `127.0.0.1` on the host. Shell scripts pass shellcheck; Caddy, Prometheus
  and Alertmanager configurations are validated in CI.

## Accepted risks

- **`'unsafe-inline'` scripts in the page CSP.** Next.js streams page data in inline scripts;
  nonces would require rendering every page per request, which prerendering
  (`cacheComponents`) cannot do. Mitigated by React's escaping, same-origin-only sources for
  scripts and connections, and no third-party scripts. Revisit when hashes for streamed payloads
  are supported.
- **E-mail tokens pass through the job queue.** A reset link is in the queued message until the
  worker sends it (Redis, password-protected, internal network only).
- **No multi-factor authentication** yet; reset links and sessions are the recovery path.
- **Single host.** See ADR-020 for availability and recovery targets.
