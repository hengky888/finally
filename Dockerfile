# Stage 1 — build the Next.js static export.
FROM node:20-slim AS frontend

WORKDIR /build

# Manifests before source so the dependency layer caches across source edits.
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci

COPY frontend/ ./
RUN npm run build


# Stage 2 — Python runtime serving the API and the built frontend.
FROM python:3.12-slim AS runtime

# Pinned: a floating uv tag would silently change the build.
COPY --from=ghcr.io/astral-sh/uv:0.8.11 /uv /bin/uv

WORKDIR /app

ENV UV_PROJECT_ENVIRONMENT=/app/.venv \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    DB_PATH=/app/db/finally.db \
    STATIC_DIR=/app/static

# Manifests first. README.md is referenced by pyproject and is needed to build
# the project itself. Dependencies install before app source is copied so a
# code change does not invalidate the dependency layer.
COPY backend/pyproject.toml backend/uv.lock backend/README.md ./
RUN uv sync --frozen --no-install-project

COPY backend/app ./app
RUN uv sync --frozen

COPY --from=frontend /build/out ./static

# Volume mount target for the SQLite file. Created here so the app can write
# even when the container runs without a volume attached.
RUN mkdir -p /app/db
VOLUME ["/app/db"]

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
