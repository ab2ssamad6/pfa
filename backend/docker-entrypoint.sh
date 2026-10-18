#!/bin/sh
# Runs Alembic migrations when RUN_MIGRATIONS=1 (the api service), then the given command.
set -e
if [ "${RUN_MIGRATIONS:-0}" = "1" ]; then
  echo "[entrypoint] applying database migrations"
  i=0
  until alembic upgrade head; do
    i=$((i + 1))
    if [ "$i" -ge 15 ]; then
      echo "[entrypoint] ERROR: migrations failed after $i attempts - is PostgreSQL reachable at DATABASE_URL?" >&2
      exit 1
    fi
    echo "[entrypoint] database not ready, retrying in 2s ($i/15)"
    sleep 2
  done
fi
exec "$@"
