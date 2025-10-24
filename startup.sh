#!/usr/bin/env bash
set -euo pipefail

echo "=== Startup script BEGIN $(date) ==="

# Move to application root
cd "$HOME/site/wwwroot"

# Upgrade pip and install dependencies
if [ -f requirements.txt ]; then
    echo "Installing dependencies..."
    python -m pip install --upgrade pip --quiet
    pip install --no-cache-dir -r requirements.txt --quiet
    echo "Dependencies installed successfully"
fi

# Set environment variables
export FLASK_ENV=production
export PYTHONPATH="$HOME/site/wwwroot:$PYTHONPATH"

# Get port from Azure (Azure sets this automatically)
PORT=${PORT:-8000}
echo "Starting application on port $PORT"

# Start Gunicorn with proper logging
echo "Launching Gunicorn..."
exec gunicorn \
    --bind=0.0.0.0:$PORT \
    --workers=3 \
    --threads=2 \
    --timeout=600 \
    --access-logfile - \
    --error-logfile - \
    --log-level info \
    --capture-output \
    "app.app:application"
