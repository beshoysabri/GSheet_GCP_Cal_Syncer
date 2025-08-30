# Google Sheets to Calendar Sync Service v4.0

A production-ready service that synchronizes events from Google Sheets to Google Calendar, deployed on Google Cloud Run with automatic scheduling.

## Table of Contents
- [Overview](#overview)
- [Features](#features)
- [Architecture](#architecture)
- [Prerequisites](#prerequisites)
- [Installation](#installation)
- [Configuration](#configuration)
- [Deployment](#deployment)
- [Usage](#usage)
- [API Reference](#api-reference)
- [Troubleshooting](#troubleshooting)
- [Cost Analysis](#cost-analysis)
- [License](#license)

## Overview

This service automatically syncs calendar events from a Google Sheet to a Google Calendar, handling:
- Duplicate prevention through content-based hashing
- Recurring events and event series
- Validation and error tracking
- Incremental updates (only syncs changes)
- Automatic scheduling via Cloud Scheduler

### Key Benefits
- **Zero Duplicates**: Advanced duplicate detection prevents creating the same event multiple times
- **Smart Updates**: Only syncs events that have changed
- **Error Recovery**: Comprehensive error tracking and retry logic
- **Cost-Effective**: Runs within Google Cloud free tier ($0/month for typical usage)

## Features

- ✅ **Smart Sync Logic**: Only creates/updates events that have changed
- ✅ **Duplicate Prevention**: Content-based hashing ensures no duplicate events
- ✅ **Validation**: Comprehensive date/time validation with detailed error reporting
- ✅ **Bulk Operations**: Delete events within date ranges for cleanup
- ✅ **Statistics Dashboard**: Track sync history and performance
- ✅ **Error Tracking**: Failed events are logged with detailed error messages
- ✅ **Rate Limiting**: Prevents API quota exhaustion
- ✅ **Database Persistence**: SQLite database stored in Google Cloud Storage

## Architecture

```
Google Sheets (Source)
        ↓
    Cloud Run Service (main.py)
        ↓
    Google Calendar (Destination)
        
Database: SQLite in GCS
Scheduler: Cloud Scheduler (configurable frequency)
```

### Components

1. **Flask Web Service** (`main.py`): Core sync logic with REST API
2. **Google Cloud Run**: Serverless container hosting
3. **Cloud Scheduler**: Automatic sync triggers
4. **Cloud Storage**: Database persistence
5. **Service Account**: Authentication for Google APIs

## Prerequisites

### Required Accounts
- Google Cloud Platform account with billing enabled
- Google Workspace account (for Sheets and Calendar access)

### Required Tools
- Google Cloud SDK (`gcloud` CLI)
- Python 3.11+ (for local testing)
- Git (optional)

### Windows Users
Install Google Cloud SDK:
```powershell
# Download installer
https://dl.google.com/dl/cloudsdk/channels/rapid/GoogleCloudSDKInstaller.exe
```

### Mac/Linux Users
```bash
# Mac
brew install google-cloud-sdk

# Linux
curl https://sdk.cloud.google.com | bash
```

## Installation

### 1. Initialize Google Cloud

```bash
# Login to Google Cloud
gcloud auth login

# Create or select project
gcloud config set project YOUR_PROJECT_ID

# Enable required APIs
gcloud services enable \
  run.googleapis.com \
  cloudscheduler.googleapis.com \
  sheets.googleapis.com \
  calendar-json.googleapis.com \
  storage.googleapis.com \
  cloudbuild.googleapis.com
```

### 2. Create Service Account

```bash
# Create service account
gcloud iam service-accounts create calendar-sync-sa \
  --display-name="Calendar Sync Service Account"

# Get service account email
SERVICE_ACCOUNT_EMAIL="calendar-sync-sa@YOUR_PROJECT_ID.iam.gserviceaccount.com"
```

### 3. Share Resources

**Share Google Sheet:**
1. Open your Google Sheet
2. Click Share
3. Add: `calendar-sync-sa@YOUR_PROJECT_ID.iam.gserviceaccount.com`
4. Permission: Viewer

**Share Google Calendar:**
1. Open Google Calendar settings
2. Find your calendar → Settings and sharing
3. Share with specific people
4. Add: `calendar-sync-sa@YOUR_PROJECT_ID.iam.gserviceaccount.com`
5. Permission: Make changes to events

### 4. Create Storage Bucket

```bash
gsutil mb -p YOUR_PROJECT_ID gs://YOUR_PROJECT_ID-calendar-sync
```

## Configuration

### Environment Variables

Create a `.env` file for local testing:

```env
SHEET_ID=your_sheet_id_here
CALENDAR_ID=primary  # or specific calendar ID
BUCKET_NAME=your-project-id-calendar-sync
```

### Sheet Format

Your Google Sheet must have these columns in the `main_import` tab:

| Column | Description | Format | Example |
|--------|-------------|---------|---------|
| Event ID | Unique identifier | Any string | 48086tked@google.com |
| Event Name | Event title | Text | Team Meeting |
| Description | Event description | Text/HTML | Project sync discussion |
| Start Date/Time | Event start | M/D/YYYY, h:mm:ss AM/PM | 8/30/2025, 2:00:00 PM |
| End Date/Time | Event end | M/D/YYYY, h:mm:ss AM/PM | 8/30/2025, 3:00:00 PM |
| Color | Calendar color (1-11) | Number | 4 |
| Event Type | Event category | Text | Focus Time |
| Focus Time | Focus time flag | Yes/No | Yes |
| Last Modified | Last update time | Timestamp | 2025-08-30 14:00:00 |

### Required Files

**requirements.txt:**
```txt
Flask==2.3.3
google-api-python-client==2.97.0
google-auth==2.22.0
google-auth-httplib2==0.1.0
google-cloud-storage==2.10.0
gunicorn==21.2.0
```

**Dockerfile:**
```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY main.py .
CMD exec gunicorn --bind :$PORT --workers 1 --threads 8 --timeout 0 main:app
```

**.gcloudignore:**
```
.gcloudignore
.git
.gitignore
__pycache__/
*.pyc
*.db
README.md
*.sh
*.bat
key.json
.env
```

## Deployment

### Quick Deploy (All Platforms)

1. **Save all files** in a directory:
   - `main.py` (from the project)
   - `requirements.txt`
   - `Dockerfile`
   - `.gcloudignore`

2. **Deploy to Cloud Run:**

```bash
# Set your configuration
PROJECT_ID="your-project-id"
SHEET_ID="your-sheet-id"
CALENDAR_ID="primary"  # or specific calendar ID
REGION="us-central1"

# Deploy
gcloud run deploy calendar-sync \
  --source . \
  --region $REGION \
  --memory 512Mi \
  --timeout 60 \
  --allow-unauthenticated \
  --service-account calendar-sync-sa@$PROJECT_ID.iam.gserviceaccount.com \
  --set-env-vars "SHEET_ID=$SHEET_ID,CALENDAR_ID=$CALENDAR_ID,BUCKET_NAME=$PROJECT_ID-calendar-sync"
```

### Windows PowerShell Deploy

```powershell
# Set variables
$PROJECT_ID = "your-project-id"
$SHEET_ID = "your-sheet-id"
$CALENDAR_ID = "primary"

# Deploy
gcloud run deploy calendar-sync `
  --source . `
  --region us-central1 `
  --allow-unauthenticated `
  --service-account calendar-sync-sa@$PROJECT_ID.iam.gserviceaccount.com `
  --set-env-vars "SHEET_ID=$SHEET_ID,CALENDAR_ID=$CALENDAR_ID,BUCKET_NAME=$PROJECT_ID-calendar-sync"
```

### Setup Automatic Sync

```bash
# Get service URL
SERVICE_URL=$(gcloud run services describe calendar-sync --region us-central1 --format 'value(status.url)')

# Create scheduler (every 5 minutes)
gcloud scheduler jobs create http calendar-sync-schedule \
  --location us-central1 \
  --schedule "*/5 * * * *" \
  --http-method POST \
  --uri "$SERVICE_URL/sync?source=scheduled"
```

**Schedule Options:**
- `* * * * *` - Every minute
- `*/5 * * * *` - Every 5 minutes
- `*/10 * * * *` - Every 10 minutes
- `0 * * * *` - Every hour
- `0 */6 * * *` - Every 6 hours
- `0 9 * * *` - Daily at 9 AM

## Usage

### Manual Sync

```bash
# Trigger sync
curl -X POST https://YOUR_SERVICE_URL/sync?source=manual
```

### Windows PowerShell

```powershell
# Trigger sync
Invoke-RestMethod -Method POST -Uri "https://YOUR_SERVICE_URL/sync?source=manual"

# View stats
Invoke-RestMethod -Uri "https://YOUR_SERVICE_URL/stats" | ConvertTo-Json -Depth 10

# Verify sync
Invoke-RestMethod -Uri "https://YOUR_SERVICE_URL/verify" | ConvertTo-Json
```

### Common Operations

#### Delete Events in Date Range
```bash
# Delete events from 7 days ago to 14 days future
curl -X POST https://YOUR_SERVICE_URL/delete-range \
  -H "Content-Type: application/json" \
  -d '{"days_before": 7, "days_after": 14}'
```

PowerShell:
```powershell
Invoke-RestMethod -Method POST -Uri "https://YOUR_SERVICE_URL/delete-range" `
  -Body '{"days_before": 7, "days_after": 14}' `
  -ContentType "application/json"
```

#### Reset All Data
```bash
# Clear all sync data
curl -X POST https://YOUR_SERVICE_URL/reset

# Force reset (drops tables)
curl -X POST https://YOUR_SERVICE_URL/reset \
  -H "Content-Type: application/json" \
  -d '{"force": true}'
```

#### Verify Sync Status
```bash
# Check which events are in calendar
curl https://YOUR_SERVICE_URL/verify
```

## API Reference

### Endpoints

| Endpoint | Method | Description | Parameters |
|----------|--------|-------------|------------|
| `/` | GET | Health check | None |
| `/sync` | POST/GET | Trigger sync | `source`: manual/scheduled |
| `/stats` | GET | View statistics | None |
| `/verify` | GET | Verify calendar events | None |
| `/delete-range` | POST | Delete events in date range | `days_before`, `days_after` |
| `/reset` | POST | Reset sync data | `force`: true/false |
| `/validation-errors` | GET | View validation errors | None |
| `/duplicates` | GET | View duplicate Event IDs | None |

### Response Examples

**Successful Sync:**
```json
{
  "status": "success",
  "created": 45,
  "updated": 12,
  "skipped": 136,
  "errors": 0,
  "total_processed": 193,
  "invalid_events": 0,
  "duplicate_event_ids": 0,
  "duration": 15.2,
  "trigger_source": "manual"
}
```

**Statistics:**
```json
{
  "synced_events": {
    "total": 193,
    "unique_sheet_ids": 193,
    "active": 193
  },
  "duplicate_event_ids": {
    "unique_ids_with_duplicates": 0,
    "total_occurrences": 0
  },
  "recent_syncs": [
    ["2025-08-30 13:29:46", 0, 123, 70, 0, 76.88, "manual", 193]
  ],
  "total_failed": 0,
  "recent_failures": [],
  "total_validation_errors": 0,
  "recent_validation_errors": []
}
```

**Verify Response:**
```json
{
  "total_in_database": 193,
  "verified": 193,
  "missing": 0,
  "missing_events": [],
  "verified_sample": [
    {
      "name": "Team Meeting",
      "unique_id": "48086tked@google.com_2025-08-30T14:00:00",
      "calendar_id": "abc123def456",
      "start_time": "2025-08-30T14:00:00"
    }
  ]
}
```

## Troubleshooting

### Common Issues

#### 1. Service Unavailable Error
```bash
# Check logs
gcloud run services logs read calendar-sync --region us-central1 --limit 50

# Common causes:
# - Python syntax errors in main.py
# - Missing dependencies in requirements.txt
# - Import errors
```

#### 2. No Events Syncing
```bash
# Verify permissions
# 1. Check Sheet is shared with service account
# 2. Check Calendar is shared with service account
# 3. Check Sheet has correct column headers
# 4. Check Sheet tab name is "main_import"
```

#### 3. Duplicate Events
```bash
# Reset and resync
curl -X POST https://YOUR_SERVICE_URL/reset
curl -X POST https://YOUR_SERVICE_URL/sync
```

#### 4. Events Not Appearing in Calendar
```bash
# Check validation errors
curl https://YOUR_SERVICE_URL/validation-errors

# Common issues:
# - Invalid date formats
# - Past events (some calendars reject)
# - Missing required fields
# - End time before start time
```

#### 5. Only Some Events Syncing
```bash
# Check for duplicates
curl https://YOUR_SERVICE_URL/duplicates

# Check validation errors
curl https://YOUR_SERVICE_URL/validation-errors

# Verify sync status
curl https://YOUR_SERVICE_URL/verify
```

### Debug Commands

```bash
# View detailed logs
gcloud run services logs read calendar-sync \
  --region us-central1 \
  --limit 200 | grep -E "ERROR|WARNING"

# Check service status
gcloud run services describe calendar-sync \
  --region us-central1

# Test database connection
curl https://YOUR_SERVICE_URL/stats

# Monitor real-time logs
gcloud run services logs tail calendar-sync --region us-central1
```

### Common Log Patterns
- `Creating new event:` - New event being added
- `Updated:` - Existing event updated
- `Skipped unchanged:` - No changes detected
- `Linked to existing:` - Found matching event in calendar
- `Failed to sync row` - Error with specific event
- `Event not in calendar, will recreate` - Event was deleted from calendar

## Cost Analysis

### Free Tier Coverage
- **Cloud Run**: 2M requests/month free
- **Cloud Scheduler**: 3 jobs free
- **Cloud Storage**: 5GB free
- **Typical usage**: $0/month

### Usage Estimates
| Sync Frequency | Monthly Requests | Monthly Cost |
|---------------|------------------|--------------|
| Every minute | 43,200 | $0 |
| Every 5 minutes | 8,640 | $0 |
| Every 15 minutes | 2,880 | $0 |
| Every hour | 720 | $0 |

### Cost Optimization Tips
1. Keep sync frequency ≤ every 5 minutes
2. Use minimum memory (512Mi)
3. Set min-instances to 0
4. Clean old sync logs periodically

## File Structure

```
calendar-sync/
├── main.py                 # Main application (v4.0)
├── requirements.txt        # Python dependencies
├── Dockerfile             # Container configuration
├── .gcloudignore         # Deployment exclusions
├── README.md             # This file
├── LICENSE               # MIT License
├── deployment-config.txt  # Deployment settings (generated)
└── key.json              # Service account key (do not commit)
```

## Security Notes

1. **Never commit** `key.json` to version control
2. **Use IAM roles** instead of keys when possible
3. **Restrict calendar sharing** to minimum required permissions
4. **Enable authentication** for production use:
   ```bash
   gcloud run deploy calendar-sync --no-allow-unauthenticated
   ```
5. **Rotate service account keys** regularly
6. **Monitor access logs** for unusual activity

## Support

### Logs Location
```bash
# Cloud Console
https://console.cloud.google.com/run/detail/us-central1/calendar-sync/logs

# CLI
gcloud run services logs tail calendar-sync --region us-central1
```

### Monitoring Dashboard
```
https://console.cloud.google.com/run/detail/us-central1/calendar-sync/metrics
```

## Version History

- **v4.0** (Current) - Duplicate handling for recurring events
  - Content-based deduplication
  - Validation tracking
  - Bulk operations
  - Comprehensive error reporting
  
- **v3.0** - Basic sync with database persistence
- **v2.0** - Added Cloud Storage support
- **v1.0** - Initial release

## Contributing

This project is open source under the MIT License. Contributions are welcome!

1. Fork the repository
2. Create your feature branch
3. Commit your changes
4. Push to the branch
5. Create a Pull Request

## License

MIT License

Copyright (c) 2025 Beshoy Sabri

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
