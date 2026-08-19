#!/usr/bin/env bash

set -e

echo "Stopping QuickInsights backend..."

pkill -f "uvicorn app.main:app" 2>/dev/null || true

echo "Backend stopped."