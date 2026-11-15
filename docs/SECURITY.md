# TASTIFY — Security and Privacy

> Derived from the approved specification [TASTIFY_v0.1.md](../TASTIFY_v0.1.md) (§12).
> This file is the maintained version: update it in the same pull request as the code it describes.

## 12. Security and Privacy Architecture

### 12.1 Authentication

Use OAuth 2.0/OIDC where supported.

For local authentication:
- Argon2id password hashing.
- Secure session cookies.
- Session expiration.
- Refresh and revocation controls.

### 12.2 External Credentials

- Encrypt tokens at rest.
- Never expose tokens to the frontend.
- Never log access tokens.
- Request minimum necessary scopes.
- Support token revocation.
- Separate user tokens from application credentials.

### 12.3 Authorization

Use user-level ownership checks for:
- Playlists.
- Preferences.
- Interactions.
- Personal listening history.
- External connections.

### 12.4 Privacy

Provide:
- Clear consent.
- Data export.
- Account deletion.
- Provider disconnection.
- Data retention controls.
- Personalization opt-out.

Do not collect precise location or unnecessary device information for recommendations.

---

## Repository and supply-chain practices (implemented)

- `.env` is git-ignored. `.env.example` contains only placeholders. Provider credentials are read
  from the environment, never from code or config files.
- **Secret scanning:** gitleaks runs in CI over the full history. The pre-commit `detect-private-key`
  hook blocks private keys locally.
- **Dependency auditing:** `pip-audit` (backend) and `npm audit --omit=dev --audit-level=high`
  (frontend) run in CI. Dependabot proposes weekly updates for pip, npm, GitHub Actions and Docker
  base images.
- **Static analysis:** ruff's flake8-bandit (`S`) rules flag common Python security issues.
- **Containers:** production images run as non-root users. In local development, docker compose
  publishes PostgreSQL, Redis and the apps on `127.0.0.1` only.

If a secret is ever committed: **rotate it first**, then remove it from the git history. Deleting it in
a later commit is not enough.
