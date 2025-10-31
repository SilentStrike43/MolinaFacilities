#!/bin/bash

source /tmp/8de18818102b142/antenv/bin/activate
cd /tmp/8de18818102b142

# Call the create_app factory directly
exec gunicorn \
    --bind=0.0.0.0:8000 \
    --timeout 600 \
    --workers 4 \
    --access-logfile - \
    --error-logfile - \
    "app.app:create_app()"
