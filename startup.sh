#!/bin/bash

# Activate virtual environment
source antenv/bin/activate

# Start Gunicorn
gunicorn --bind=0.0.0.0:8000 \
         --timeout 600 \
         --workers 4 \
         --worker-class sync \
         --access-logfile '-' \
         --error-logfile '-' \
         wsgi:app
