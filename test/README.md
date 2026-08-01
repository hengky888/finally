# FinAlly E2E Tests

Playwright suite covering the scenarios in `planning/PLAN.md` §12. Browser
dependencies live in the Playwright container, never in the production image.

## Run

```bash
cd test
docker compose -f docker-compose.test.yml up --build \
  --abort-on-container-exit --exit-code-from playwright
docker compose -f docker-compose.test.yml down -v
```

The app service starts with `LLM_MOCK=true` and no volume, so every run begins
against a pristine database.

## Run against an app you already have running

```bash
npm install && npx playwright install chromium
BASE_URL=http://localhost:8000 npx playwright test
```

The app must be running with `LLM_MOCK=true`, and `01-fresh-start` expects an
untouched database.

## Notes

- **Serial by design.** FinAlly is single-user: one portfolio, one database.
  Specs run in file-name order with a single worker, and `01-fresh-start` runs
  first because the seeded $10,000 is only observable before anything trades.
- **No retries.** A test that only passes on the second attempt is hiding a
  defect, so retries are off and flakes are treated as findings.
- **No fixed sleeps.** Waits are on real conditions — a response arriving, the
  stream sequence advancing, an element appearing.
- The compose service is named `finally-app` rather than `app` because Chromium
  HSTS-preloads the entire `.app` TLD, which force-upgrades `http://app:8000`
  to HTTPS and fails every navigation with `ERR_SSL_PROTOCOL_ERROR`.
