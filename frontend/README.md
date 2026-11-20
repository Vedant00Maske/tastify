# SONIQUEO Frontend

Next.js (App Router) + TypeScript + Tailwind CSS. See the [root README](../README.md) and
[docs/DEVELOPMENT.md](../docs/DEVELOPMENT.md) for the full setup.

```bash
npm ci                 # install exact versions from package-lock.json
npm run dev            # http://localhost:3000

npm run lint           # ESLint
npm run format:check   # Prettier (npm run format to fix)
npm run typecheck      # next typegen + tsc
npm test               # Vitest unit/component tests
npm run test:e2e       # Playwright (first time: npm run test:e2e:install)
```

Source layout (`src/`):

| Folder        | Purpose                                                                  |
| ------------- | ------------------------------------------------------------------------ |
| `app/`        | Routes, layouts and pages (App Router)                                   |
| `components/` | Shared, presentational UI components                                     |
| `features/`   | Feature modules: auth, discovery, playlists, taste-profile, integrations |
| `hooks/`      | Shared React hooks                                                       |
| `services/`   | API client and other side-effecting modules                              |
| `types/`      | Shared TypeScript types (API contracts mirror backend schemas)           |

`AGENTS.md` is generated and maintained by `next dev`; commit it as-is.
