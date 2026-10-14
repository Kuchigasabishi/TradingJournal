# CLAUDE.md - Trading Journal & Calendar Monolith

Locked architecture decisions, the phase roadmap and the verification contract live in [docs/BLUEPRINT.md](docs/BLUEPRINT.md). Read it before changing the architecture.

## Architecture Overview
- Monolithic repository.
- **Backend:** FastAPI (Python), handling API routes, SQLite/PostgreSQL local persistence, and free calendar/RSS data fetchers.
- **Frontend:** React Native (Expo / universal web & mobile build target).
- **Constraints:** Zero paid APIs. Use public RSS/JSON feeds for ForexFactory-style economic events and free Google Calendar public/iCal or service account integrations.
- **Testing Harness:** Containerized Docker setup with a headless Playwright sidecar testing both FastAPI endpoints (server-side) and rendered React Native Web/DOM elements (client-side).
- **Logging & Artifacts:** Output structured logs to `logs/` and capture phase-by-phase verification screenshots into `artifacts/phase_{N}/screenshots/`.
- **Containers:** `docker-compose.yml` is the production definition (one app container, named volume `tj_data`); running and looking after it is in [docs/RUNBOOK.md](docs/RUNBOOK.md). `python scripts/verify.py N --backend compose` runs a phase's whole suite in containers (Docker Desktop required; the first run downloads the 3.5 GB Playwright image). Never edit repo files while a verification runs.
