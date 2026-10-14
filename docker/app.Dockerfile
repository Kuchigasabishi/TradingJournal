#
# The Trading Journal as one image: FastAPI serves the API at /api and the Expo web export at /, so the app and its
# API share one origin. Build from the repository root:
#
#     docker build -f docker/app.Dockerfile -t tradingjournal/app:local .
#
# Stage 1 compiles the web export. Stage 2 is the runtime: no Node, no compilers, no test code, a non-root user and
# nothing writable but the data volume (SQLite lives on /data).

# --- Stage 1: the web export --------------------------------------------------------------------------------------
FROM node:24-slim AS web

ENV CI=1 \
    EXPO_NO_TELEMETRY=1 \
    NPM_CONFIG_UPDATE_NOTIFIER=false \
    NPM_CONFIG_FUND=false

WORKDIR /build/frontend

# Dependencies first, so a change to the source does not reinstall them.
COPY frontend/package.json frontend/package-lock.json ./
RUN --mount=type=cache,target=/root/.npm npm ci

# EXPO_PUBLIC_API_URL stays unset: the web build talks to the origin that served it.
COPY frontend/ ./
RUN npx expo export --platform web --output-dir /build/web-dist \
    && test -f /build/web-dist/index.html

# --- Stage 2: the runtime -----------------------------------------------------------------------------------------
FROM python:3.14-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# The pinned lock (uv pip compile), runtime dependencies only: no pytest, no uv.
COPY backend/requirements.txt /tmp/requirements.txt
RUN pip install -r /tmp/requirements.txt && rm /tmp/requirements.txt

# A user with no shell and no home. The application code is owned by root and readable, so a compromised process
# cannot rewrite it; only /data belongs to the app.
RUN groupadd --system --gid 10001 app \
    && useradd --system --uid 10001 --gid app --no-create-home --home-dir /nonexistent --shell /usr/sbin/nologin app \
    && mkdir /data && chown app:app /data

WORKDIR /app
COPY backend/app ./app
COPY backend/migrations ./migrations
COPY backend/alembic.ini backend/log_config.json ./
COPY --from=web /build/web-dist ./web

# Bytecode is compiled now, because the root filesystem is read-only when the container runs.
RUN python -m compileall -q /app/app /app/migrations

ENV APP_ENV=prod \
    DATABASE_URL=sqlite:////data/tj.db \
    STATIC_DIR=/app/web \
    AUTO_MIGRATE=true

USER app
VOLUME /data
EXPOSE 8000

# Liveness, through the standard library (the slim image has no curl). docker-compose.yml repeats this on purpose:
# the compose file is the production definition and states its healthcheck itself.
HEALTHCHECK --interval=10s --timeout=3s --start-period=20s --retries=3 \
    CMD ["python", "-c", "import json, urllib.request as u; r = u.urlopen(u.Request('http://127.0.0.1:8000/api/health', headers={'X-Request-ID': 'healthcheck'}), timeout=2); raise SystemExit(0 if r.status == 200 and json.load(r) == {'status': 'ok'} else 1)"]

# One worker, always: a second would double-fetch the feeds and trip the news host's rate limit (docs/BLUEPRINT.md, P2).
# The app runs its migrations itself at startup (AUTO_MIGRATE), so the process that serves is the one that migrated.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--log-config", "log_config.json", "--no-server-header"]
