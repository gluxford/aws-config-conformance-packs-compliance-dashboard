#!/bin/bash

# Basic Infrastructure Deployment
set -e

# Colors
GREEN='\033[0;32m'
BLUE='\033[0;34m'
NC='\033[0m'

# Configuration
STACK_NAME="apra-cpg-234-compliance-basic"
REGION=${AWS_DEFAULT_REGION:-"ap-southeast-2"}
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
DASHBOARD_BUCKET_NAME="mymlpg-compliance-dashboard-${ACCOUNT_ID}"

echo -e "${BLUE}Deploying Basic Infrastructure...${NC}"

# Get Organization ID
ORGANIZATION_ID=$(aws organizations describe-organization --query Organization.Id --output text)

# Deploy basic infrastructure
aws cloudformation deploy \
    --template-file "./cloudformation/basic-infrastructure.yaml" \
    --stack-name "$STACK_NAME" \
    --parameter-overrides \
        OrganizationId="$ORGANIZATION_ID" \
        DashboardBucketName="$DASHBOARD_BUCKET_NAME" \
    --capabilities CAPABILITY_IAM \
    --region "$REGION"

echo -e "${GREEN}✓ Basic infrastructure deployed${NC}"

# Deploy dashboard
mkdir -p dashboard/public
cp "./dashboard/enhanced-dashboard.html" "dashboard/public/index.html"
aws s3 cp dashboard/public/index.html "s3://$DASHBOARD_BUCKET_NAME/index.html" --content-type "text/html"

echo -e "${GREEN}✓ Dashboard deployed${NC}"

# Trigger initial data collection
aws lambda invoke \
    --function-name "APRA-CPG-234-Compliance-data-collector" \
    --region "$REGION" \
    /tmp/lambda-response.json

echo -e "${GREEN}✓ Initial data collection triggered${NC}"

DASHBOARD_URL="http://${DASHBOARD_BUCKET_NAME}.s3-website-${REGION}.amazonaws.com"
echo -e "${GREEN}Dashboard URL: $DASHBOARD_URL${NC}"
