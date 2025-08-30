# deploy-windows.ps1 - Windows PowerShell Deployment Script
# Run this in PowerShell as Administrator

Write-Host "================================================" -ForegroundColor Blue
Write-Host "   Calendar Sync - Windows Deployment" -ForegroundColor Blue
Write-Host "================================================" -ForegroundColor Blue
Write-Host ""

# Check if gcloud is installed
try {
    gcloud version | Out-Null
} catch {
    Write-Host "ERROR: gcloud CLI not found!" -ForegroundColor Red
    Write-Host "Please install from: https://cloud.google.com/sdk/docs/install" -ForegroundColor Yellow
    Write-Host ""
    Write-Host "Direct download link for Windows:" -ForegroundColor Green
    Write-Host "https://dl.google.com/dl/cloudsdk/channels/rapid/GoogleCloudSDKInstaller.exe" -ForegroundColor Green
    exit 1
}

# Get configuration
Write-Host "Configuration Setup" -ForegroundColor Yellow
Write-Host "-------------------" -ForegroundColor Yellow

$SHEET_ID = Read-Host "Enter your Google Sheet ID"
if ([string]::IsNullOrEmpty($SHEET_ID)) {
    Write-Host "Sheet ID is required!" -ForegroundColor Red
    exit 1
}

$CALENDAR_ID = Read-Host "Enter Calendar ID (press Enter for 'primary')"
if ([string]::IsNullOrEmpty($CALENDAR_ID)) {
    $CALENDAR_ID = "primary"
}

$PROJECT_ID = Read-Host "Enter Google Cloud Project ID"
if ([string]::IsNullOrEmpty($PROJECT_ID)) {
    $PROJECT_ID = "calendar-sync-$(Get-Date -Format 'yyyyMMddHHmmss')"
    Write-Host "Using generated project ID: $PROJECT_ID" -ForegroundColor Green
}

$REGION = Read-Host "Enter region (press Enter for 'us-central1')"
if ([string]::IsNullOrEmpty($REGION)) {
    $REGION = "us-central1"
}

# Confirm configuration
Write-Host ""
Write-Host "Configuration Summary:" -ForegroundColor Green
Write-Host "Project ID: $PROJECT_ID"
Write-Host "Region: $REGION"
Write-Host "Sheet ID: $SHEET_ID"
Write-Host "Calendar ID: $CALENDAR_ID"
Write-Host ""

$confirm = Read-Host "Proceed with deployment? (y/n)"
if ($confirm -ne "y") {
    Write-Host "Deployment cancelled" -ForegroundColor Yellow
    exit 0
}

# Set project
Write-Host "Setting up Google Cloud project..." -ForegroundColor Blue
gcloud config set project $PROJECT_ID

# Enable APIs
Write-Host "Enabling required APIs..." -ForegroundColor Blue
gcloud services enable `
    run.googleapis.com `
    cloudscheduler.googleapis.com `
    sheets.googleapis.com `
    calendar-json.googleapis.com `
    storage.googleapis.com `
    cloudbuild.googleapis.com

# Create storage bucket
$BUCKET_NAME = "${PROJECT_ID}-calendar-sync"
Write-Host "Creating storage bucket..." -ForegroundColor Blue
gsutil mb -p $PROJECT_ID gs://$BUCKET_NAME 2>$null

# Create service account
Write-Host "Setting up service account..." -ForegroundColor Blue
$SERVICE_ACCOUNT = "calendar-sync-sa"
$SERVICE_ACCOUNT_EMAIL = "${SERVICE_ACCOUNT}@${PROJECT_ID}.iam.gserviceaccount.com"

gcloud iam service-accounts create $SERVICE_ACCOUNT `
    --display-name="Calendar Sync Service Account" 2>$null

# Grant permissions
Write-Host "Granting permissions..." -ForegroundColor Blue
$roles = @(
    "roles/sheets.viewer",
    "roles/calendar.events",
    "roles/storage.objectAdmin"
)

foreach ($role in $roles) {
    gcloud projects add-iam-policy-binding $PROJECT_ID `
        --member="serviceAccount:${SERVICE_ACCOUNT_EMAIL}" `
        --role="$role" `
        --quiet
}

# Check if files exist
if (-not (Test-Path "main.py")) {
    Write-Host "ERROR: main.py not found in current directory!" -ForegroundColor Red
    Write-Host "Please ensure main.py is in: $(Get-Location)" -ForegroundColor Yellow
    exit 1
}

# Create requirements.txt if it doesn't exist
if (-not (Test-Path "requirements.txt")) {
    Write-Host "Creating requirements.txt..." -ForegroundColor Blue
    @"
Flask==2.3.3
google-api-python-client==2.97.0
google-auth==2.22.0
google-auth-httplib2==0.1.0
google-cloud-storage==2.10.0
pandas==2.0.3
gunicorn==21.2.0
"@ | Out-File -FilePath "requirements.txt" -Encoding UTF8
}

# Create Dockerfile if it doesn't exist
if (-not (Test-Path "Dockerfile")) {
    Write-Host "Creating Dockerfile..." -ForegroundColor Blue
    @"
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY main.py .
CMD exec gunicorn --bind :`$PORT --workers 1 --threads 8 --timeout 0 main:app
"@ | Out-File -FilePath "Dockerfile" -Encoding UTF8
}

# Create .gcloudignore
if (-not (Test-Path ".gcloudignore")) {
    @"
.gcloudignore
.git
.gitignore
__pycache__/
*.pyc
*.db
*.ps1
*.sh
"@ | Out-File -FilePath ".gcloudignore" -Encoding UTF8
}

# Deploy to Cloud Run
Write-Host "Deploying to Cloud Run (this may take 2-3 minutes)..." -ForegroundColor Blue
gcloud run deploy calendar-sync `
    --source . `
    --platform managed `
    --region $REGION `
    --memory 512Mi `
    --cpu 1 `
    --timeout 60 `
    --min-instances 0 `
    --max-instances 10 `
    --allow-unauthenticated `
    --service-account $SERVICE_ACCOUNT_EMAIL `
    --set-env-vars "SHEET_ID=$SHEET_ID,CALENDAR_ID=$CALENDAR_ID,BUCKET_NAME=$BUCKET_NAME"

# Get service URL
$SERVICE_URL = gcloud run services describe calendar-sync --region $REGION --format "value(status.url)"

# Create Cloud Scheduler job
Write-Host "Setting up automatic sync schedule..." -ForegroundColor Blue
gcloud scheduler jobs create http calendar-sync-schedule `
    --location $REGION `
    --schedule "*/5 * * * *" `
    --http-method POST `
    --uri "${SERVICE_URL}/sync?source=scheduled" `
    --attempt-deadline 60s 2>$null

# Success message
Write-Host ""
Write-Host "================================================" -ForegroundColor Green
Write-Host "DEPLOYMENT SUCCESSFUL!" -ForegroundColor Green
Write-Host "================================================" -ForegroundColor Green
Write-Host ""
Write-Host "Service URL: $SERVICE_URL" -ForegroundColor Cyan
Write-Host "Stats: ${SERVICE_URL}/stats" -ForegroundColor Cyan
Write-Host "Manual Sync: ${SERVICE_URL}/sync" -ForegroundColor Cyan
Write-Host ""
Write-Host "IMPORTANT NEXT STEPS:" -ForegroundColor Yellow
Write-Host ""
Write-Host "1. Share your Google Sheet with:" -ForegroundColor White
Write-Host "   $SERVICE_ACCOUNT_EMAIL" -ForegroundColor Green
Write-Host "   Permission: Viewer" -ForegroundColor White
Write-Host ""
Write-Host "2. Share your Google Calendar with:" -ForegroundColor White
Write-Host "   $SERVICE_ACCOUNT_EMAIL" -ForegroundColor Green
Write-Host "   Permission: Make changes to events" -ForegroundColor White
Write-Host ""

# Create helper batch files
@"
@echo off
curl -X POST ${SERVICE_URL}/sync?source=manual
pause
"@ | Out-File -FilePath "sync-now.bat" -Encoding ASCII

@"
@echo off
gcloud run logs tail calendar-sync --region $REGION
"@ | Out-File -FilePath "view-logs.bat" -Encoding ASCII

@"
@echo off
curl ${SERVICE_URL}/stats
pause
"@ | Out-File -FilePath "view-stats.bat" -Encoding ASCII

Write-Host "Helper scripts created:" -ForegroundColor Blue
Write-Host "  sync-now.bat   - Trigger manual sync" -ForegroundColor White
Write-Host "  view-logs.bat  - View real-time logs" -ForegroundColor White
Write-Host "  view-stats.bat - View sync statistics" -ForegroundColor White
Write-Host ""

# Save configuration
@"
Deployment Configuration
========================
Date: $(Get-Date)
Project ID: $PROJECT_ID
Region: $REGION
Service URL: $SERVICE_URL
Sheet ID: $SHEET_ID
Calendar ID: $CALENDAR_ID
Service Account: $SERVICE_ACCOUNT_EMAIL
"@ | Out-File -FilePath "deployment-config.txt" -Encoding UTF8

Write-Host "Configuration saved to: deployment-config.txt" -ForegroundColor Green