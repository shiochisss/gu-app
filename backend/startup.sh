#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
# Migrations are a separate, explicitly approved administration step.
exec gunicorn -k uvicorn.workers.UvicornWorker --bind=0.0.0.0:8000 --workers 1 --timeout 120 --access-logfile /dev/null app.main:app
