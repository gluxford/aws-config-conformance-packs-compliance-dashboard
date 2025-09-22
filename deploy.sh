#!/bin/bash

# APRA CPG 234 Compliance Dashboard Deployment Script
set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Configuration
STACK_NAME="apra-cpg-234-compliance-dashboard"
REGION=${AWS_DEFAULT_REGION:-"us-east-1"}
CONFORMANCE_PACK_BUCKET=""
DASHBOARD_BUCKET_NAME=""
ORGANIZATION_ID=""

# Functions
print_header() {
    echo -e "${BLUE}================================${NC}"
    echo -e "${BLUE}$1${NC}"
    echo -e "${BLUE}================================${NC}"
}

print_success() {
    echo -e "${GREEN}✓ $1${NC}"
}

print_warning() {
    echo -e "${YELLOW}⚠ $1${NC}"
}

print_error() {
    echo -e "${RED}✗ $1${NC}"
}

check_prerequisites() {
    print_header "Checking Prerequisites"
    
    # Check AWS CLI
    if ! command -v aws &> /dev/null; then
        print_error "AWS CLI is not installed"
        exit 1
    fi
    print_success "AWS CLI is installed"
    
    # Check AWS credentials
    if ! aws sts get-caller-identity &> /dev/null; then
        print_error "AWS credentials not configured"
        exit 1
    fi
    print_success "AWS credentials configured"
    
    # Check if running in audit account
    ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
    print_success "Running in account: $ACCOUNT_ID"
    
    # Check organization
    if ! aws organizations describe-organization &> /dev/null; then
        print_error "Not running in organization management account or delegated administrator"
        exit 1
    fi
    
    ORGANIZATION_ID=$(aws organizations describe-organization --query Organization.Id --output text)
    print_success "Organization ID: $ORGANIZATION_ID"
}

get_user_input() {
    print_header "Configuration Input"
    
    # Get dashboard bucket name
    while [[ -z "$DASHBOARD_BUCKET_NAME" ]]; do
        read -p "Enter unique S3 bucket name for dashboard (e.g., my-org-compliance-dashboard-$(date +%s)): " DASHBOARD_BUCKET_NAME
        
        # Validate bucket name
        if [[ ! "$DASHBOARD_BUCKET_NAME" =~ ^[a-z0-9][a-z0-9-]*[a-z0-9]$ ]]; then
            print_error "Invalid bucket name. Use lowercase letters, numbers, and hyphens only."
            DASHBOARD_BUCKET_NAME=""
        fi
    done
    
    # Get conformance pack bucket (for uploading the YAML)
    while [[ -z "$CONFORMANCE_PACK_BUCKET" ]]; do
        read -p "Enter S3 bucket name for conformance pack templates (will be created if doesn't exist): " CONFORMANCE_PACK_BUCKET
    done
    
    print_success "Configuration complete"
}

upload_conformance_pack() {
    print_header "Uploading Conformance Pack"
    
    # Create bucket if it doesn't exist
    if ! aws s3 ls "s3://$CONFORMANCE_PACK_BUCKET" &> /dev/null; then
        print_warning "Creating S3 bucket: $CONFORMANCE_PACK_BUCKET"
        aws s3 mb "s3://$CONFORMANCE_PACK_BUCKET" --region "$REGION"
    fi
    
    # Upload conformance pack YAML
    aws s3 cp "./Operational-Best-Practices-for-APRA-CPG-234.yaml" \
        "s3://$CONFORMANCE_PACK_BUCKET/conformance-packs/Operational-Best-Practices-for-APRA-CPG-234.yaml"
    
    print_success "Conformance pack uploaded"
}

deploy_infrastructure() {
    print_header "Deploying Infrastructure"
    
    # Deploy main CloudFormation stack
    aws cloudformation deploy \
        --template-file "./cloudformation/main-template.yaml" \
        --stack-name "$STACK_NAME" \
        --parameter-overrides \
            OrganizationId="$ORGANIZATION_ID" \
            DashboardBucketName="$DASHBOARD_BUCKET_NAME" \
        --capabilities CAPABILITY_IAM CAPABILITY_NAMED_IAM \
        --region "$REGION"
    
    print_success "Infrastructure deployed"
}

deploy_conformance_packs() {
    print_header "Deploying Conformance Packs via StackSet"
    
    # Get StackSet name from CloudFormation output
    STACKSET_NAME=$(aws cloudformation describe-stacks \
        --stack-name "$STACK_NAME" \
        --query 'Stacks[0].Outputs[?OutputKey==`StackSetName`].OutputValue' \
        --output text \
        --region "$REGION" 2>/dev/null || echo "")
    
    if [[ -z "$STACKSET_NAME" ]]; then
        print_warning "StackSet not found in outputs, using default name"
        STACKSET_NAME="APRA-CPG-234-Compliance-StackSet"
    fi
    
    # Create StackSet operation to deploy to organization
    OPERATION_ID=$(aws cloudformation create-stack-instances \
        --stack-set-name "$STACKSET_NAME" \
        --deployment-targets OrganizationalUnitIds=r-$(echo $ORGANIZATION_ID | cut -c3-) \
        --regions "$REGION" \
        --operation-preferences RegionConcurrencyType=PARALLEL,MaxConcurrentPercentage=100 \
        --query 'OperationId' \
        --output text \
        --region "$REGION")
    
    print_success "StackSet deployment initiated: $OPERATION_ID"
    print_warning "Monitor deployment progress in CloudFormation console"
}

build_and_deploy_dashboard() {
    print_header "Building and Deploying Dashboard"
    
    # Create dashboard files
    mkdir -p dashboard/public dashboard/src
    
    # Create minimal React app structure
    cat > dashboard/public/index.html << 'EOF'
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>APRA CPG 234 Compliance Dashboard</title>
    <script src="https://unpkg.com/react@18/umd/react.production.min.js"></script>
    <script src="https://unpkg.com/react-dom@18/umd/react-dom.production.min.js"></script>
    <script src="https://unpkg.com/recharts@2.8.0/umd/Recharts.js"></script>
    <link href="https://cdn.jsdelivr.net/npm/antd@5.9.0/dist/reset.css" rel="stylesheet">
    <style>
        body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; margin: 0; padding: 20px; }
        .dashboard { max-width: 1200px; margin: 0 auto; }
        .header { text-align: center; margin-bottom: 30px; }
        .metrics { display: grid; grid-template-columns: repeat(auto-fit, minmax(250px, 1fr)); gap: 20px; margin-bottom: 30px; }
        .metric-card { background: #f8f9fa; padding: 20px; border-radius: 8px; border-left: 4px solid #1890ff; }
        .chart-container { background: white; padding: 20px; border-radius: 8px; box-shadow: 0 2px 8px rgba(0,0,0,0.1); margin-bottom: 20px; }
        .compliance-status { font-size: 24px; font-weight: bold; }
        .compliant { color: #52c41a; }
        .non-compliant { color: #ff4d4f; }
        .loading { text-align: center; padding: 50px; }
        .export-buttons { margin: 20px 0; }
        .export-btn { margin-right: 10px; padding: 8px 16px; background: #1890ff; color: white; border: none; border-radius: 4px; cursor: pointer; }
    </style>
</head>
<body>
    <div id="root"></div>
    <script>
        const { useState, useEffect } = React;
        const { PieChart, Pie, Cell, ResponsiveContainer, BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, Legend } = Recharts;
        
        function ComplianceDashboard() {
            const [data, setData] = useState(null);
            const [loading, setLoading] = useState(true);
            
            useEffect(() => {
                fetchComplianceData();
                const interval = setInterval(fetchComplianceData, 300000); // Refresh every 5 minutes
                return () => clearInterval(interval);
            }, []);
            
            const fetchComplianceData = async () => {
                try {
                    const response = await fetch('./data/compliance-summary.json');
                    const complianceData = await response.json();
                    setData(complianceData);
                    setLoading(false);
                } catch (error) {
                    console.error('Error fetching compliance data:', error);
                    setLoading(false);
                }
            };
            
            const exportToCSV = () => {
                if (!data) return;
                
                let csv = 'Conformance Pack,Account ID,Compliant Rules,Total Rules,Compliance %\n';
                data.conformancePackSummary.forEach(pack => {
                    const compliance = ((pack.CompliantRuleCount / pack.TotalRuleCount) * 100).toFixed(2);
                    csv += `${pack.ConformancePackName},${pack.AccountId},${pack.CompliantRuleCount},${pack.TotalRuleCount},${compliance}%\n`;
                });
                
                const blob = new Blob([csv], { type: 'text/csv' });
                const url = window.URL.createObjectURL(blob);
                const a = document.createElement('a');
                a.href = url;
                a.download = 'compliance-report.csv';
                a.click();
            };
            
            if (loading) {
                return React.createElement('div', { className: 'loading' }, 'Loading compliance data...');
            }
            
            if (!data) {
                return React.createElement('div', { className: 'loading' }, 'No compliance data available');
            }
            
            const pieData = [
                { name: 'Compliant', value: data.organizationCompliance.compliantRules, color: '#52c41a' },
                { name: 'Non-Compliant', value: data.organizationCompliance.nonCompliantRules, color: '#ff4d4f' }
            ];
            
            const barData = data.conformancePackSummary.map(pack => ({
                name: pack.ConformancePackName.substring(0, 20) + '...',
                compliant: pack.CompliantRuleCount,
                nonCompliant: pack.TotalRuleCount - pack.CompliantRuleCount,
                total: pack.TotalRuleCount
            }));
            
            return React.createElement('div', { className: 'dashboard' }, [
                React.createElement('div', { className: 'header', key: 'header' }, [
                    React.createElement('h1', { key: 'title' }, 'APRA CPG 234 Compliance Dashboard'),
                    React.createElement('p', { key: 'updated' }, `Last Updated: ${new Date(data.lastUpdated).toLocaleString()}`)
                ]),
                
                React.createElement('div', { className: 'export-buttons', key: 'export' }, [
                    React.createElement('button', { 
                        className: 'export-btn', 
                        onClick: exportToCSV,
                        key: 'csv-btn'
                    }, 'Export to CSV')
                ]),
                
                React.createElement('div', { className: 'metrics', key: 'metrics' }, [
                    React.createElement('div', { className: 'metric-card', key: 'total-accounts' }, [
                        React.createElement('h3', { key: 'title' }, 'Total Accounts'),
                        React.createElement('div', { className: 'compliance-status', key: 'value' }, data.accounts.length)
                    ]),
                    React.createElement('div', { className: 'metric-card', key: 'compliance-rate' }, [
                        React.createElement('h3', { key: 'title' }, 'Overall Compliance'),
                        React.createElement('div', { 
                            className: `compliance-status ${data.organizationCompliance.compliancePercentage >= 80 ? 'compliant' : 'non-compliant'}`,
                            key: 'value'
                        }, `${data.organizationCompliance.compliancePercentage}%`)
                    ]),
                    React.createElement('div', { className: 'metric-card', key: 'compliant-rules' }, [
                        React.createElement('h3', { key: 'title' }, 'Compliant Rules'),
                        React.createElement('div', { className: 'compliance-status compliant', key: 'value' }, data.organizationCompliance.compliantRules)
                    ]),
                    React.createElement('div', { className: 'metric-card', key: 'non-compliant-rules' }, [
                        React.createElement('h3', { key: 'title' }, 'Non-Compliant Rules'),
                        React.createElement('div', { className: 'compliance-status non-compliant', key: 'value' }, data.organizationCompliance.nonCompliantRules)
                    ])
                ]),
                
                React.createElement('div', { className: 'chart-container', key: 'pie-chart' }, [
                    React.createElement('h3', { key: 'title' }, 'Organization Compliance Overview'),
                    React.createElement(ResponsiveContainer, { width: '100%', height: 300, key: 'chart' },
                        React.createElement(PieChart, null,
                            React.createElement(Pie, {
                                data: pieData,
                                cx: '50%',
                                cy: '50%',
                                outerRadius: 100,
                                dataKey: 'value',
                                label: ({ name, percent }) => `${name}: ${(percent * 100).toFixed(1)}%`
                            }, pieData.map((entry, index) =>
                                React.createElement(Cell, { key: `cell-${index}`, fill: entry.color })
                            )),
                            React.createElement(Tooltip)
                        )
                    )
                ]),
                
                React.createElement('div', { className: 'chart-container', key: 'bar-chart' }, [
                    React.createElement('h3', { key: 'title' }, 'Conformance Pack Compliance by Account'),
                    React.createElement(ResponsiveContainer, { width: '100%', height: 400, key: 'chart' },
                        React.createElement(BarChart, { data: barData },
                            React.createElement(CartesianGrid, { strokeDasharray: '3 3' }),
                            React.createElement(XAxis, { dataKey: 'name', angle: -45, textAnchor: 'end', height: 100 }),
                            React.createElement(YAxis),
                            React.createElement(Tooltip),
                            React.createElement(Legend),
                            React.createElement(Bar, { dataKey: 'compliant', stackId: 'a', fill: '#52c41a', name: 'Compliant' }),
                            React.createElement(Bar, { dataKey: 'nonCompliant', stackId: 'a', fill: '#ff4d4f', name: 'Non-Compliant' })
                        )
                    )
                ])
            ]);
        }
        
        ReactDOM.render(React.createElement(ComplianceDashboard), document.getElementById('root'));
    </script>
</body>
</html>
EOF
    
    # Upload dashboard to S3
    aws s3 cp dashboard/public/index.html "s3://$DASHBOARD_BUCKET_NAME/index.html" --content-type "text/html"
    
    print_success "Dashboard deployed"
}

trigger_initial_data_collection() {
    print_header "Triggering Initial Data Collection"
    
    # Get Lambda function name
    LAMBDA_FUNCTION=$(aws cloudformation describe-stacks \
        --stack-name "$STACK_NAME" \
        --query 'Stacks[0].Outputs[?OutputKey==`DataCollectorFunction`].OutputValue' \
        --output text \
        --region "$REGION" 2>/dev/null || echo "APRA-CPG-234-Compliance-data-collector")
    
    # Invoke Lambda function
    aws lambda invoke \
        --function-name "$LAMBDA_FUNCTION" \
        --region "$REGION" \
        /tmp/lambda-response.json
    
    print_success "Initial data collection triggered"
}

display_results() {
    print_header "Deployment Complete"
    
    DASHBOARD_URL=$(aws cloudformation describe-stacks \
        --stack-name "$STACK_NAME" \
        --query 'Stacks[0].Outputs[?OutputKey==`DashboardURL`].OutputValue' \
        --output text \
        --region "$REGION")
    
    echo -e "${GREEN}Dashboard URL: $DASHBOARD_URL${NC}"
    echo -e "${YELLOW}Note: It may take a few minutes for the dashboard to populate with data${NC}"
    echo -e "${BLUE}Monitor the deployment progress in the AWS CloudFormation console${NC}"
}

# Main execution
main() {
    print_header "APRA CPG 234 Compliance Dashboard Deployment"
    
    check_prerequisites
    get_user_input
    upload_conformance_pack
    deploy_infrastructure
    deploy_conformance_packs
    build_and_deploy_dashboard
    trigger_initial_data_collection
    display_results
}

# Run main function
main "$@"
