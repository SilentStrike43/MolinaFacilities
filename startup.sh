#!/usr/bin/env bash
set -euo pipefail

LOGFILE="$HOME/LogFiles/startup.log"
mkdir -p "$(dirname "$LOGFILE")"
echo "=== startup.sh BEGIN $(date) ===" >> "$LOGFILE"

cd "$HOME/site/wwwroot"

# Activate virtualenv or create one
if [ -d "./antenv/bin" ]; then
  source "./antenv/bin/activate" || true
else
  python3 -m venv ./antenv || true
  source "./antenv/bin/activate" || true
fi

# Install dependencies
if [ -f requirements.txt ]; then
  python -m pip install --upgrade pip setuptools wheel >> "$LOGFILE" 2>&1 || true
  pip install --no-cache-dir -r requirements.txt >> "$LOGFILE" 2>&1 || true
fi

export FLASK_ENV=production
export PYTHONPATH="$HOME/site/wwwroot:$PYTHONPATH"

PORT=${PORT:-8000}
echo "Launching Gunicorn on 0.0.0.0:$PORT (module: app.app:application)" >> "$LOGFILE"

exec gunicorn --bind=0.0.0.0:$PORT --workers=3 --timeout=600 "app.app:application" >> "$LOGFILE" 2>&1
