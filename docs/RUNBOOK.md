# TASTIFY: Operations runbook

How to deploy, roll back, restore, rotate secrets and respond to alerts. Architecture and first
installation: [DEPLOYMENT.md](DEPLOYMENT.md). Design: [ADR-020](ADR/ADR-020-production-hardening.md).

All commands run on the server, in the repository checkout, with:

```bash
alias dc='docker compose -f docker-compose.prod.yml --env-file .env.production'
```

## Targets

| | Target | How |
| --- | --- | --- |
| Availability | 99.5% a month (about 3.6 hours of downtime) | Health-checked replicas, automatic restarts, alerts |
| Recovery point (RPO) | 24 hours | Daily backups, plus one before every deploy |
| Recovery time (RTO) | About 1 hour | Restore from the newest backup (below) |
| Recommendation latency | p95 below 500 ms, cached and precomputed | Load test, `RecommendationLatencyHigh` alert |

## Deploy

Releases are tagged (`v0.7.0`). Pushing the tag publishes the images; the deploy job waits for
approval in the GitHub `production` environment, then runs `scripts/deploy.sh v0.7.0` over SSH.
By hand on the server:

```bash
sh scripts/deploy.sh v0.7.0
```

The script backs up the database, pulls the images, migrates, recreates the services (a few
seconds of unavailability), reloads Caddy, checks readiness through the public address and
records the version in `.deployed` (the previous one in `.deployed.previous`).

**Migrations must be backwards compatible with the running version** (expand, then contract):
add columns and tables first; remove or rename them only in a later release, after the code no
longer uses them. Then a rollback never needs a schema downgrade.

## Roll back

```bash
sh scripts/deploy.sh "$(cat .deployed.previous)"
```

If the release you are leaving ran a migration that is not backwards compatible (it should not
have), restore the pre-deploy backup instead (below): the newest `tastify-*.dump` before the
deploy time.

## Backups

- Automatic: daily, kept `BACKUP_KEEP_DAYS` (14), in the `backups` volume. Also before every
  deploy. The `BackupTooOld` alert fires after 26 hours without a successful one.
- One now: `dc exec backup sh /scripts/backup.sh --once`
- List: `dc exec backup ls -lh /backups`
- **Copy them off the server** daily (another region or provider), encrypted, for example:
  `docker run --rm -v tastify-prod_backups:/b alpine tar -C /b -cf - . | age -r <key> > backups.tar.age`
  then upload. A backup that only exists on the same disk does not survive the server.
- **Back up `INTEGRATIONS_TOKEN_KEY` separately** (a password manager): database backups contain
  provider tokens encrypted with it.

### Restore test (monthly)

```bash
dc exec backup sh /scripts/verify.sh
```

Restores the newest backup into a scratch database, compares it with the live one and drops it.
`verify: OK` means the backup is usable.

### Restore

1. Stop writers: `dc stop api recommender worker beat`
2. Restore (replaces the live database):
   `dc exec backup sh /scripts/restore.sh /backups/tastify-<time>.dump tastify --replace`
3. Bring the schema to the running release: `dc run --rm migrate`
4. Start: `dc up -d --wait api recommender worker beat`
5. Flush cached recommendations (they describe the old state):
   `dc exec redis sh -c 'redis-cli -a "$REDIS_PASSWORD" --no-auth-warning --scan --pattern "reccache:*" | xargs -r redis-cli -a "$REDIS_PASSWORD" --no-auth-warning del'`
6. Run the smoke test: `python3 scripts/smoke_test.py --base https://<domain>`

Data written between the backup and the failure is lost (that is the RPO). Tell affected users.

### Rebuilding a lost server

Install Docker, clone the repository, restore `.env.production` (password manager), start
PostgreSQL (`dc up -d --wait postgres`), copy the newest off-site backup into the `backups`
volume, restore as above, then `sh scripts/deploy.sh <version>`.

## Secrets

| Secret | Rotate | Effect |
| --- | --- | --- |
| `INTEGRATIONS_TOKEN_KEY` | Put the old key in `INTEGRATIONS_TOKEN_PREVIOUS_KEYS='["<old>"]'`, set a new key, redeploy, run `dc run --rm api python -m app.cli rotate-token-key`, then remove the old key and redeploy | None; connections keep working. If the key is lost, users reconnect their services. |
| `POSTGRES_PASSWORD` | `dc exec postgres psql -U tastify -c "ALTER USER tastify PASSWORD '<new>'"`, update `.env.production`, `dc up -d --force-recreate` | Seconds of unavailability |
| `REDIS_PASSWORD` | Update `.env.production`, `dc up -d --force-recreate redis api recommender worker beat` | Rate-limit counters and cached mixes reset |
| Session compromise (everyone signs in again) | `dc exec postgres psql -U tastify -c "UPDATE user_sessions SET revoked_at = now() WHERE revoked_at IS NULL"` | All users signed out |
| SMTP, Spotify, Google, Sentry credentials | Rotate at the provider, update `.env.production`, redeploy | None |

After any suspected leak: rotate first, then investigate (logs carry request ids, never secrets).

## Alerts

| Alert | First steps |
| --- | --- |
| `TargetDown` | `dc ps`; `dc logs --tail 100 <service>`. A replica that keeps restarting: look for the startup error (an unsafe production setting names itself). |
| `HighErrorRate` | Grafana "Requests per second by status"; `dc logs api recommender \| grep '"level": "ERROR"'`; each error line has a `request_id` matching the client's `X-Request-ID` and the error-tracking event. |
| `ServiceOverloaded` | Every database connection is busy. Add replicas (`API_REPLICAS`, `RECOMMENDER_REPLICAS`) if CPU allows, or raise `DB_POOL_SIZE` within `POSTGRES_MAX_CONNECTIONS`. |
| `RecommendationLatencyHigh` | Grafana "Ranking stages" (candidates vs ranking) and "Cache hit rate". Low hit rate: is the worker running (precompute)? High candidate time: `SlowDatabase`. CPU-bound: add recommender replicas. |
| `ApiLatencyHigh`, `SlowDatabase` | `dc exec postgres psql -U tastify -c "SELECT round(mean_exec_time) ms, calls, left(query, 120) FROM pg_stat_statements ORDER BY total_exec_time DESC LIMIT 10"`. Slow statements over 1 s are also in the PostgreSQL log. |
| `BackgroundJobsFailing` | `dc logs worker --tail 200`. Mail jobs retry for about a day on their own. |
| `EmailNotDelivered` | Check the SMTP account and `SMTP_*` settings; users can request a new link. |
| `BackupTooOld` | `dc logs backup`; disk space (`df -h`); run one now. |
| `ProviderErrors` | The provider may be down or have changed: see INTEGRATIONS.md; only that provider's features are affected. |
| `WebAppErrors` | `dc logs api \| grep tastify.client` (message, page, digest); the digest matches a Next.js server log line. |

## Routine

- **Daily (automatic):** backup; retention job at 03:30 UTC (expired sessions and e-mail links,
  recommendation logs past `RECOMMENDATION_LOG_RETENTION_DAYS`, stale provider ids). Run it now:
  `dc run --rm api python -m app.cli prune`.
- **Weekly:** Dependabot pull requests; review Grafana for trends.
- **Monthly:** restore test; check disk usage of volumes and backups.
- **Configuration check** after any change to `.env.production`:
  `dc run --rm api python -m app.cli check-config`.

## People's requests about their data

Users can export and delete everything themselves (Settings → Privacy). If someone cannot sign
in and asks for deletion, verify they control the address (a password reset proves it), or
delete by e-mail after verification:
`dc exec postgres psql -U tastify -c "DELETE FROM users WHERE email = lower('<address>')"`
(cascades to all their data; backups age out within `BACKUP_KEEP_DAYS`).
