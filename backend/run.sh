#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"

# 1. Free port 8000 if occupied
fuser -k 8000/tcp 2>/dev/null || true

# 2. Run uvicorn using the virtual environment python directly
echo "🚀 Starting NSE AI Backend API on http://localhost:8000 ..."
exec ./venv/bin/python -m uvicorn main:app --reload --port 8000 "$@"
