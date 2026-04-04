# Email Flow Manager

A FastAPI web application for managing bulk email campaigns using Azure Communication Services. Features CSV-based recipient import, HTML templates with merge fields, scheduled sending, and full delivery tracking.

## Architecture

- **FastAPI** — Admin web UI and API
- **Microsoft Entra ID** — User authentication and role-based access
- **Azure Database for PostgreSQL** — Flows, recipients, schedules, and logs
- **Azure Blob Storage** — CSV uploads and email attachments
- **Azure Communication Services** — Outbound email delivery
- **APScheduler** — Background job processor for scheduled sends

## Features

- **Email Flows**: Create campaigns with subject, sender, HTML body template, and send schedule
- **CSV Import**: Upload recipient lists; columns become merge fields (e.g., `{{first_name}}`)
- **Attachments**: Upload shared flow-level attachments or per-row attachment references
- **Merge Fields**: `{{field_name}}` placeholders in subject and body auto-populate from CSV data
- **Scheduled Sending**: Set date/time for email dispatch, or start immediately
- **Status Tracking**: Dashboard with Pending/Sending/Sent/Failed counts
- **Email Log**: Row-level audit trail with ACS operation IDs and error messages
- **Role-Based Access**: Admin, Operator, Viewer roles via Entra ID app roles

## Screens

1. **Dashboard** — Summary counts, next scheduled batch, recent flows
2. **Email Flows** — List/create/edit flows, set subject/from/body/schedule
3. **Flow Detail** — Upload CSV, upload attachments, preview recipients, start/cancel
4. **Email Log** — Filterable delivery log with pagination

## Prerequisites

- Python 3.11+
- Azure Subscription with:
  - App Service (Linux, Python 3.11)
  - Azure Database for PostgreSQL Flexible Server
  - Azure Blob Storage Account
  - Azure Communication Services resource with a verified email domain
  - Entra ID App Registration

## Setup

### 1. Clone and configure

```bash
cp .env.template .env
# Edit .env with your Azure resource details
```

### 2. Entra ID App Registration

1. Go to **Azure Portal → Microsoft Entra ID → App registrations → New registration**
2. Name: `EmailFlowManager`
3. Redirect URI: `https://YOUR_APP.azurewebsites.net/auth/callback`
4. Under **Certificates & secrets**, create a client secret
5. Under **Expose an API**, set Application ID URI: `api://YOUR_CLIENT_ID`
6. Under **App roles**, create:
   - `EmailFlow.Admin` — Manage flows, settings
   - `EmailFlow.Operator` — Upload CSVs, schedule sends
   - `EmailFlow.Viewer` — Read-only access
7. Under **API permissions**, add `openid`, `profile`, `email`
8. Assign roles to users in **Enterprise applications → EmailFlowManager → Users and groups**

### 3. Azure Communication Services

1. Create an ACS resource in Azure Portal
2. Go to **Email → Domains** and add/verify your sender domain
3. Copy the connection string to `.env`

### 4. Database

```bash
# Create the PostgreSQL database
az postgres flexible-server db create \
  --resource-group YOUR_RG \
  --server-name YOUR_SERVER \
  --database-name emailflowdb

# Run migrations
alembic upgrade head
```

### 5. Local Development

```bash
pip install -r requirements.txt
alembic upgrade head
uvicorn app.main:app --reload --port 8000
```

### 6. Deploy to Azure App Service

```bash
# Create App Service
az webapp up --name YOUR_APP_NAME --resource-group YOUR_RG --runtime "PYTHON:3.11"

# Set environment variables
az webapp config appsettings set --name YOUR_APP_NAME --resource-group YOUR_RG --settings \
  DATABASE_URL="postgresql+asyncpg://..." \
  AZURE_TENANT_ID="..." \
  AZURE_CLIENT_ID="..." \
  AZURE_CLIENT_SECRET="..." \
  APP_REDIRECT_URI="https://YOUR_APP.azurewebsites.net/auth/callback" \
  ACS_CONNECTION_STRING="..." \
  AZURE_STORAGE_CONNECTION_STRING="..." \
  SECRET_KEY="$(openssl rand -hex 32)"

# Set startup command
az webapp config set --name YOUR_APP_NAME --resource-group YOUR_RG \
  --startup-file "startup.sh"
```

## CSV Format

The CSV must include a `to_email` column (also accepts `email`, `toemail`, `recipient_email`). All other columns become merge fields.

**Example CSV:**
```csv
to_email,first_name,last_name,company,attachment_ref
john@example.com,John,Doe,Acme Corp,
jane@example.com,Jane,Smith,Widgets Inc,flow-1/attachments/custom-jane.pdf
```

## Email Template Example

```html
<h1>Hello {{first_name}},</h1>
<p>Thank you for your business with {{company}}.</p>
<p>We wanted to reach out regarding your account.</p>
<p>Best regards,<br>The Team</p>
```

## Data Model

| Table | Purpose |
|-------|---------|
| `email_flows` | Flow name, subject, from, body template, schedule, status |
| `email_flow_attachments` | Attachment file metadata and blob path |
| `email_recipient_jobs` | One row per CSV record with merge fields, status tracking |
| `email_send_attempts` | ACS operation ID, provider status, timestamps, errors |
| `csv_imports` | Original filename, validation results, upload metadata |

## Status Flow

```
Draft → Scheduled → Processing → Completed
                  ↘ Cancelled
```

Per-job: `Pending → Scheduled → Sending → Sent | Failed | Cancelled`
