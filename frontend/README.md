# Trading Journal: frontend

The universal web UI, built with Expo (SDK 57), Expo Router and TypeScript. The web build is what gets verified end to end; iOS and Android only have to bundle. The design record is in [docs/BLUEPRINT.md](../docs/BLUEPRINT.md), section 5.

## Run it

One-time setup (Node.js 24 LTS):

```powershell
cd frontend
npm ci
```

**Against a built copy, the way verification does it.** The API serves the web export at `/`, so the app and the API share one origin and need no CORS or API URL.

```powershell
npm run export:web                         # writes frontend\dist
cd ..\backend
$env:STATIC_DIR = "..\frontend\dist"; $env:APP_TIMEZONE = "America/New_York"
..\.venv\Scripts\python.exe -m uvicorn app.main:app --log-config log_config.json
# open http://127.0.0.1:8000
```

**With fast refresh.** Run the API on :8000 as above (set `APP_ENV=dev`, which allows the dev server's origin through CORS) and start Metro on :8081 pointed at it:

```powershell
$env:EXPO_PUBLIC_API_URL = "http://127.0.0.1:8000"; npm run web
```

## Scripts

| Command | What it does |
|---------|--------------|
| `npm run typecheck` | Strict TypeScript over the app and over the tests |
| `npm test` | Unit tests for `src/lib` (exact decimals, money formatting, time zones, validation, filters, events). Node's built-in test runner, no framework |
| `npm run export:web` | Production web build into `dist/` |
| `npm run gen:api` | Regenerates `src/api/schema.d.ts` from a running API on :8000 |

`python scripts/verify.py 2` runs all of this, builds the web and native bundles, serves the build and drives it with Playwright. `python scripts/verify.py 3` adds the feed connectors, against a local stub of both hosts.

## Events from outside calendars

The calendar and the day screen show ForexFactory's economic news and your Google Calendar. Nothing runs until the API is told to: put `FEEDS_MODE=live` in the repo-root `.env` (and your calendar's secret iCal address in `GCAL_ICAL_URL`; see `.env.example`), restart the API, and open the calendar. "Sync now" under the grid refreshes both feeds. The address of your calendar stays on the server and never reaches this app.

News impact is drawn in an amber ramp so it never borrows the blue or red of a gain or a loss. `node tools/derive-impact-ramp.mjs` reproduces the three colours in `src/theme.ts` and runs the checks they have to pass.

## Settings (build time)

| Variable | Default | Meaning |
|----------|---------|---------|
| `EXPO_PUBLIC_API_URL` | empty | Empty means same origin. Set a full URL for `expo start` and for native builds |
| `EXPO_PUBLIC_ACCOUNT_CURRENCY` | `USD` | The currency P&L is shown in. The journal keeps one account, so this is a display setting |

## Rules that are checked

- **Money never becomes a float.** Amounts, prices and lot sizes travel as strings and are handled as `bigint` counts of 1e-8 (`src/lib/decimal.ts`). `parseFloat`, `toFixed`, `Intl.NumberFormat` and `toLocaleString` are rejected by the `frontend-rules` gate.
- **Links go through `PressableLink`** (`src/ui/controls.tsx`). expo-router's `<Link asChild>` merges the child's `style` with an object spread, so an array or function style crashes a production build.
- **`src/api/schema.d.ts` is generated, never edited.** The `api-contract` gate fails when it no longer matches the running API.
- Every request carries `X-Request-ID: web-<hex>`, which is how verification proves each endpoint is reached from the UI.
