#!/bin/bash

set -e

# Colors
GREEN='\033[0;32m'
BLUE='\033[0;34m'
NC='\033[0m'

AUDIT_ACCOUNT_ID="222634399117"
CONFORMANCE_PACK_BUCKET="mymlpg-conformance-packs-${AUDIT_ACCOUNT_ID}"
REGION=${AWS_DEFAULT_REGION:-"ap-southeast-2"}

echo -e "${BLUE}Deploying Conformance Packs via StackSet...${NC}"

# Upload conformance pack template to audit account bucket (now accessible)
aws s3 cp "./Operational-Best-Practices-for-APRA-CPG-234.yaml" \
    "s3://$CONFORMANCE_PACK_BUCKET/conformance-packs/Operational-Best-Practices-for-APRA-CPG-234.yaml"

echo -e "${GREEN}✓ Conformance pack uploaded${NC}"

# Create StackSet
aws cloudformation create-stack-set \
    --stack-set-name "APRA-CPG-234-Conformance-Pack-StackSet" \
    --description "Deploy APRA CPG 234 conformance pack across organization" \
    --template-body file://./cloudformation/stackset-template.yaml \
    --parameters ParameterKey=AuditAccountId,ParameterValue=$AUDIT_ACCOUNT_ID \
                 ParameterKey=ConformancePackBucket,ParameterValue=$CONFORMANCE_PACK_BUCKET \
    --capabilities CAPABILITY_IAM CAPABILITY_NAMED_IAM \
    --permission-model SERVICE_MANAGED \
    --auto-deployment Enabled=true,RetainStacksOnAccountRemoval=false \
    --region $REGION

echo -e "${GREEN}✓ StackSet created${NC}"

# Get organization root OU
ROOT_OU=$(aws organizations list-roots --query 'Roots[0].Id' --output text)

# Deploy to organization
OPERATION_ID=$(aws cloudformation create-stack-instances \
    --stack-set-name "APRA-CPG-234-Conformance-Pack-StackSet" \
    --deployment-targets OrganizationalUnitIds=$ROOT_OU \
    --regions $REGION \
    --operation-preferences RegionConcurrencyType=PARALLEL,MaxConcurrentPercentage=100 \
    --query 'OperationId' \
    --output text \
    --region $REGION)

echo -e "${GREEN}✓ Deployment initiated: $OPERATION_ID${NC}"
echo -e "${BLUE}Monitor progress: AWS Console > CloudFormation > StackSets${NC}"
