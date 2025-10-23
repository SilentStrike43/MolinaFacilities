#!/usr/bin/env bash
set -euo pipefail

# ------------------------------
# Azure App Service Startup Script
# ------------------------------

# Log file
LOGFILE="$HOME/LogFiles/startup.log"
mkdir -p "$(dirname "$LOGFILE")"
echo "=== startup.sh BEGIN $(date) ===" >> "$LOGFILE"

# Move to wwwroot
cd "$HOME/site/wwwroot"

# ------------------------------
# Virtual Environment Setup
# ------------------------------

if [ -d "./antenv/bin" ]; then
    echo "Activating existing virtualenv..." >> "$LOGFILE"
    source "./antenv/bin/activate"
else
    echo "Creating virtualenv..." >> "$LOGFILE"
    python3 -m venv ./antenv
    source "./antenv/bin/activate"
fi

# ------------------------------
# Install dependencies
# ------------------------------
if [ -f requirements.txt ]; then
    echo "Installing Python dependencies..." >> "$LOGFILE"
    python -m pip install --upgrade pip setuptools wheel >> "$LOGFILE" 2>&1
    pip install --no-cache-dir -r requirements.txt >> "$LOGFILE" 2>&1
else
    echo "No requirements.txt found, skipping pip install" >> "$LOGFILE"
fi

# ------------------------------
# Environment Variables
# ------------------------------
export FLASK_ENV=production
export PYTHONPATH="$HOME/site/wwwroot:$PYTHONPATH"

# ------------------------------
# Determine Port
# ------------------------------
PORT=${PORT:-8000}
echo "Container will listen on port $PORT" >> "$LOGFILE"

# ------------------------------
# Start Gunicorn
# ------------------------------
echo "Launching Gunicorn for app.app:application..." >> "$LOGFILE"
exec gunicorn --bind=0.0.0.0:$PORT --workers=3 --timeout=600 "app.app:application" >> "$LOGFILE" 2>&1

