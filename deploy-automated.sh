#!/bin/bash

# APRA CPG 234 Compliance Dashboard - Automated Deployment
set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

# Configuration with defaults
STACK_NAME="apra-cpg-234-compliance-dashboard"
REGION=${AWS_DEFAULT_REGION:-"ap-southeast-2"}
TIMESTAMP=$(date +%s)
CONFORMANCE_PACK_BUCKET="mymlpg-conformance-packs-${TIMESTAMP}"
DASHBOARD_BUCKET_NAME="mymlpg-compliance-dashboard-${TIMESTAMP}"
ORGANIZATION_ID=""

print_header() {
    echo -e "${BLUE}================================${NC}"
    echo -e "${BLUE}$1${NC}"
    echo -e "${BLUE}================================${NC}"
}

print_success() {
    echo -e "${GREEN}✓ $1${NC}"
}

print_error() {
    echo -e "${RED}✗ $1${NC}"
}

print_header "APRA CPG 234 Compliance Dashboard - Automated Deployment"

# Check prerequisites
print_header "Checking Prerequisites"

if ! command -v aws &> /dev/null; then
    print_error "AWS CLI is not installed"
    exit 1
fi
print_success "AWS CLI is installed"

if ! aws sts get-caller-identity &> /dev/null; then
    print_error "AWS credentials not configured"
    exit 1
fi
print_success "AWS credentials configured"

ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
print_success "Running in account: $ACCOUNT_ID"

if ! aws organizations describe-organization &> /dev/null; then
    print_error "Not running in organization management account or delegated administrator"
    exit 1
fi

ORGANIZATION_ID=$(aws organizations describe-organization --query Organization.Id --output text)
print_success "Organization ID: $ORGANIZATION_ID"

echo -e "${YELLOW}Configuration:${NC}"
echo "Dashboard Bucket: $DASHBOARD_BUCKET_NAME"
echo "Conformance Pack Bucket: $CONFORMANCE_PACK_BUCKET"
echo "Region: $REGION"

# Upload conformance pack
print_header "Uploading Conformance Pack"

aws s3 mb "s3://$CONFORMANCE_PACK_BUCKET" --region "$REGION" 2>/dev/null || true
aws s3 cp "./Operational-Best-Practices-for-APRA-CPG-234.yaml" \
    "s3://$CONFORMANCE_PACK_BUCKET/conformance-packs/Operational-Best-Practices-for-APRA-CPG-234.yaml"

print_success "Conformance pack uploaded"

# Deploy infrastructure
print_header "Deploying Infrastructure"

aws cloudformation deploy \
    --template-file "./cloudformation/main-template.yaml" \
    --stack-name "$STACK_NAME" \
    --parameter-overrides \
        OrganizationId="$ORGANIZATION_ID" \
        DashboardBucketName="$DASHBOARD_BUCKET_NAME" \
    --capabilities CAPABILITY_IAM CAPABILITY_NAMED_IAM \
    --region "$REGION"

print_success "Infrastructure deployed"

# Deploy conformance packs via StackSet
print_header "Deploying Conformance Packs via StackSet"

STACKSET_NAME="APRA-CPG-234-Compliance-StackSet"

# Get the root OU ID
ROOT_OU=$(aws organizations list-roots --query 'Roots[0].Id' --output text)

OPERATION_ID=$(aws cloudformation create-stack-instances \
    --stack-set-name "$STACKSET_NAME" \
    --deployment-targets OrganizationalUnitIds="$ROOT_OU" \
    --regions "$REGION" \
    --operation-preferences RegionConcurrencyType=PARALLEL,MaxConcurrentPercentage=100 \
    --query 'OperationId' \
    --output text \
    --region "$REGION")

print_success "StackSet deployment initiated: $OPERATION_ID"

# Build and deploy dashboard
print_header "Deploying Dashboard"

mkdir -p dashboard/public

# Use the enhanced dashboard
cp "./dashboard/enhanced-dashboard.html" "dashboard/public/index.html"

aws s3 cp dashboard/public/index.html "s3://$DASHBOARD_BUCKET_NAME/index.html" --content-type "text/html"

print_success "Dashboard deployed"

# Trigger initial data collection
print_header "Triggering Initial Data Collection"

LAMBDA_FUNCTION="APRA-CPG-234-Compliance-data-collector"

aws lambda invoke \
    --function-name "$LAMBDA_FUNCTION" \
    --region "$REGION" \
    /tmp/lambda-response.json

print_success "Initial data collection triggered"

# Display results
print_header "Deployment Complete"

DASHBOARD_URL="http://${DASHBOARD_BUCKET_NAME}.s3-website-${REGION}.amazonaws.com"

echo -e "${GREEN}Dashboard URL: $DASHBOARD_URL${NC}"
echo -e "${YELLOW}Note: It may take 5-10 minutes for conformance packs to deploy and data to populate${NC}"
echo -e "${BLUE}Monitor StackSet deployment: AWS Console > CloudFormation > StackSets${NC}"

# Monitor StackSet deployment
print_header "Monitoring StackSet Deployment"

echo "Checking StackSet operation status..."
while true; do
    STATUS=$(aws cloudformation describe-stack-set-operation \
        --stack-set-name "$STACKSET_NAME" \
        --operation-id "$OPERATION_ID" \
        --query 'StackSetOperation.Status' \
        --output text \
        --region "$REGION" 2>/dev/null || echo "UNKNOWN")
    
    echo "StackSet operation status: $STATUS"
    
    if [[ "$STATUS" == "SUCCEEDED" ]]; then
        print_success "StackSet deployment completed successfully"
        break
    elif [[ "$STATUS" == "FAILED" || "$STATUS" == "STOPPED" ]]; then
        print_error "StackSet deployment failed"
        break
    elif [[ "$STATUS" == "UNKNOWN" ]]; then
        print_error "Unable to check StackSet status"
        break
    fi
    
    sleep 30
done

echo -e "${GREEN}Deployment completed! Access your dashboard at: $DASHBOARD_URL${NC}"
