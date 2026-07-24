#!/bin/sh
# Container entrypoint: apply pending Alembic migrations, then hand off to
# uvicorn. `set -e` ensures a failed migration aborts the container instead
# of falling through to starting the API against an un-migrated database.
set -e

echo "Running database migrations (alembic upgrade head)..."
/app/.venv/bin/alembic upgrade head

echo "Migrations complete. Starting application..."
exec "$@"
