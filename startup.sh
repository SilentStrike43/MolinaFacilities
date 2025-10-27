#!/bin/bash
# startup.sh - Azure App Service startup script

echo "Starting BTManifest application..."

# Install ODBC Driver 18 for SQL Server (if not already installed)
if [ ! -f /opt/microsoft/msodbcsql18/lib64/libmsodbcsql-18.3.so.2.1 ]; then
    echo "Installing ODBC Driver 18 for SQL Server..."
    curl https://packages.microsoft.com/keys/microsoft.asc | apt-key add -
    curl https://packages.microsoft.com/config/debian/11/prod.list > /etc/apt/sources.list.d/mssql-release.list
    apt-get update
    ACCEPT_EULA=Y apt-get install -y msodbcsql18
    apt-get install -y unixodbc-dev
fi

# Start Gunicorn
echo "Starting Gunicorn..."
gunicorn --bind=0.0.0.0:8000 --timeout 600 --workers=4 wsgi:app
