#!/usr/bin/env bash
# Convenience script: creates a venv (first run only), installs deps, starts the server.
set -e
cd "$(dirname "$0")"

if [ ! -d ".venv" ]; then
  python3 -m venv .venv
fi
source .venv/bin/activate
pip install -q -r requirements.txt

cd backend
echo "Starting server at http://localhost:8000  (Ctrl+C to stop)"
uvicorn main:app --host 0.0.0.0 --port 8000
