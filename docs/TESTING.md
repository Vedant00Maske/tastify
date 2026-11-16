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

- `backend/tests/unit/` is fast, with no network. External dependencies are replaced with fakes
  through `app.dependency_overrides`.
- `backend/tests/integration/` is marked `@pytest.mark.integration`. These tests use the isolated
  `tastify_test` database and Redis DB 15. Override them with `TEST_DATABASE_URL` and `TEST_REDIS_URL`.
- The `migrated_database` fixture brings the test schema to `head`. Use it in any test that needs
  tables.
- Frontend tests sit next to the code they test (`*.test.ts(x)` under `src/`). E2E specs live in
  `frontend/e2e/`.
- Test names describe behaviour, for example `test_readiness_returns_503_when_dependencies_are_unreachable`.

### In CI (`.github/workflows/ci.yml`)

Every push to `main` and every pull request runs:

- backend lint, format and types
- migrations (upgrade → downgrade → upgrade, plus `alembic check`)
- backend unit and integration tests with coverage
- frontend lint, format, types, unit tests and production build
- Playwright E2E against the production build
- the secret scan and dependency audits
- production Docker image builds
