#!/usr/bin/env bash

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

cd "$PROJECT_ROOT"

echo
echo "=========================================="
echo "     Starting QuickInsights"
echo "=========================================="
echo

echo "Starting Docker services..."

# The bundled MariaDB is behind the "docker-db" profile (see docker-compose.yml)
# so a plain `docker compose up -d` never starts/restarts it — only include the
# profile when backend/.env is actually configured for it (no METADATA_DATABASE_URL
# override, i.e. the "Docker" option from setup_metadata_db.sh), so a "Frappe"-mode
# setup (reusing an existing MariaDB server) doesn't get a redundant DB container.
ENV_FILE="$PROJECT_ROOT/backend/.env"
if [ -f "$ENV_FILE" ] && grep -q "^METADATA_DATABASE_URL=.\+" "$ENV_FILE"; then
    docker compose up -d
else
    docker compose --profile docker-db up -d
fi

echo
echo "Starting FastAPI..."

exec "$PROJECT_ROOT/start-backend.sh"
