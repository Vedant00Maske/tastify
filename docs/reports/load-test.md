# Load test (Milestone 7)

Run on 2026-11-19 with `scripts/loadtest.py` against the production stack
(`docker-compose.prod.yml` with the smoke overlay), through Caddy, with the full development
catalogue (42,952 tracks, four active models) loaded by `infrastructure/backup/catalogue.sh`.
Design decisions: [ADR-020](../ADR/ADR-020-production-hardening.md).

## Method

Each virtual user registers, plays and likes twelve popular tracks (so recommendations are
personal, not cold start), then repeats weighted actions with a mean think time of one second:
the home page (its six requests in parallel, as the web app sends them) 30%, search 20%, a
track and its similar tracks 15%, feedback 15%, a mood mix 8%, popular charts 7%, a prompt
playlist 5%. Each user sends its own `X-Forwarded-For`, as distinct clients behind a load
balancer would (`CADDY_TRUSTED_PROXIES=private_ranges` in the smoke settings), so per-client
rate limits apply per user. Thirty seconds of warm-up are not measured. Personalized responses
are reported separately when served from the cache ("cached", `X-Cache: hit`) and when computed.

One virtual user with a one-second think time is far busier than a person: 20 virtual users
sent about 54 requests per second, the traffic of hundreds of people browsing normally.

**Environment.** One Windows 11 machine: Docker Desktop's VM with 16 vCPUs and 8 GB, running
PostgreSQL, Redis, Caddy, the frontend, 2 API replicas, 8 recommender replicas, the worker and
the load generator itself. Everything competes for the same CPUs, so these numbers are
conservative for a dedicated server.

## Results: 20 virtual users (target load)

90 s measured, 4,895 requests, 53.6 requests/s, no server errors.

| Endpoint | Requests | p50 ms | p95 ms | p99 ms |
| --- | ---: | ---: | ---: | ---: |
| for-you (cached) | 389 | 63 | 124 | 207 |
| for-you (computed) | 99 | 337 | 475 | 533 |
| hidden-gems (cached) | 387 | 77 | 177 | 231 |
| hidden-gems (computed) | 101 | 292 | 406 | 626 |
| because-you-listened (cached) | 323 | 82 | 173 | 262 |
| because-you-listened (computed) | 165 | 125 | 238 | 419 |
| custom (prompt playlist) | 77 | 178 | 477 | 589 |
| mood-mix | 134 | 76 | 241 | 332 |
| moods | 488 | 57 | 156 | 351 |
| popular | 121 | 30 | 88 | 237 |
| similar | 537 | 57 | 120 | 223 |
| search | 312 | 50 | 314 | 381 |
| track | 537 | 27 | 69 | 116 |
| me | 488 | 47 | 126 | 222 |
| history | 488 | 70 | 164 | 318 |
| interactions (feedback) | 249 | 107 | 159 | 218 |

Every endpoint's p95 is below the spec's 500 ms target (§4), which applies to cached and
precomputed recommendations; computed ones meet it as well. 404 answers from "similar" (97) are
tracks without a content embedding and are expected.

## Results: 50 virtual users (saturation)

120 s measured, 12,719 requests, 104.7 requests/s.

| Endpoint | p50 ms | p95 ms | p99 ms |
| --- | ---: | ---: | ---: |
| for-you (cached) | 220 | 506 | 752 |
| for-you (computed) | 613 | 998 | 1311 |
| hidden-gems (cached) | 358 | 834 | 1064 |
| custom | 398 | 909 | 1100 |
| search | 166 | 614 | 757 |
| me | 156 | 526 | 897 |
| track | 127 | 318 | 562 |

At about twice the target throughput latencies roughly double and one request in 12,719 timed
out. The machine is then CPU-bound across every process, including the load generator. On a
dedicated host, capacity grows by adding recommender replicas (`RECOMMENDER_REPLICAS`) up to the
number of cores, with PostgreSQL connections sized to match (`.env.production.example`).

## What the test found and changed

Each row is a measured problem, its cause and the fix (in order of discovery).

| Observation | Cause | Fix | Effect |
| --- | --- | --- | --- |
| One API process: 9.6 requests/s, for-you p95 11 s, `/users/me` p95 5.6 s | CPU-heavy ranking and Argon2 hashing run on the single event loop; every request queues behind them | One process per container, scaled by replicas; Argon2 in a bounded thread pool; recommendations on their own service | Cheap endpoints stay fast while ranking is busy |
| A `500` under load | Database pool exhausted | Pool exhaustion answers `503` with `Retry-After` and is counted (`soniqueo_overloaded_total`) | Overload is reported as overload |
| Repeated home pages recompute everything | No response cache | Per-user cache keyed by a state fingerprint; precompute after feedback | Throughput +75% in the first single-process test |
| About 29 database round trips per for-you | One HNSW query per seed track | One `LATERAL` query for all seeds | Identical neighbours, 3.7 times faster (20 seeds) |
| Track search 700-900 ms in the database | `OR` with a condition on the concatenated "artist title" scanned every track | Candidates through the trigram indexes, then the same scoring | Identical top 20 on 30 queries, 5 times faster |
| Mood mixes and prompts 350-550 ms of SQL per request | Genre and tag rankings recomputed for every request and replica | Cached per process by popularity version (one hour bound) | Repeated mixes skip the query |
| 8 recommender replicas: computed for-you p50 12-14 s, idle 0.33 s | numpy's BLAS started 16 threads in every process: 128 threads on 16 CPUs | `OMP_NUM_THREADS=1`, `OPENBLAS_NUM_THREADS=1` in the image | 12.8 to 53.6 requests/s; for-you p95 21.9 s to 0.48 s |

## Reproducing

```bash
docker compose -p soniqueo-smoke -f docker-compose.prod.yml \
  -f infrastructure/deployment/docker-compose.smoke.yml \
  --env-file infrastructure/deployment/smoke.env up -d --build --wait
docker exec -i soniqueo-postgres-1 sh -s export - < infrastructure/backup/catalogue.sh > catalogue.dump
docker compose -p soniqueo-smoke ... cp catalogue.dump backup:/backups/catalogue.dump
docker compose -p soniqueo-smoke ... exec backup sh /scripts/catalogue.sh import /backups/catalogue.dump
RECOMMENDER_REPLICAS=8 DB_POOL_SIZE=5 DB_MAX_OVERFLOW=5 docker compose -p soniqueo-smoke ... up -d --wait
python scripts/loadtest.py --base http://127.0.0.1:8080 --users 20 --warmup 30 --duration 90
```
