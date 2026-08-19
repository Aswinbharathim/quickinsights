#!/usr/bin/env bash

# =========================================================
# QuickInsights - Master Setup
#
# Responsibilities:
#   1. Check prerequisites
#   2. Create backend Python virtual environment
#   3. Install backend dependencies
#   4. Run metadata database setup
#   5. Validate the environment
#
# Metadata DB / Qdrant setup is delegated to:
#   backend/setup_metadata_db.sh
# =========================================================

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$PROJECT_ROOT/backend"
VENV_DIR="$BACKEND_DIR/.venv"
REQUIREMENTS_FILE="$BACKEND_DIR/requirements.txt"
METADATA_SETUP="$BACKEND_DIR/setup_metadata_db.sh"

cd "$PROJECT_ROOT"


# ---------------------------------------------------------
# Helpers
# ---------------------------------------------------------

command_exists() {
    command -v "$1" >/dev/null 2>&1
}


fail() {
    echo
    echo "ERROR: $1"
    exit 1
}


# ---------------------------------------------------------
# Header
# ---------------------------------------------------------

echo
echo "=========================================="
echo "       QuickInsights Setup"
echo "=========================================="
echo


# ---------------------------------------------------------
# 1. Check prerequisites
# ---------------------------------------------------------

echo "[1/5] Checking prerequisites..."

command_exists python3 || fail "python3 is not installed."
command_exists docker || fail "Docker is not installed."

echo "  Python: $(python3 --version)"
echo "  Docker: $(docker --version)"


# ---------------------------------------------------------
# 2. Check project files
# ---------------------------------------------------------

echo
echo "[2/5] Checking project files..."

[ -d "$BACKEND_DIR" ] \
    || fail "backend directory not found."

[ -f "$REQUIREMENTS_FILE" ] \
    || fail "backend/requirements.txt not found."

[ -f "$METADATA_SETUP" ] \
    || fail "backend/setup_metadata_db.sh not found."

[ -f "$PROJECT_ROOT/docker-compose.yml" ] \
    || fail "Root docker-compose.yml not found."

echo "  Backend: OK"
echo "  Requirements: OK"
echo "  Metadata setup: OK"
echo "  Docker Compose: OK"


# ---------------------------------------------------------
# 3. Create Python virtual environment
# ---------------------------------------------------------

echo
echo "[3/5] Setting up backend virtual environment..."

if [ ! -d "$VENV_DIR" ]; then
    echo "  Creating backend/.venv..."
    python3 -m venv "$VENV_DIR"
else
    echo "  backend/.venv already exists."
fi

PYTHON_BIN="$VENV_DIR/bin/python"
PIP_BIN="$VENV_DIR/bin/pip"

[ -x "$PYTHON_BIN" ] \
    || fail "Python virtual environment was not created correctly."

echo "  Python: $("$PYTHON_BIN" --version)"

echo
echo "  Upgrading pip..."
"$PYTHON_BIN" -m pip install --upgrade pip

echo
echo "  Installing backend dependencies..."
"$PIP_BIN" install -r "$REQUIREMENTS_FILE"


# ---------------------------------------------------------
# 4. Metadata database + Qdrant
# ---------------------------------------------------------

echo
echo "[4/5] Setting up metadata database and Qdrant..."

chmod +x "$METADATA_SETUP"

"$METADATA_SETUP"


# ---------------------------------------------------------
# 5. Final validation
# ---------------------------------------------------------

echo
echo "[5/5] Running final checks..."

# Check Python imports
"$PYTHON_BIN" -c "import fastapi; print('  FastAPI: OK')"

# Check Qdrant container
if docker compose -f "$PROJECT_ROOT/docker-compose.yml" ps --status running 2>/dev/null | grep -q qdrant; then
    echo "  Qdrant: running"
else
    echo "  WARNING: Qdrant container is not running."
fi

echo
echo "=========================================="
echo "       Setup completed successfully"
cd "$PROJECT_ROOT"
echo "=========================================="

echo
echo "Backend:"
echo "  cd '$PROJECT_ROOT' "
echo "  ./start-backend.sh"
echo
echo "Frappe:"
echo "  cd <your-frappe-bench>"
echo "  bench start"
echo
