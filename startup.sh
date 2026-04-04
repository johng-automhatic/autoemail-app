#!/bin/bash

# Log startup for debugging
echo "Starting application setup at $(date)"

# Determine the app directory
APP_DIR="/home/site/wwwroot"
echo "App directory: $APP_DIR"

# Set up Python environment if it doesn't exist
if [ ! -d "$HOME/antenv" ]; then
    echo "Creating virtual environment..."
    python -m venv "$HOME/antenv"
    source "$HOME/antenv/bin/activate"
    echo "Installing requirements from $APP_DIR/requirements.txt"
    if [ -f "$APP_DIR/requirements.txt" ]; then
        pip install -r "$APP_DIR/requirements.txt"
    else
        echo "ERROR: requirements.txt not found at $APP_DIR"
    fi
else
    echo "Using existing virtual environment..."
    source "$HOME/antenv/bin/activate"
fi

# Start the application (skip migrations until DB connectivity is confirmed)
echo "Starting application server..."
cd "$APP_DIR"
pip show uvicorn > /dev/null 2>&1 || pip install uvicorn
exec uvicorn app.main:app --host 0.0.0.0 --port 8000
