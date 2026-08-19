# QuickInsights

QuickInsights is an AI-powered data analysis and reporting application integrated with the Frappe Framework.

Key components:
- FastAPI backend
- Qdrant vector database
- MariaDB metadata database
- Frappe custom application
- Pre-built React frontend bundled inside the Frappe app

The React source/frontend project is not required on the deployment machine because the production build is already included in the Frappe custom app.

---

## Project structure

```
quickinsights/
├── backend/
│   ├── app/
│   ├── migrations/
│   ├── tests/
│   ├── alembic.ini
│   ├── requirements.txt
│   ├── setup_metadata_db.sh
│   └── README.md
├── quickinsights/
│   ├── pyproject.toml
│   ├── license.txt
│   └── quickinsights/
│       ├── public/
│       │   └── dist/
│       │       ├── assets/
│       │       ├── index.html
│       │       ├── quickinsights.js
│       │       ├── quickinsights.css
│       │       ├── icons.svg
│       │       └── favicon.svg
│       ├── quickinsights/
│       └── www/
├── docker-compose.yml
├── setup.sh
├── start-all.sh
├── start-backend.sh
├── stop-backend.sh
└── .gitignore
```

## Architecture (overview)

Browser → Frappe v16 → QuickInsights Frappe App → Built React app → FastAPI backend

FastAPI backend communicates with:
- Metadata MariaDB
- Qdrant vector store
- External user databases (for queries)

## Requirements

- Git
- Python 3.10+ (for the QuickInsights FastAPI backend, `backend/.venv/`)
- Python 3.14 (required by Frappe Framework v16 itself — check with `bench init --python python3.14` if your default `python3` is older)
- Docker
- Docker Compose
- Frappe Framework v16
- A working Frappe bench

Note: The Frappe bench uses its own Python environment (Python 3.14, per Frappe v16's own requirement). The QuickInsights FastAPI backend uses a separate virtual environment (`backend/.venv/`) and only needs Python 3.10+. Do not mix them.

## Setup

1. Clone the repository:

```bash
git clone https://github.com/Aswinbharathim/quickinsights.git
cd quickinsights
```

2. Make scripts executable (once):

```bash
chmod +x setup.sh start-all.sh start-backend.sh stop-backend.sh
chmod +x backend/setup_metadata_db.sh
```

3. Run initial setup:

```bash
./setup.sh
```

The script creates the backend virtual environment under `backend/.venv/`, installs dependencies, configures the metadata DB, and starts Qdrant if requested.

## Metadata database options

During `./setup.sh` you can choose:

1) Docker — starts bundled MariaDB and Qdrant (Docker profile `docker-db`)
2) Frappe — reuse an existing Frappe MariaDB (provide host, port, root/admin credentials, and create a dedicated database/user)

Default Docker MariaDB connection (when using Docker profile):

```
Host: localhost
Port: 3307
Database: quickinsights
User: quickinsights
```

## Docker services

Qdrant:

- HTTP: http://localhost:6333
- gRPC: localhost:6334

Start services:

```bash
# Start all services (detached)
docker compose up -d

# Start services including bundled MariaDB
docker compose --profile docker-db up -d

# Check services
docker compose ps
```

## Important ports

| Service        | Port |
|----------------|------|
| FastAPI        | 8000 |
| Qdrant (HTTP)  | 6333 |
| Qdrant (gRPC)  | 6334 |
| MariaDB (meta) | 3307 |

If port 3307 (or 8000) is already in use, check processes:

```bash
sudo ss -ltnp | grep :3307
sudo ss -ltnp | grep :8000
docker ps --format 'table {{.Names}}\t{{.Ports}}'
```

## Environment configuration

The backend environment file is `backend/.env`. It contains local configuration and secrets — do not commit it to Git.

.gitignore already excludes:

```
backend/.env
backend/.venv/
backend/logs/
backend/mariadb_data/
backend/qdrant_data/
```

## Start the FastAPI backend

```bash
./start-backend.sh
# Backend will be available at: http://localhost:8000
```

Keep this terminal running.

## Start Frappe

In a separate terminal (your Frappe bench):

```bash
cd ~/frappe-bench          # your Frappe bench directory
bench start
```

## Install QuickInsights Frappe app

The Frappe app lives in the `quickinsights/` subdirectory of this repo, not
at the repo root (the root also holds `backend/`, Docker/setup scripts,
etc.). `bench get-app` requires its target to itself be a git repository, so
after cloning, give that subdirectory its own local repo once before
pointing bench at it:

```bash
cd quickinsights/quickinsights   # the nested Frappe app folder
git init -q && git add -A && git commit -q -m "quickinsights app snapshot"
cd ../..
```

Then, from your Frappe bench directory:

```bash
bench get-app --branch main /path/to/quickinsights/quickinsights
bench --site <your-site-name> install-app quickinsights
bench --site <your-site-name> migrate
bench restart
```

Example:

```bash
bench --site hospital.local install-app quickinsights
```

## React frontend

The React build is bundled in `quickinsights/quickinsights/public/dist/`. You do not need to run `npm install` or `npm run build` on the deployment machine.

## Runtime flow

Browser → Frappe → QuickInsights Frappe App → Built React app → FastAPI backend → (MariaDB, Qdrant, external DBs)

## Start everything (quick)

Terminal 1 — QuickInsights backend:

```bash
cd quickinsights
./start-backend.sh
```

Terminal 2 — Frappe:

```bash
cd ~/frappe-bench          # your Frappe bench directory
bench start
```

Or start Docker + backend together:

```bash
./start-all.sh
```

## Stopping

Stop the FastAPI backend:

```bash
./stop-backend.sh
```

Stop Docker services:

```bash
docker compose down

# If using Docker MariaDB profile
docker compose --profile docker-db down
```

## Troubleshooting

- Backend virtual environment not found: `./setup.sh`
- backend/.env not found: `./setup.sh`
- Port 3307 already allocated: `sudo ss -ltnp | grep :3307`
- Qdrant not running: `docker compose ps` or `docker compose up -d qdrant`
- MariaDB not running: `docker compose --profile docker-db up -d mariadb`

## Updating QuickInsights

```bash
cd quickinsights
git pull

# If app maintained via bench:
cd ~/frappe-bench          # your Frappe bench directory
bench update --app quickinsights
bench --site <your-site-name> migrate
bench restart
```

## Production considerations

- Do not commit `backend/.env`
- Use strong database passwords and a secure `ENCRYPTION_KEY`
- Do not expose MariaDB or Qdrant publicly unless required
- Use HTTPS and configure CORS correctly
- Back up the metadata DB and Qdrant data as needed
- Keep API keys outside Git
