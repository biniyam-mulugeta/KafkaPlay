# syntax=docker/dockerfile:1.7
#
# Single image: the React bundle is built in stage 1 and served by the FastAPI
# process in stage 2, so deployment is one container.
#
# Build context is the repository root, because the frontend imports the shared
# locale files from locales/.

# ---------------------------------------------------------------------------
# Stage 1 -- frontend
# ---------------------------------------------------------------------------
FROM node:24.13.0-bookworm-slim AS frontend

WORKDIR /build

# Dependencies first so a source-only change reuses this layer.
COPY frontend/package.json frontend/package-lock.json ./frontend/
RUN --mount=type=cache,target=/root/.npm \
    cd frontend && npm ci --no-audit --no-fund

COPY locales/ ./locales/
COPY frontend/ ./frontend/

# tsconfig.build.json covers only shipped code; test fixtures live outside
# this stage's build context. Tests are typechecked by `make lint`.
RUN cd frontend && npx tsc --noEmit -p tsconfig.build.json && npx vite build

# ---------------------------------------------------------------------------
# Stage 2 -- runtime
# ---------------------------------------------------------------------------
FROM python:3.12.12-slim-bookworm AS runtime

# Never write .pyc, never buffer stdout (logs must stream to the collector).
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# No apt install at all. confluent-kafka ships manylinux wheels with librdkafka
# bundled, so there is no build toolchain to add, and the healthcheck uses the
# Python that is already here rather than pulling in curl. Smaller image, fewer
# packages to patch, and no apt version pin to rot.

WORKDIR /app

COPY backend/pyproject.toml ./backend/
COPY backend/app/__init__.py ./backend/app/
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --no-cache-dir "./backend[codecs,oidc]"

COPY backend/app/ ./backend/app/
COPY backend/healthcheck.py ./backend/
COPY themes/ ./themes/
COPY locales/ ./locales/
COPY --from=frontend /build/frontend/dist/ ./backend/static/

# Run as a non-root user that owns only what it must write to.
RUN groupadd --system --gid 10001 offsetscope \
 && useradd --system --uid 10001 --gid offsetscope --home /app --shell /usr/sbin/nologin offsetscope \
 && mkdir -p /data /config \
 && chown -R offsetscope:offsetscope /app /data /config

USER offsetscope
WORKDIR /app/backend

ENV CONSOLE_HOST=0.0.0.0 \
    CONSOLE_PORT=8080 \
    DATABASE_URL=sqlite:////data/offsetscope.db \
    CLUSTERS_FILE=/config/clusters.yaml \
    THEMES_DIR=/app/themes \
    LOG_FORMAT=json

EXPOSE 8080
VOLUME ["/data"]

# Liveness only: a broker being unreachable is a degraded state reported in the
# API, not a reason for the orchestrator to restart this container.
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD ["python", "healthcheck.py"]

CMD ["sh", "-c", "exec uvicorn app.main:create_app --factory --host \"$CONSOLE_HOST\" --port \"$CONSOLE_PORT\" --no-access-log"]
