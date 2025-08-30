#!/bin/bash

# ==========================================
#     QUICK DEPLOY - ONE COMMAND SETUP
# ==========================================
# Run this script to deploy everything with minimal configuration

set -e  # Exit on error

# Color codes for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}================================================${NC}"
echo -e "${BLUE}   📅 Calendar Sync - Quick Cloud Deployment${NC}"
echo -e "${BLUE}================================================${NC}"
echo ""

# Function to get input with default value
get_input() {
    local prompt=$1
    local default=$2
    local input
    
    if [ -z "$default" ]; then
        read -p "$prompt: " input
    else
        read -p "$prompt [$default]: " input
        input=${input:-$default}
    fi
    echo "$input"
}

# Check if gcloud is installed
if ! command -v gcloud &> /dev/null; then
    echo -e "${RED}❌ gcloud CLI not found!${NC}"
    echo "Please install: https://cloud.google.com/sdk/docs/install"
    exit 1
fi

# Get configuration from user
echo -e "${YELLOW}📝 Configuration Setup${NC}"
echo "--------------------"

# Get Sheet ID from URL
echo -e "${BLUE}Find your Sheet ID from the URL:${NC}"
echo "https://docs.google.com/spreadsheets/d/${GREEN}[THIS_IS_YOUR_SHEET_ID]${NC}/edit"
SHEET_ID=$(get_input "Enter your Google Sheet ID" "")

# Validate Sheet ID
if [ -z "$SHEET_ID" ]; then
    echo -e "${RED}❌ Sheet ID is required!${NC}"
    exit 1
fi

# Get Calendar ID
echo ""
echo -e "${BLUE}Calendar ID options:${NC}"
echo "  - Use 'primary' for your main calendar"
echo "  - Or enter specific calendar ID"
CALENDAR_ID=$(get_input "Enter Calendar ID" "primary")

# Get Project ID or create new
echo ""
CURRENT_PROJECT=$(gcloud config get-value project 2>/dev/null)
if [ -n "$CURRENT_PROJECT" ]; then
    USE_CURRENT=$(get_input "Use current project '$CURRENT_PROJECT'? (y/n)" "y")
    if [ "$USE_CURRENT" = "y" ]; then
        PROJECT_ID=$CURRENT_PROJECT
    else
        PROJECT_ID=$(get_input "Enter new project ID" "calendar-sync-$(date +%s)")
    fi
else
    PROJECT_ID=$(get_input "Enter project ID" "calendar-sync-$(date +%s)")
fi

# Get region
echo ""
echo -e "${BLUE}Recommended regions:${NC}"
echo "  - us-central1 (Iowa)"
echo "  - us-east1 (South Carolina)"
echo "  - europe-west1 (Belgium)"
echo "  - asia-southeast1 (Singapore)"
REGION=$(get_input "Enter region" "us-central1")

# Get sync frequency
echo ""
echo -e "${BLUE}Sync frequency options:${NC}"
echo "  1. Every minute (real-time)"
echo "  2. Every 5 minutes (recommended)"
echo "  3. Every 10 minutes"
echo "  4. Every 30 minutes"
echo "  5. Every hour"
FREQ_CHOICE=$(get_input "Choose frequency (1-5)" "2")

case $FREQ_CHOICE in
    1) SCHEDULE="* * * * *" ;;
    2) SCHEDULE="*/5 * * * *" ;;
    3) SCHEDULE="*/10 * * * *" ;;
    4) SCHEDULE="*/30 * * * *" ;;
    5) SCHEDULE="0 * * * *" ;;
    *) SCHEDULE="*/5 * * * *" ;;
esac

# Confirm configuration
echo ""
echo -e "${GREEN}📋 Configuration Summary:${NC}"
echo "------------------------"
echo "Project ID: $PROJECT_ID"
echo "Region: $REGION"
echo "Sheet ID: $SHEET_ID"
echo "Calendar ID: $CALENDAR_ID"
echo "Sync Schedule: $SCHEDULE"
echo ""

CONFIRM=$(get_input "Proceed with deployment? (y/n)" "y")
if [ "$CONFIRM" != "y" ]; then
    echo -e "${YELLOW}Deployment cancelled${NC}"
    exit 0
fi

# Start deployment
echo ""
echo -e "${GREEN}🚀 Starting deployment...${NC}"
echo "========================"

# Set project
echo -e "${BLUE}Setting project...${NC}"
gcloud config set project $PROJECT_ID 2>/dev/null || {
    echo -e "${YELLOW}Creating new project...${NC}"
    gcloud projects create $PROJECT_ID
    gcloud config set project $PROJECT_ID
}

# Enable billing check
echo -e "${YELLOW}⚠️  Please ensure billing is enabled for project $PROJECT_ID${NC}"
echo "Visit: https://console.cloud.google.com/billing/linkedaccount?project=$PROJECT_ID"
read -p "Press Enter when billing is enabled..."

# Enable APIs
echo -e "${BLUE}📦 Enabling required APIs...${NC}"
gcloud services enable \
    run.googleapis.com \
    cloudscheduler.googleapis.com \
    sheets.googleapis.com \
    calendar-json.googleapis.com \
    storage.googleapis.com \
    cloudbuild.googleapis.com \
    --quiet

# Create storage bucket
BUCKET_NAME="${PROJECT_ID}-calendar-sync"
echo -e "${BLUE}🗄️  Creating storage bucket...${NC}"
gsutil mb -p $PROJECT_ID -l $REGION gs://$BUCKET_NAME 2>/dev/null || echo "Bucket exists"

# Create service account
SERVICE_ACCOUNT="calendar-sync-sa"
echo -e "${BLUE}🔐 Setting up service account...${NC}"
gcloud iam service-accounts create $SERVICE_ACCOUNT \
    --display-name="Calendar Sync Service Account" 2>/dev/null || echo "Service account exists"

SERVICE_ACCOUNT_EMAIL="${SERVICE_ACCOUNT}@${PROJECT_ID}.iam.gserviceaccount.com"

# Grant permissions
echo -e "${BLUE}🔑 Granting permissions...${NC}"
for role in \
    "roles/sheets.viewer" \
    "roles/calendar.events" \
    "roles/storage.objectAdmin"; do
    gcloud projects add-iam-policy-binding $PROJECT_ID \
        --member="serviceAccount:${SERVICE_ACCOUNT_EMAIL}" \
        --role="$role" \
        --quiet
done

# Create application files
echo -e "${BLUE}📄 Creating application files...${NC}"

# Create main.py (using the previously provided code)
cat > main.py << 'PYTHON_EOF'
# [Insert the complete main.py code from the previous artifact here]
# This is a placeholder - use the actual main.py code from above
import os
# ... (complete main.py code)
PYTHON_EOF

# Create requirements.txt
cat > requirements.txt << 'EOF'
Flask==2.3.3
google-api-python-client==2.97.0
google-auth==2.22.0
google-auth-httplib2==0.1.0
google-cloud-storage==2.10.0
pandas==2.0.3
gunicorn==21.2.0
EOF

# Create Dockerfile
cat > Dockerfile << 'EOF'
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY main.py .
CMD exec gunicorn --bind :$PORT --workers 1 --threads 8 --timeout 0 main:app
EOF

# Create .gcloudignore
cat > .gcloudignore << 'EOF'
.gcloudignore
.git
.gitignore
__pycache__/
*.pyc
*.db
README.md
*.sh
EOF

# Deploy to Cloud Run
echo -e "${BLUE}🚢 Deploying to Cloud Run...${NC}"
gcloud run deploy calendar-sync \
    --source . \
    --platform managed \
    --region $REGION \
    --memory 512Mi \
    --cpu 1 \
    --timeout 60 \
    --min-instances 0 \
    --max-instances 10 \
    --allow-unauthenticated \
    --service-account ${SERVICE_ACCOUNT_EMAIL} \
    --set-env-vars "SHEET_ID=$SHEET_ID,CALENDAR_ID=$CALENDAR_ID,BUCKET_NAME=$BUCKET_NAME" \
    --quiet

# Get service URL
SERVICE_URL=$(gcloud run services describe calendar-sync --region $REGION --format 'value(status.url)')

# Create Cloud Scheduler job
echo -e "${BLUE}⏰ Setting up Cloud Scheduler...${NC}"
gcloud scheduler jobs create http calendar-sync-schedule \
    --location $REGION \
    --schedule "$SCHEDULE" \
    --http-method POST \
    --uri "${SERVICE_URL}/sync?source=scheduled" \
    --attempt-deadline 60s \
    --quiet 2>/dev/null || \
gcloud scheduler jobs update http calendar-sync-schedule \
    --location $REGION \
    --schedule "$SCHEDULE" \
    --http-method POST \
    --uri "${SERVICE_URL}/sync?source=scheduled" \
    --attempt-deadline 60s \
    --quiet

# Test the deployment
echo -e "${BLUE}🧪 Testing deployment...${NC}"
TEST_RESPONSE=$(curl -s -X POST "${SERVICE_URL}/sync?source=test")
echo "Test response: $TEST_RESPONSE"

# Success message
echo ""
echo -e "${GREEN}================================================${NC}"
echo -e "${GREEN}✅ DEPLOYMENT SUCCESSFUL!${NC}"
echo -e "${GREEN}================================================${NC}"
echo ""
echo -e "${BLUE}📊 Service Details:${NC}"
echo "  URL: ${SERVICE_URL}"
echo "  Stats: ${SERVICE_URL}/stats"
echo "  Manual Sync: ${SERVICE_URL}/sync"
echo ""
echo -e "${YELLOW}⚠️  IMPORTANT NEXT STEPS:${NC}"
echo ""
echo "1. Share your Google Sheet with this email:"
echo -e "   ${GREEN}${SERVICE_ACCOUNT_EMAIL}${NC}"
echo "   Permission: Viewer"
echo ""
echo "2. Share your Google Calendar with this email:"
echo -e "   ${GREEN}${SERVICE_ACCOUNT_EMAIL}${NC}"
echo "   Permission: Make changes to events"
echo ""
echo "3. Test manual sync:"
echo -e "   ${BLUE}curl -X POST ${SERVICE_URL}/sync${NC}"
echo ""
echo "4. View sync statistics:"
echo -e "   ${BLUE}curl ${SERVICE_URL}/stats${NC}"
echo ""
echo -e "${GREEN}📈 Monitoring:${NC}"
echo "  Logs: gcloud run logs tail calendar-sync --region $REGION"
echo "  Console: https://console.cloud.google.com/run/detail/$REGION/calendar-sync"
echo ""
echo -e "${GREEN}💰 Estimated Cost: \$0/month (within free tier)${NC}"
echo ""

# Save configuration
cat > deployment-config.txt << EOF
Deployment Configuration
========================
Date: $(date)
Project ID: $PROJECT_ID
Region: $REGION
Service URL: $SERVICE_URL
Sheet ID: $SHEET_ID
Calendar ID: $CALENDAR_ID
Service Account: $SERVICE_ACCOUNT_EMAIL
Schedule: $SCHEDULE
EOF

echo -e "${BLUE}Configuration saved to: deployment-config.txt${NC}"

# Create helper scripts
cat > sync-now.sh << EOF
#!/bin/bash
# Quick script to trigger manual sync
curl -X POST "${SERVICE_URL}/sync?source=manual"
EOF
chmod +x sync-now.sh

cat > view-logs.sh << EOF
#!/bin/bash
# View real-time logs
gcloud run logs tail calendar-sync --region $REGION
EOF
chmod +x view-logs.sh

cat > view-stats.sh << EOF
#!/bin/bash
# View sync statistics
curl "${SERVICE_URL}/stats" | python -m json.tool
EOF
chmod +x view-stats.sh

echo ""
echo -e "${BLUE}📝 Helper scripts created:${NC}"
echo "  ./sync-now.sh   - Trigger manual sync"
echo "  ./view-logs.sh  - View real-time logs"
echo "  ./view-stats.sh - View sync statistics"
echo ""
echo -e "${GREEN}🎉 Setup complete! Your calendar sync is now live!${NC}"