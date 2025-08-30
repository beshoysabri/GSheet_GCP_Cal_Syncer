Google Sheets to Calendar Sync Service v4.0
A production-ready service that synchronizes events from Google Sheets to Google Calendar, deployed on Google Cloud Run with automatic scheduling.
Table of Contents

Overview
Features
Architecture
Prerequisites
Installation
Configuration
Deployment
Usage
API Reference
Troubleshooting
Cost Analysis

Overview
This service automatically syncs calendar events from a Google Sheet to a Google Calendar, handling:

Duplicate prevention through content-based hashing
Recurring events and event series
Validation and error tracking
Incremental updates (only syncs changes)
Automatic scheduling via Cloud Scheduler

Key Benefits

Zero Duplicates: Advanced duplicate detection prevents creating the same event multiple times
Smart Updates: Only syncs events that have changed
Error Recovery: Comprehensive error tracking and retry logic
Cost-Effective: Runs within Google Cloud free tier ($0/month for typical usage)

Features

✅ Smart Sync Logic: Only creates/updates events that have changed
✅ Duplicate Prevention: Content-based hashing ensures no duplicate events
✅ Validation: Comprehensive date/time validation with detailed error reporting
✅ Bulk Operations: Delete events within date ranges for cleanup
✅ Statistics Dashboard: Track sync history and performance
✅ Error Tracking: Failed events are logged with detailed error messages
✅ Rate Limiting: Prevents API quota exhaustion
✅ Database Persistence: SQLite database stored in Google Cloud Storage

Architecture
Google Sheets (Source)
        ↓
    Cloud Run Service (main.py)
        ↓
    Google Calendar (Destination)
        
Database: SQLite in GCS
Scheduler: Cloud Scheduler (configurable frequency)
Components

Flask Web Service (main.py): Core sync logic with REST API
Google Cloud Run: Serverless container hosting
Cloud Scheduler: Automatic sync triggers
Cloud Storage: Database persistence
Service Account: Authentication for Google APIs

Prerequisites
Required Accounts

Google Cloud Platform account with billing enabled
Google Workspace account (for Sheets and Calendar access)

Required Tools

Google Cloud SDK (gcloud CLI)
Python 3.11+ (for local testing)
Git (optional)

Windows Users
Install Google Cloud SDK:
powershell# Download installer
https://dl.google.com/dl/cloudsdk/channels/rapid/GoogleCloudSDKInstaller.exe
Mac/Linux Users
bash# Mac
brew install google-cloud-sdk

# Linux
curl https://sdk.cloud.google.com | bash
Installation
1. Initialize Google Cloud
bash# Login to Google Cloud
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
2. Create Service Account
bash# Create service account
gcloud iam service-accounts create calendar-sync-sa \
  --display-name="Calendar Sync Service Account"

# Get service account email
SERVICE_ACCOUNT_EMAIL="calendar-sync-sa@YOUR_PROJECT_ID.iam.gserviceaccount.com"
3. Share Resources
Share Google Sheet:

Open your Google Sheet
Click Share
Add: calendar-sync-sa@YOUR_PROJECT_ID.iam.gserviceaccount.com
Permission: Viewer

Share Google Calendar:

Open Google Calendar settings
Find your calendar → Settings and sharing
Share with specific people
Add: calendar-sync-sa@YOUR_PROJECT_ID.iam.gserviceaccount.com
Permission: Make changes to events

4. Create Storage Bucket
bashgsutil mb -p YOUR_PROJECT_ID gs://YOUR_PROJECT_ID-calendar-sync
Configuration
Environment Variables
Create a .env file for local testing:
envSHEET_ID=your_sheet_id_here
CALENDAR_ID=primary  # or specific calendar ID
BUCKET_NAME=your-project-id-calendar-sync
Sheet Format
Your Google Sheet must have these columns in the main_import tab:
ColumnDescriptionFormatEvent IDUnique identifierAny stringEvent NameEvent titleTextDescriptionEvent descriptionText/HTMLStart Date/TimeEvent startM/D/YYYY, h:mm:ss AM/PMEnd Date/TimeEvent endM/D/YYYY, h:mm:ss AM/PMColorCalendar color (1-11)NumberEvent TypeEvent categoryTextFocus TimeFocus time flagYes/NoLast ModifiedLast update timeTimestamp
Deployment
Quick Deploy (All Platforms)

Save all files in a directory:

main.py (from above)
requirements.txt
Dockerfile


Deploy to Cloud Run:

bash# Set your configuration
PROJECT_ID="your-project-id"
SHEET_ID="your-sheet-id"
CALENDAR_ID="primary"
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
Windows PowerShell Deploy
powershell# Set variables
$PROJECT_ID = "your-project-id"
$SHEET_ID = "your-sheet-id"
$CALENDAR_ID = "primary"

# Deploy
gcloud run deploy calendar-sync `
  --source . `
  --region us-central1 `
  --allow-unauthenticated `
  --set-env-vars "SHEET_ID=$SHEET_ID,CALENDAR_ID=$CALENDAR_ID,BUCKET_NAME=$PROJECT_ID-calendar-sync"
Setup Automatic Sync
bash# Get service URL
SERVICE_URL=$(gcloud run services describe calendar-sync --region us-central1 --format 'value(status.url)')

# Create scheduler (every 5 minutes)
gcloud scheduler jobs create http calendar-sync-schedule \
  --location us-central1 \
  --schedule "*/5 * * * *" \
  --http-method POST \
  --uri "$SERVICE_URL/sync?source=scheduled"
Usage
Manual Sync
bash# Trigger sync
curl -X POST https://YOUR_SERVICE_URL/sync?source=manual
Windows PowerShell
powershell# Trigger sync
Invoke-RestMethod -Method POST -Uri "https://YOUR_SERVICE_URL/sync?source=manual"

# View stats
Invoke-RestMethod -Uri "https://YOUR_SERVICE_URL/stats" | ConvertTo-Json -Depth 10
Common Operations
Delete Events in Date Range
bash# Delete events from 7 days ago to 14 days future
curl -X POST https://YOUR_SERVICE_URL/delete-range \
  -H "Content-Type: application/json" \
  -d '{"days_before": 7, "days_after": 14}'
Reset All Data
bash# Clear all sync data
curl -X POST https://YOUR_SERVICE_URL/reset

# Force reset (drops tables)
curl -X POST https://YOUR_SERVICE_URL/reset \
  -H "Content-Type: application/json" \
  -d '{"force": true}'
Verify Sync Status
bash# Check which events are in calendar
curl https://YOUR_SERVICE_URL/verify
API Reference
Endpoints
EndpointMethodDescription/GETHealth check/syncPOST/GETTrigger sync/statsGETView statistics/verifyGETVerify calendar events/delete-rangePOSTDelete events in date range/resetPOSTReset sync data/validation-errorsGETView validation errors/duplicatesGETView duplicate Event IDs
Response Examples
Successful Sync:
json{
  "status": "success",
  "created": 45,
  "updated": 12,
  "skipped": 136,
  "errors": 0,
  "total_processed": 193,
  "duration": 15.2
}
Statistics:
json{
  "synced_events": {
    "total": 193,
    "unique_sheet_ids": 193,
    "active": 193
  },
  "recent_syncs": [...],
  "total_failed": 0
}
Troubleshooting
Common Issues
1. Service Unavailable Error
bash# Check logs
gcloud run services logs read calendar-sync --region us-central1 --limit 50

# Common causes:
# - Python syntax errors in main.py
# - Missing dependencies in requirements.txt
# - Import errors
2. No Events Syncing
bash# Verify permissions
# 1. Check Sheet is shared with service account
# 2. Check Calendar is shared with service account
# 3. Check Sheet has correct column headers
3. Duplicate Events
bash# Reset and resync
curl -X POST https://YOUR_SERVICE_URL/reset
curl -X POST https://YOUR_SERVICE_URL/sync
4. Events Not Appearing in Calendar
bash# Check validation errors
curl https://YOUR_SERVICE_URL/validation-errors

# Common issues:
# - Invalid date formats
# - Past events (some calendars reject)
# - Missing required fields
Debug Commands
bash# View detailed logs
gcloud run services logs read calendar-sync \
  --region us-central1 \
  --limit 200 | grep -E "ERROR|WARNING"

# Check service status
gcloud run services describe calendar-sync \
  --region us-central1

# Test database connection
curl https://YOUR_SERVICE_URL/stats
Cost Analysis
Free Tier Coverage

Cloud Run: 2M requests/month free
Cloud Scheduler: 3 jobs free
Cloud Storage: 5GB free
Typical usage: $0/month

Usage Estimates
Sync FrequencyMonthly RequestsMonthly CostEvery minute43,200$0Every 5 minutes8,640$0Every hour720$0
File Structure
calendar-sync/
├── main.py                 # Main application
├── requirements.txt        # Python dependencies
├── Dockerfile             # Container configuration
├── .gcloudignore         # Deployment exclusions
├── deployment-config.txt  # Deployment settings (generated)
└── key.json              # Service account key (do not commit)
Security Notes

Never commit key.json to version control
Use IAM roles instead of keys when possible
Restrict calendar sharing to minimum required permissions
Enable authentication for production use:
bashgcloud run deploy calendar-sync --no-allow-unauthenticated


Support
Logs Location
bash# Cloud Console
https://console.cloud.google.com/run/detail/us-central1/calendar-sync/logs

# CLI
gcloud run services logs tail calendar-sync --region us-central1
Common Log Patterns

Creating new event: - New event being added
Updated: - Existing event updated
Skipped unchanged: - No changes detected
Failed to sync row - Error with specific event

Version History

v4.0 - Current version with duplicate handling for recurring events
Features: Content-based deduplication, validation tracking, bulk operations

License
This project is provided as-is Under MIT License.