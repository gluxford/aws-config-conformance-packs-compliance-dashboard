# APRA CPG 234 Compliance Dashboard

A comprehensive AWS Config-based compliance dashboard solution for monitoring APRA CPG 234 conformance across your AWS Organization.

## Overview

This solution provides:
- **Automated Conformance Pack Deployment** across all organization accounts via CloudFormation StackSets
- **Real-time Compliance Dashboard** hosted as a static website on S3
- **Visual Analytics** with donut charts and bar graphs showing compliance status
- **Detailed Remediation Guidance** for non-compliant resources
- **Export Capabilities** to CSV and PowerPoint for reporting
- **Organization-wide Aggregation** using AWS Config Aggregator
- **Secure Cross-account Access** with least-privilege IAM roles

## Architecture

```
┌─────────────────┐    ┌──────────────────┐    ┌─────────────────┐
│   Member        │    │   Audit Account  │    │   Dashboard     │
│   Accounts      │    │   (Delegated     │    │   (S3 Static    │
│                 │    │   Administrator) │    │   Website)      │
│ ┌─────────────┐ │    │ ┌──────────────┐ │    │ ┌─────────────┐ │
│ │Conformance  │ │    │ │Config        │ │    │ │React App    │ │
│ │Pack         │◄┼────┼►│Aggregator    │◄┼────┼►│with Charts  │ │
│ │             │ │    │ │              │ │    │ │             │ │
│ │IAM Role     │ │    │ │Lambda        │ │    │ │Export       │ │
│ └─────────────┘ │    │ │Functions     │ │    │ │Functions    │ │
└─────────────────┘    │ └──────────────┘ │    │ └─────────────┘ │
                       └──────────────────┘    └─────────────────┘
```

## Prerequisites

### AWS Account Setup
1. **Audit Account**: Must be designated as delegated administrator for AWS Config
2. **Organization**: AWS Organizations must be enabled
3. **Permissions**: Deploying account needs:
   - `OrganizationsFullAccess`
   - `CloudFormationFullAccess`
   - `ConfigFullAccess`
   - `IAMFullAccess`
   - `S3FullAccess`
   - `LambdaFullAccess`

### Local Environment
- AWS CLI v2.x installed and configured
- Bash shell (Linux/macOS/WSL)
- Internet connectivity for downloading dependencies

### Enable AWS Config as Delegated Administrator

```bash
# Run from Organization Management Account
aws organizations enable-aws-service-access --service-principal config.amazonaws.com
aws organizations register-delegated-administrator --account-id <AUDIT-ACCOUNT-ID> --service-principal config.amazonaws.com
```

## Quick Start

### 1. Clone and Prepare
```bash
git clone <repository-url>
cd security-hub-apra-cps-234-compliance
```

### 2. Deploy the Solution
```bash
./deploy.sh
```

The deployment script will:
1. ✅ Check prerequisites and AWS credentials
2. 📝 Prompt for configuration (S3 bucket names)
3. 📤 Upload conformance pack template to S3
4. 🏗️ Deploy main infrastructure via CloudFormation
5. 🌐 Deploy conformance packs across organization via StackSets
6. 🎨 Build and deploy the React dashboard
7. 🚀 Trigger initial data collection

### 3. Access Dashboard
After deployment completes, access your dashboard at:
```
http://<dashboard-bucket-name>.s3-website-<region>.amazonaws.com
```

## Manual Deployment (Alternative)

If you prefer manual deployment:

### Step 1: Deploy Main Infrastructure
```bash
aws cloudformation deploy \
  --template-file ./cloudformation/main-template.yaml \
  --stack-name apra-cpg-234-compliance-dashboard \
  --parameter-overrides \
    OrganizationId=o-xxxxxxxxxx \
    DashboardBucketName=my-compliance-dashboard-bucket \
  --capabilities CAPABILITY_IAM CAPABILITY_NAMED_IAM \
  --region us-east-1
```

### Step 2: Deploy Conformance Packs via StackSet
```bash
# Create StackSet instances across organization
aws cloudformation create-stack-instances \
  --stack-set-name APRA-CPG-234-Compliance-StackSet \
  --deployment-targets OrganizationalUnitIds=r-xxxx \
  --regions us-east-1 \
  --operation-preferences RegionConcurrencyType=PARALLEL,MaxConcurrentPercentage=100
```

### Step 3: Upload Dashboard Files
```bash
aws s3 cp dashboard/public/index.html s3://your-dashboard-bucket/index.html
```

## Configuration

### Environment Variables
The Lambda functions use these environment variables:
- `DASHBOARD_BUCKET`: S3 bucket for dashboard hosting
- `ORGANIZATION_ID`: AWS Organization ID
- `CONFIG_AGGREGATOR_NAME`: Name of Config aggregator
- `CONFORMANCE_PACK_NAME`: Name of conformance pack

### Customization Options

#### 1. Modify Conformance Pack Parameters
Edit `Operational-Best-Practices-for-APRA-CPG-234.yaml` to adjust:
- Password policy requirements
- Access key rotation periods
- Certificate expiration thresholds

#### 2. Update Data Collection Frequency
Modify the EventBridge rule in `main-template.yaml`:
```yaml
ScheduleExpression: 'rate(4 hours)'  # Change to desired frequency
```

#### 3. Customize Dashboard Appearance
Edit the CSS styles in the dashboard HTML template to match your branding.

## Features

### Dashboard Components

#### 1. Overview Metrics
- Total accounts in organization
- Overall compliance percentage
- Compliant vs non-compliant rule counts

#### 2. Visual Analytics
- **Donut Chart**: Organization-wide compliance ratio
- **Bar Chart**: Per-account conformance pack compliance
- **Trend Analysis**: Historical compliance data (future enhancement)

#### 3. Detailed Views
- Individual conformance pack status
- Failed control listings with resource links
- Remediation suggestions for each non-compliant control

#### 4. Export Capabilities
- **CSV Export**: Compliance data for spreadsheet analysis
- **PowerPoint Generation**: Executive reporting (via browser download)

### Security Features

#### 1. Cross-Account IAM Roles
```yaml
# Read-only role in each member account
ConfigComplianceRole:
  AssumeRolePolicyDocument:
    Principal:
      AWS: arn:aws:iam::AUDIT-ACCOUNT:root
  Policies:
    - ConfigRole (AWS Managed)
    - ReadOnlyAccess (AWS Managed)
```

#### 2. Least Privilege Access
- Lambda functions have minimal required permissions
- S3 bucket policies restrict access appropriately
- Cross-account roles use external ID for additional security

#### 3. Data Encryption
- S3 bucket encryption enabled (AES-256)
- Data in transit encrypted via HTTPS
- Lambda environment variables encrypted

## Monitoring and Troubleshooting

### CloudWatch Logs
Monitor Lambda function execution:
```bash
aws logs tail /aws/lambda/APRA-CPG-234-Compliance-data-collector --follow
```

### Common Issues

#### 1. StackSet Deployment Failures
**Symptom**: Conformance packs not deploying to all accounts
**Solution**: 
- Verify delegated administrator permissions
- Check account status in organization
- Review CloudFormation events in target accounts

#### 2. Dashboard Shows No Data
**Symptom**: Dashboard loads but shows "No compliance data available"
**Solution**:
- Check Lambda function logs for errors
- Verify Config aggregator is collecting data
- Ensure conformance packs are deployed and active

#### 3. Cross-Account Access Denied
**Symptom**: Lambda function cannot assume roles in member accounts
**Solution**:
- Verify IAM role trust relationships
- Check external ID configuration
- Ensure roles exist in target accounts

### Debugging Commands

```bash
# Check StackSet operation status
aws cloudformation describe-stack-set-operation \
  --stack-set-name APRA-CPG-234-Compliance-StackSet \
  --operation-id <operation-id>

# Test Lambda function
aws lambda invoke \
  --function-name APRA-CPG-234-Compliance-data-collector \
  --payload '{}' \
  response.json

# Check Config aggregator status
aws configservice describe-configuration-aggregators
```

## Cost Optimization

### Estimated Monthly Costs (100 accounts)
- **AWS Config**: ~$200-400 (depending on resource count)
- **Lambda**: ~$5-10 (based on execution frequency)
- **S3**: ~$1-5 (dashboard hosting and data storage)
- **CloudFormation**: No additional cost

### Cost Reduction Tips
1. Adjust data collection frequency based on needs
2. Use S3 lifecycle policies for historical data
3. Implement resource-based filtering in Config rules
4. Consider regional deployment strategy

## Security Best Practices

### 1. Regular Updates
- Monitor for new conformance pack versions
- Update Lambda runtime versions regularly
- Review and rotate IAM access keys

### 2. Access Control
- Implement IP restrictions on S3 bucket if needed
- Use CloudFront for additional security layers
- Enable MFA for administrative access

### 3. Monitoring
- Set up CloudWatch alarms for Lambda failures
- Monitor Config compliance drift
- Track unusual access patterns

## Extending the Solution

### 1. Additional Conformance Packs
Add more conformance packs by:
1. Uploading new YAML files to S3
2. Updating StackSet template
3. Modifying Lambda function to process additional packs

### 2. Custom Remediation
Implement automated remediation by:
1. Creating remediation Lambda functions
2. Configuring Config remediation actions
3. Adding remediation triggers to dashboard

### 3. Integration with Other Services
- **Security Hub**: Aggregate findings across services
- **Systems Manager**: Automated patching and compliance
- **CloudTrail**: Audit trail integration

## Support and Maintenance

### Regular Maintenance Tasks
1. **Monthly**: Review compliance trends and address persistent issues
2. **Quarterly**: Update conformance pack parameters as needed
3. **Annually**: Review and update IAM permissions

### Backup and Recovery
- CloudFormation templates serve as infrastructure backup
- S3 versioning protects dashboard and data files
- Config history provides compliance audit trail

## License

This solution is provided under the MIT License. See LICENSE file for details.

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Add tests if applicable
5. Submit a pull request

## Changelog

### Version 1.0.0
- Initial release with APRA CPG 234 conformance pack
- React-based dashboard with export capabilities
- CloudFormation StackSet deployment
- Cross-account IAM role configuration

---

For questions or support, please open an issue in the repository or contact your AWS solutions architect.
