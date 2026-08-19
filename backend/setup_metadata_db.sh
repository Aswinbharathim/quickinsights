#!/usr/bin/env bash
#setup_metadata_db.sh
# Interactive setup for QuickInsights' metadata database (connections, reports,
# schedules, SQL examples, training state) — lets you pick between:
#   1) Docker  — spin up the bundled MariaDB 10.6 container (standalone use,
#                no MariaDB server already available)
#   2) Frappe  — reuse an EXISTING MariaDB server (e.g. the one behind your
#                Frappe bench) by creating a new database + user on it,
#                instead of running a second MariaDB server
#
# Either way, Qdrant is started and .env is updated with the right
# METADATA_DATABASE_URL / ENCRYPTION_KEY — no manual editing needed.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

cd "$SCRIPT_DIR"

ENV_FILE="$SCRIPT_DIR/.env"
COMPOSE_FILE="$PROJECT_ROOT/docker-compose.yml"

if [ ! -f "$ENV_FILE" ]; then
  cp "$SCRIPT_DIR/.env.example" "$ENV_FILE"
  echo "Created $ENV_FILE from .env.example"
fi

PYTHON_BIN="python3"
if [ -x ".venv/bin/python" ]; then
  PYTHON_BIN=".venv/bin/python"
fi

set_env_var() {
  # set_env_var KEY VALUE — updates KEY=VALUE in .env if present, else appends it.
  local key="$1" value="$2" tmp
  if grep -q "^${key}=" "$ENV_FILE"; then
    tmp=$(mktemp)
    awk -v k="$key" -v v="$value" -F= 'BEGIN{OFS="="} $1==k{$0=k"="v} {print}' "$ENV_FILE" > "$tmp"
    mv "$tmp" "$ENV_FILE"
  else
    echo "${key}=${value}" >> "$ENV_FILE"
  fi
}

ensure_encryption_key() {
  local current
  current=$(grep "^ENCRYPTION_KEY=" "$ENV_FILE" | head -1 | cut -d= -f2- || true)
  if [ -z "$current" ]; then
    local key
    key=$("$PYTHON_BIN" -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())" 2>/dev/null || true)
    if [ -z "$key" ]; then
      echo "Note: couldn't generate ENCRYPTION_KEY ('cryptography' isn't installed in $PYTHON_BIN yet)."
      echo "Once you've run 'pip install -r requirements.txt', generate one with:"
      echo "  python3 -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\""
      echo "and set ENCRYPTION_KEY in .env manually."
    else
      set_env_var "ENCRYPTION_KEY" "$key"
      echo "Generated and saved ENCRYPTION_KEY."
    fi
  fi
}

cleanup_conflicting_docker_services() {
  local container_id container_name image ports

  echo
  echo "Checking for Docker port conflicts..."

  # QuickInsights Docker MariaDB uses host port 3307.
  while read -r container_id; do
    [ -z "$container_id" ] && continue

    container_name=$(docker inspect --format '{{.Name}}' "$container_id" | sed 's#^/##')
    image=$(docker inspect --format '{{.Config.Image}}' "$container_id")

    if [[ "$image" == mariadb* ]]; then
      echo "  Found MariaDB container using port 3307:"
      echo "    Container: $container_name"
      echo "    Image:     $image"
      echo "  Stopping and removing it..."

      docker stop "$container_id" >/dev/null
      docker rm "$container_id" >/dev/null

      echo "  Removed conflicting MariaDB container: $container_name"
    else
      ports=$(docker inspect --format '{{json .HostConfig.PortBindings}}' "$container_id")
      echo "ERROR: Port 3307 is occupied by a non-MariaDB Docker container."
      echo "  Container: $container_name"
      echo "  Image:     $image"
      echo "  Ports:     $ports"
      echo
      echo "Please stop/remove that container manually before continuing."
      exit 1
    fi
  done < <(docker ps -aq --filter "publish=3307")

  # Qdrant uses host ports 6333 and 6334.
  while read -r container_id; do
    [ -z "$container_id" ] && continue

    container_name=$(docker inspect --format '{{.Name}}' "$container_id" | sed 's#^/##')
    image=$(docker inspect --format '{{.Config.Image}}' "$container_id")

    if [[ "$image" == qdrant/* ]]; then
      echo "  Found existing Qdrant container using QuickInsights ports:"
      echo "    Container: $container_name"
      echo "    Image:     $image"
      echo "  Stopping and removing it..."

      docker stop "$container_id" >/dev/null
      docker rm "$container_id" >/dev/null

      echo "  Removed conflicting Qdrant container: $container_name"
    else
      echo "ERROR: Qdrant port 6333/6334 is occupied by another Docker container."
      echo "  Container: $container_name"
      echo "  Image:     $image"
      echo
      echo "Please stop/remove that container manually before continuing."
      exit 1
    fi
  done < <(
    {
      docker ps -aq --filter "publish=6333"
      docker ps -aq --filter "publish=6334"
    } | sort -u
  )

  echo "  Docker port check completed."
}

echo "QuickInsights metadata database setup"
echo "======================================"
echo "  1) Docker — run a bundled MariaDB 10.6 container (standalone setup) [default]"
echo "  2) Frappe — reuse an existing MariaDB server (e.g. your Frappe bench's own DB)"
read -rp "Choose [1/2] (Enter = 1, standalone): " MODE
MODE=${MODE:-1}

case "$MODE" in
  1)
    echo
    echo "Preparing Docker services..."
    cleanup_conflicting_docker_services

    echo
    echo "Starting Qdrant + MariaDB via Docker Compose..."
    docker compose -f "$COMPOSE_FILE" up -d qdrant
    docker compose -f "$COMPOSE_FILE" --profile docker-db up -d mariadb

    echo "Waiting for MariaDB to become healthy..."
    for _ in $(seq 1 30); do
      if docker compose -f "$COMPOSE_FILE" exec -T mariadb healthcheck.sh --connect --innodb_initialized 2>/dev/null; then
        echo "MariaDB is healthy."
        break
      fi
      sleep 2
    done

    # Defaults in config.py/.env.example already match the docker-compose
    # service (host localhost, port 3307, db/user/pass quickinsights) — clear
    # any METADATA_DATABASE_URL left over from a previous "Frappe" run.
    set_env_var "METADATA_DATABASE_URL" ""
    ensure_encryption_key

    echo
    echo "Done. Metadata DB: Docker MariaDB on localhost:${METADATA_DB_PORT:-3307}."
    ;;

  2)
    echo
    echo "Starting Qdrant (MariaDB will be your existing server, not Docker)..."
    docker compose -f "$COMPOSE_FILE" up -d qdrant

    echo
    echo "Enter connection details for your EXISTING MariaDB server (e.g. the one"
    echo "behind your Frappe bench — same host/port as your site's site_config.json)."
    read -rp "Host [localhost]: " DB_HOST
    DB_HOST=${DB_HOST:-localhost}
    read -rp "Port [3306]: " DB_PORT
    DB_PORT=${DB_PORT:-3306}
    read -rp "Root (admin) user [root]: " ROOT_USER
    ROOT_USER=${ROOT_USER:-root}
    read -rsp "Root (admin) password: " ROOT_PASSWORD
    echo
    read -rp "New database name for QuickInsights [quickinsights]: " NEW_DB
    NEW_DB=${NEW_DB:-quickinsights}
    read -rp "New database user [quickinsights]: " NEW_USER
    NEW_USER=${NEW_USER:-quickinsights}
    read -rsp "New database user password (blank = auto-generate): " NEW_PASSWORD
    echo
    if [ -z "$NEW_PASSWORD" ]; then
      NEW_PASSWORD=$("$PYTHON_BIN" -c "import secrets; print(secrets.token_urlsafe(18))")
      echo "Generated a password for $NEW_USER."
    fi

    echo "Creating database and user on ${DB_HOST}:${DB_PORT}..."
    "$PYTHON_BIN" - "$DB_HOST" "$DB_PORT" "$ROOT_USER" "$ROOT_PASSWORD" "$NEW_DB" "$NEW_USER" "$NEW_PASSWORD" <<'PYEOF'
import re
import sys

import pymysql

host, port, root_user, root_password, new_db, new_user, new_password = sys.argv[1:8]

if not re.fullmatch(r"[A-Za-z0-9_]+", new_db) or not re.fullmatch(r"[A-Za-z0-9_]+", new_user):
    print("Database/user name must contain only letters, digits, underscore.", file=sys.stderr)
    sys.exit(1)

conn = pymysql.connect(host=host, port=int(port), user=root_user, password=root_password, charset="utf8mb4")
try:
    with conn.cursor() as cur:
        cur.execute(f"CREATE DATABASE IF NOT EXISTS `{new_db}` CHARACTER SET utf8mb4")
        cur.execute("CREATE USER IF NOT EXISTS %s@'%%' IDENTIFIED BY %s", (new_user, new_password))
        cur.execute(f"GRANT ALL PRIVILEGES ON `{new_db}`.* TO %s@'%%'", (new_user,))
        cur.execute("FLUSH PRIVILEGES")
    conn.commit()
    print("Database and user created.")
finally:
    conn.close()
PYEOF

    METADATA_URL="mysql+pymysql://${NEW_USER}:${NEW_PASSWORD}@${DB_HOST}:${DB_PORT}/${NEW_DB}?charset=utf8mb4"
    set_env_var "METADATA_DATABASE_URL" "$METADATA_URL"
    ensure_encryption_key

    echo
    echo "Done. Metadata DB: ${NEW_DB} on ${DB_HOST}:${DB_PORT} (user: ${NEW_USER})."
    echo "Saved as METADATA_DATABASE_URL in .env."
    ;;

  *)
    echo "Invalid choice — enter 1 or 2." >&2
    exit 1
    ;;
esac

echo
echo "Next: activate your venv and install deps if you haven't, then run:"
echo "  uvicorn app.main:app --reload --port 8000"
echo "(the metadata DB schema migrates automatically on startup)"
