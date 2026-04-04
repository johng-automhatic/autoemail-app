#!/bin/bash
# Azure App Service startup command for FastAPI
# Set this as the Startup Command in Azure App Service → Configuration → General Settings

# Run database migrations
python -m alembic upgrade head

# Start the FastAPI app with Uvicorn
uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 2
