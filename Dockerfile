# syntax=docker/dockerfile:1

# ---- Stage: builder -------------------------------------------------------
# Materializes the virtualenv (.venv) from the locked dependency set. This
# stage carries the `uv` binary and any build toolchain needed to resolve
# and install wheels; none of it survives into the runtime stage.
FROM python:3.12-slim AS builder

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

# Copy only the dependency manifests first so this layer is cached across
# source-code-only changes.
COPY pyproject.toml uv.lock ./

# --locked: fail instead of silently re-resolving if uv.lock is out of sync
# with pyproject.toml (see AD-009 / dependency supply-chain decision).
# --no-dev: production image never ships pytest/pip-audit/httpx etc.
RUN uv sync --locked --no-dev

# ---- Stage: runtime ---------------------------------------------------
# Clean base image: no `uv`, no pip cache, no compiler toolchain — just the
# Python interpreter, the pre-built virtualenv, and the application code.
FROM python:3.12-slim AS runtime

WORKDIR /app

# Dedicated non-root application user/group.
RUN addgroup --system appuser && adduser --system --ingroup appuser appuser

# Bring in the virtualenv built in the builder stage.
COPY --from=builder /app/.venv /app/.venv

# Application source needed to run the API and its migrations.
COPY app ./app
COPY alembic ./alembic
COPY alembic.ini ./alembic.ini

# Local attachment storage directory (LOCAL_STORAGE_PATH default from
# .env.example). Only this directory and the app code are writable by
# appuser; the rest of the image filesystem stays read-only at runtime.
RUN mkdir -p /app/data/attachments \
    && chown -R appuser:appuser /app

USER appuser

ENV PATH="/app/.venv/bin:$PATH"

EXPOSE 8000

CMD ["/app/.venv/bin/uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
