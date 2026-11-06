#!/usr/bin/env bash
# Starts the project's PostgreSQL (same settings as docker-compose.yml; used because the compose plugin may be absent).
set -euo pipefail
NAME=gtm-postgres
if docker ps --format '{{.Names}}' | grep -qx "$NAME"; then echo "already running"; exit 0; fi
if docker ps -a --format '{{.Names}}' | grep -qx "$NAME"; then docker start "$NAME" >/dev/null; else
  docker run -d --name "$NAME" -e POSTGRES_USER=gtm -e POSTGRES_PASSWORD=gtm_local_dev_only -e POSTGRES_DB=gtm \
    -p 127.0.0.1:5433:5432 -v gtm_pgdata:/var/lib/postgresql/data postgres:16-alpine >/dev/null
fi
for i in $(seq 1 30); do docker exec "$NAME" pg_isready -U gtm -d gtm >/dev/null 2>&1 && { echo "postgres ready on 127.0.0.1:5433"; exit 0; }; sleep 1; done
echo "postgres did not become ready" >&2; exit 1
