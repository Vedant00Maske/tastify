# TASTIFY — Testing Strategy

> Derived from the approved specification [TASTIFY_v0.1.md](../TASTIFY_v0.1.md) (§11).
> This file is the maintained version: update it in the same pull request as the code it describes.

## 11. Testing Strategy

Testing is a first-class development requirement.

### 11.1 Unit Testing

Tools:
- pytest.
- pytest-cov.
- Vitest.

Test:
- User services.
- Repository methods.
- Feature engineering.
- Recommendation scoring.
- Candidate filtering.
- Diversity algorithms.
- Playlist operations.

### 11.2 Integration Testing

Test:
- Backend and PostgreSQL.
- Backend and Redis.
- Repository and database.
- Recommendation service and ML models.
- Background processing.
- Provider adapters.

Use isolated test databases and mock external services where appropriate.

### 11.3 ML Testing

#### Data Tests
- Missing value checks.
- Duplicate detection.
- Feature range validation.
- Data leakage checks.
- Schema compatibility.

#### Model Tests
- Deterministic inference where expected.
- Output shape validation.
- Score normalization.
- Cold-start behaviour.
- Model version compatibility.

#### Recommendation Tests
- Precision@K.
- Recall@K.
- NDCG@K.
- MAP@K.
- Catalog coverage.
- Diversity.
- Novelty.

### 11.4 API Contract Testing

Validate:
- Request schemas.
- Response schemas.
- Authentication failures.
- Authorization failures.
- Pagination.
- Rate limiting.
- Invalid parameters.
- Provider failures.

### 11.5 End-to-End Testing

Tools:
- Playwright.

Test user journeys:

1. Registration.
2. Login.
3. Onboarding.
4. Connecting a music provider.
5. Generating recommendations.
6. Liking and skipping tracks.
7. Generating a playlist.
8. Editing a playlist.
9. Exporting a playlist.
10. Disconnecting a provider.
11. Deleting an account.

### 11.6 Security Testing

Test:
- Broken access control.
- SQL injection.
- Cross-site scripting.
- CSRF where applicable.
- OAuth state validation.
- Token leakage.
- Rate-limit bypass.
- Insecure direct object references.
- Unauthorized playlist modifications.

### 11.7 Initial Quality Gates

- All critical unit and integration tests pass.
- No unresolved critical security vulnerabilities.
- API contracts are validated.
- Database migrations work from a clean database.
- ML evaluation results are recorded.
- No user can access another user's private playlists.
- No provider credential is committed to source control.

---

## Running the tests

Tooling set up in Milestone 0:

| Layer                     | Tool                                   | Command (from the package directory)                                  |
| ------------------------- | -------------------------------------- | --------------------------------------------------------------------- |
| Backend unit              | pytest, pytest-asyncio, httpx          | `pytest -m "not integration"`                                         |
| Backend integration       | pytest against real PostgreSQL + Redis | `pytest -m integration` (needs `docker compose up -d postgres redis`) |
| Backend coverage          | pytest-cov                             | `pytest --cov`                                                        |
| Frontend unit / component | Vitest, React Testing Library, jsdom   | `npm test` (`npm run test:watch` while developing)                    |
| Frontend coverage         | @vitest/coverage-v8                    | `npm run test:coverage`                                               |
| End-to-end                | Playwright (Chromium)                  | `npm run test:e2e` (first run: `npm run test:e2e:install`)            |
| ML pipelines              | pytest (+ PostgreSQL for `integration`) | `cd ml && pytest` (unit only: `pytest -m "not integration"`)       |

### Layout and conventions

- `ml/tests/` covers the pipelines with small synthetic fixtures (tar.zst dumps, CSVs, zip archives
  built in the test), so no downloads are needed. `test_keys.py` checks that the vectorized
  matching keys match the backend's Python rules exactly.
- Recommendation tests (Milestone 2): metrics are checked against hand-computed values
  (`test_evaluation_metrics.py`); `test_evaluation_split.py` checks that no interaction crosses the
  cutoff; `test_recommenders.py` checks that evaluated recommenders rank exactly like the backend's
  `rerank`; `integration/test_recommendation_publish.py` publishes models to PostgreSQL, serves them
  through `RecommendationService` and runs the retrieval benchmark. On the backend,
  `tests/integration/recommendations/` exercises every endpoint on a hand-built model whose
  expected rankings are computed in the test.
- Personalization tests (Milestone 3). Parity with the libraries the models come from:
  `test_collaborative.py` checks that the API's fold-in, BM25 weighting and item-item scoring
  reproduce `implicit` exactly, and `test_ltr.py` that the backend's numpy tree evaluator reproduces
  LightGBM's predictions (missing values included) and that training is deterministic.
  `test_hybrid_engine.py` runs the offline engine on a synthetic world (signals equal the backend's
  aggregation, candidates are unheard and attributed, generation is deterministic, a failing source
  is isolated). `integration/test_personalization_publish.py` publishes collaborative and hybrid
  versions, serves a TASTIFY user through the API service and checks the served collaborative scores
  against the offline model. On the backend, `tests/unit/users/` covers event aggregation and taste
  profiles (recent listening does not erase long-term taste, cautious negatives, declared
  preferences, reproducibility), `tests/unit/recommendations/` the merger, filter, features,
  rankers, MMR and composition, and `tests/integration/users/` the user API end to end (ingestion
  and idempotency, preferences, exploration modes, exclusions, cold start, opt-out, a failing
  source, artist radio).
- Application tests (Milestone 4). Backend: `tests/integration/users/test_auth_api.py` covers
  registration rules, login, logout, the HttpOnly cookie, revocation on password change, rate limits, the
  Origin check, export and account deletion; `test_collections_api.py` covers moods (regenerate
  with `exclude`), hidden gems, Surprise Me, because-you-listened, playlists (lifecycle, ownership,
  reorder, regenerate, suggestions), artist search, genres, artwork and the stored taste profile's
  ordering; `tests/unit/test_milestone4_logic.py` the password policy, analytics helpers, mood
  recipes and trusted-proxy parsing. Frontend: `src/services/api-client.test.ts` (requests,
  errors, response validation), `src/lib/logic.test.ts` (formatting, form schemas, safe redirects,
  the player queue) and `src/components/components.test.tsx` (feedback buttons record the right
  events, track cards, the exploration slider's accessible value, empty and error states,
  recent searches without storage). `frontend/e2e/journeys.spec.ts` runs the critical journeys
  (sign-in redirect, register and onboarding, dashboard feedback and the player, discovery and
  moods, playlists, taste, search, logout) against an in-memory API (`e2e/support/mock-api.ts`)
  that intercepts `/api/v1` in the browser, so they need no backend; a journey fails if the app
  calls an endpoint the mock does not know. `e2e/accessibility.spec.ts` runs axe-core (WCAG 2.1
  A and AA) on every page at 1440 and 390 px; `e2e/layout.spec.ts` fails if any page scrolls
  sideways at 360, 768, 1024 or 1920 px and keeps screenshots in `test-results/`. Session expiry
  and the sliding refresh are covered in `test_auth_api.py`.
- Milestone 6. `backend/tests/unit/test_milestone6_logic.py`: prompt reading (genres, moods,
  artists, exclusions, tempo, era, popularity), stable weighted assignment, Wilson intervals,
  the two-proportion test and verdicts, session and daypart fits.
  `backend/tests/integration/users/test_milestone6_api.py`: prompt playlists by genre and by
  artist with exclusions, the `422` for unmatched prompts, personalization and logging, saving
  and regenerating prompt playlists, for-you logging with attributed feedback, an experiment from
  assignment to report, the session nudge. `ml/tests/test_context_experiment.py` checks that the
  offline context model equals the API's (dayparts, shrinkage, session windows, offset
  inference). The E2E journey creates, regenerates and saves a prompt playlist; `/create` is in
  the accessibility and layout checks.
- Integration tests (Milestone 5). `backend/tests/integration/integrations/fakes.py` implements
  in-memory ListenBrainz, Spotify, YouTube and MusicBrainz servers (httpx `MockTransport`) that
  follow the providers' documented shapes, record calls and can fail on demand.
  `test_integrations_api.py` covers token validation and encryption at rest, consent, matching
  by MBID, ISRC and key, incremental re-import, OAuth with PKCE and single-use state, token
  refresh and `reauth_required`, retry-safe exports (failure after creation, lost remote id),
  Spotify ISRC matching with the id cache, the YouTube quota refusing before any call, ownership,
  failure isolation and disconnecting with deletion of imported history.
  `tests/unit/test_integrations_logic.py` covers the cipher, PKCE, idempotency keys, listen
  parsing, quota estimates and query escaping. The E2E journeys connect ListenBrainz, import,
  export a playlist and use the MusicBrainz fallback.

- `backend/tests/unit/` is fast, with no network. External dependencies are replaced with fakes
  through `app.dependency_overrides`.
- `backend/tests/integration/` is marked `@pytest.mark.integration`. These tests use the isolated
  `tastify_test` database and Redis DB 15. Override them with `TEST_DATABASE_URL` and `TEST_REDIS_URL`.
- The `migrated_database` fixture brings the test schema to `head`. Use it in any test that needs
  tables.
- Frontend tests sit next to the code they test (`*.test.ts(x)` under `src/`). E2E specs live in
  `frontend/e2e/`.
- Test names describe behaviour, for example `test_readiness_returns_503_when_dependencies_are_unreachable`.
- On Windows, run the frontend tests from PowerShell or `cmd`, not Git Bash: Git Bash reports the
  working directory with a lower-case drive letter (`d:/…`), Node resolves `D:\…`, and Vitest then
  loads its setup file twice ("failed to find the current suite").

### In CI (`.github/workflows/ci.yml`)

Every push to `main` and every pull request runs:

- backend lint, format and types
- migrations (upgrade → downgrade → upgrade, plus `alembic check`)
- backend unit and integration tests with coverage
- frontend lint, format, types, unit tests and production build
- Playwright E2E against the production build
- the secret scan and dependency audits
- production Docker image builds
