#!/usr/bin/env bash

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$PROJECT_ROOT/backend"
VENV_DIR="$BACKEND_DIR/.venv"

if [ ! -d "$VENV_DIR" ]; then
    echo "ERROR: backend/.venv not found."
    echo "Run ./setup.sh first."
    exit 1
fi

if [ ! -f "$BACKEND_DIR/.env" ]; then
    echo "ERROR: backend/.env not found."
    echo "Run ./setup.sh first."
    exit 1
fi

cd "$BACKEND_DIR"

echo
echo "=========================================="
echo "     QuickInsights FastAPI"
echo "=========================================="
echo
echo "Backend: $BACKEND_DIR"
echo "URL:     http://localhost:8000"
echo

exec "$VENV_DIR/bin/uvicorn" \
    app.main:app \
    --host 0.0.0.0 \
    --port 8000
