#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"

# 1. Free port 5500 if occupied
fuser -k 5500/tcp 2>/dev/null || true

# 2. Start HTTP server
echo "🌐 Serving NSE AI Frontend on http://localhost:5500 ..."
exec python3 -m http.server 5500
