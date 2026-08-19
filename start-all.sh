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

docker compose up -d

echo
echo "Starting FastAPI..."

exec "$PROJECT_ROOT/start-backend.sh"
