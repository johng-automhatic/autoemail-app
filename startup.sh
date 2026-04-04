#!/bin/bash
set -e

# Azure App Service Python startup script
# The Oryx build creates antenv, but it can be lost on container restart.
# This ensures packages are always available.

echo "=== Starting Email Flow Manager ==="

# Find or create the virtual environment
if [ -d "antenv" ]; then
    echo "Found antenv in app directory"
    source antenv/bin/activate
elif ls /tmp/*/antenv/bin/activate 1>/dev/null 2>&1; then
    echo "Found antenv in /tmp"
    source /tmp/*/antenv/bin/activate
else
    echo "No antenv found — installing packages..."
    pip install --upgrade pip
    pip install -r requirements.txt
fi

# Start the app (skip migrations for now)
echo "Starting uvicorn..."
exec uvicorn app.main:app --host 0.0.0.0 --port 8000
