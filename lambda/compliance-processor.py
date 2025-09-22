import json
import boto3
import os
from datetime import datetime, timezone
from decimal import Decimal
import logging

# Configure logging
logger = logging.getLogger()
logger.setLevel(logging.INFO)

class DecimalEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, Decimal):
            return float(obj)
        return super(DecimalEncoder, self).default(obj)

def lambda_handler(event, context):
    """
    Enhanced compliance data processor with detailed remediation suggestions
    """
    config_client = boto3.client('config')
    s3_client = boto3.client('s3')
    org_client = boto3.client('organizations')
    
    bucket = os.environ['DASHBOARD_BUCKET']
    aggregator_name = os.environ['CONFIG_AGGREGATOR_NAME']
    conformance_pack_name = os.environ['CONFORMANCE_PACK_NAME']
    
    try:
        logger.info("Starting compliance data collection")
        
        # Get organization accounts
        accounts_response = org_client.list_accounts()
        accounts = [
            {
                'accountId': acc['Id'], 
                'accountName': acc['Name'], 
                'status': acc['Status'],
                'email': acc['Email']
            } 
            for acc in accounts_response['Accounts']
        ]
        
        # Get conformance pack compliance summary
        compliance_summary = config_client.get_aggregate_conformance_pack_compliance_summary(
            ConfigurationAggregatorName=aggregator_name
        )
        
        # Get detailed compliance for each conformance pack
        detailed_compliance = {}
        account_compliance = {}
        
        for pack_summary in compliance_summary['AggregateConformancePackComplianceSummaries']:
            pack_name = pack_summary['ConformancePackName']
            account_id = pack_summary['AccountId']
            
            # Initialize account compliance tracking
            if account_id not in account_compliance:
                account_compliance[account_id] = {
                    'accountName': next((acc['accountName'] for acc in accounts if acc['accountId'] == account_id), 'Unknown'),
                    'conformancePacks': {},
                    'totalCompliant': 0,
                    'totalRules': 0
                }
            
            # Get compliance details for this pack
            try:
                details = config_client.get_aggregate_conformance_pack_compliance_details(
                    ConfigurationAggregatorName=aggregator_name,
                    ConformancePackName=pack_name,
                    AccountId=account_id
                )
                
                pack_details = details['AggregateConformancePackComplianceDetails']
                
                # Process non-compliant rules for remediation suggestions
                non_compliant_rules = [
                    detail for detail in pack_details 
                    if detail['ComplianceType'] == 'NON_COMPLIANT'
                ]
                
                # Store detailed compliance data
                if pack_name not in detailed_compliance:
                    detailed_compliance[pack_name] = {}
                
                detailed_compliance[pack_name][account_id] = {
                    'summary': pack_summary,
                    'details': pack_details,
                    'nonCompliantRules': non_compliant_rules
                }
                
                # Update account compliance tracking
                account_compliance[account_id]['conformancePacks'][pack_name] = {
                    'compliantRules': pack_summary.get('CompliantRuleCount', 0),
                    'totalRules': pack_summary.get('TotalRuleCount', 0),
                    'compliancePercentage': round(
                        (pack_summary.get('CompliantRuleCount', 0) / pack_summary.get('TotalRuleCount', 1)) * 100, 2
                    )
                }
                
                account_compliance[account_id]['totalCompliant'] += pack_summary.get('CompliantRuleCount', 0)
                account_compliance[account_id]['totalRules'] += pack_summary.get('TotalRuleCount', 0)
                
            except Exception as e:
                logger.error(f"Error getting details for pack {pack_name} in account {account_id}: {str(e)}")
                continue
        
        # Calculate overall compliance percentages for accounts
        for account_id in account_compliance:
            total_rules = account_compliance[account_id]['totalRules']
            if total_rules > 0:
                account_compliance[account_id]['overallCompliancePercentage'] = round(
                    (account_compliance[account_id]['totalCompliant'] / total_rules) * 100, 2
                )
            else:
                account_compliance[account_id]['overallCompliancePercentage'] = 0
        
        # Calculate organization-wide compliance
        org_compliance = calculate_org_compliance(compliance_summary)
        
        # Generate remediation suggestions
        remediation_data = generate_remediation_suggestions(detailed_compliance)
        
        # Prepare dashboard data
        dashboard_data = {
            'lastUpdated': datetime.now(timezone.utc).isoformat(),
            'accounts': accounts,
            'conformancePackSummary': compliance_summary['AggregateConformancePackComplianceSummaries'],
            'detailedCompliance': detailed_compliance,
            'accountCompliance': account_compliance,
            'organizationCompliance': org_compliance,
            'remediationSuggestions': remediation_data,
            'statistics': generate_statistics(compliance_summary, account_compliance)
        }
        
        # Upload to S3
        s3_client.put_object(
            Bucket=bucket,
            Key='data/compliance-summary.json',
            Body=json.dumps(dashboard_data, indent=2, cls=DecimalEncoder),
            ContentType='application/json'
        )
        
        # Generate individual conformance pack reports
        for pack_name in detailed_compliance:
            pack_report = generate_pack_report(pack_name, detailed_compliance[pack_name], remediation_data.get(pack_name, {}))
            s3_client.put_object(
                Bucket=bucket,
                Key=f'data/packs/{pack_name}.json',
                Body=json.dumps(pack_report, indent=2, cls=DecimalEncoder),
                ContentType='application/json'
            )
        
        logger.info("Compliance data collection completed successfully")
        return {
            'statusCode': 200,
            'body': json.dumps('Data collection completed successfully')
        }
        
    except Exception as e:
        logger.error(f"Error in compliance data collection: {str(e)}")
        return {
            'statusCode': 500,
            'body': json.dumps(f'Error: {str(e)}')
        }

def calculate_org_compliance(summary):
    """Calculate organization-wide compliance metrics"""
    summaries = summary['AggregateConformancePackComplianceSummaries']
    total_compliant = sum(pack.get('CompliantRuleCount', 0) for pack in summaries)
    total_rules = sum(pack.get('TotalRuleCount', 0) for pack in summaries)
    
    return {
        'compliantRules': total_compliant,
        'totalRules': total_rules,
        'compliancePercentage': round((total_compliant / total_rules * 100) if total_rules > 0 else 0, 2),
        'nonCompliantRules': total_rules - total_compliant
    }

def generate_remediation_suggestions(detailed_compliance):
    """Generate detailed remediation suggestions for non-compliant rules"""
    
    # Comprehensive remediation mapping
    remediation_map = {
        'access-keys-rotated': {
            'title': 'Access Key Rotation',
            'description': 'IAM access keys should be rotated regularly',
            'remediation': 'Implement automated access key rotation using AWS Secrets Manager or Lambda functions',
            'priority': 'High',
            'effort': 'Medium',
            'resources': [
                'https://docs.aws.amazon.com/IAM/latest/UserGuide/id_credentials_access-keys.html#Using_RotateAccessKey'
            ]
        },
        'acm-certificate-expiration-check': {
            'title': 'Certificate Expiration',
            'description': 'SSL/TLS certificates should be renewed before expiration',
            'remediation': 'Set up automated certificate renewal using ACM and CloudWatch alarms',
            'priority': 'High',
            'effort': 'Low',
            'resources': [
                'https://docs.aws.amazon.com/acm/latest/userguide/acm-renewal.html'
            ]
        },
        'cloudtrail-enabled': {
            'title': 'CloudTrail Logging',
            'description': 'CloudTrail should be enabled for audit logging',
            'remediation': 'Enable CloudTrail in all regions with proper S3 bucket configuration and log file validation',
            'priority': 'Critical',
            'effort': 'Low',
            'resources': [
                'https://docs.aws.amazon.com/cloudtrail/latest/userguide/cloudtrail-create-and-update-a-trail.html'
            ]
        },
        'ec2-security-group-attached-to-eni': {
            'title': 'Security Group Configuration',
            'description': 'Security groups should follow least privilege principle',
            'remediation': 'Review and update security group rules to restrict unnecessary access',
            'priority': 'High',
            'effort': 'Medium',
            'resources': [
                'https://docs.aws.amazon.com/vpc/latest/userguide/VPC_SecurityGroups.html'
            ]
        },
        'guardduty-enabled-centralized': {
            'title': 'GuardDuty Threat Detection',
            'description': 'GuardDuty should be enabled for threat detection',
            'remediation': 'Enable GuardDuty in all accounts and regions, configure centralized management',
            'priority': 'High',
            'effort': 'Low',
            'resources': [
                'https://docs.aws.amazon.com/guardduty/latest/ug/guardduty_settingup.html'
            ]
        },
        'iam-password-policy': {
            'title': 'IAM Password Policy',
            'description': 'Strong password policy should be enforced',
            'remediation': 'Configure IAM password policy with minimum length, complexity requirements, and rotation',
            'priority': 'Medium',
            'effort': 'Low',
            'resources': [
                'https://docs.aws.amazon.com/IAM/latest/UserGuide/id_credentials_passwords_account-policy.html'
            ]
        },
        'mfa-enabled-for-iam-console-access': {
            'title': 'Multi-Factor Authentication',
            'description': 'MFA should be enabled for all IAM users',
            'remediation': 'Enforce MFA for all IAM users with console access using IAM policies',
            'priority': 'Critical',
            'effort': 'Medium',
            'resources': [
                'https://docs.aws.amazon.com/IAM/latest/UserGuide/id_credentials_mfa.html'
            ]
        },
        's3-bucket-public-access-prohibited': {
            'title': 'S3 Public Access',
            'description': 'S3 buckets should not allow public access unless required',
            'remediation': 'Enable S3 Block Public Access settings and review bucket policies',
            'priority': 'Critical',
            'effort': 'Low',
            'resources': [
                'https://docs.aws.amazon.com/AmazonS3/latest/userguide/access-control-block-public-access.html'
            ]
        }
    }
    
    suggestions = {}
    for pack_name, pack_data in detailed_compliance.items():
        pack_suggestions = []
        
        for account_id, account_data in pack_data.items():
            for detail in account_data.get('nonCompliantRules', []):
                rule_name = detail['ConfigRuleName']
                
                # Get base rule name (remove suffixes)
                base_rule_name = rule_name.lower().replace('_', '-')
                for suffix in ['-conformance-pack', '-config-rule']:
                    base_rule_name = base_rule_name.replace(suffix, '')
                
                suggestion_data = remediation_map.get(base_rule_name, {
                    'title': f'Remediate {rule_name}',
                    'description': f'Address non-compliance for {rule_name}',
                    'remediation': f'Review and remediate the configuration for {rule_name}',
                    'priority': 'Medium',
                    'effort': 'Medium',
                    'resources': []
                })
                
                pack_suggestions.append({
                    'ruleName': rule_name,
                    'accountId': account_id,
                    'awsRegion': detail.get('AwsRegion', 'N/A'),
                    'complianceType': detail.get('ComplianceType', 'NON_COMPLIANT'),
                    'lastConfigurationItemCaptureTime': detail.get('LastConfigurationItemCaptureTime', ''),
                    **suggestion_data
                })
        
        suggestions[pack_name] = pack_suggestions
    
    return suggestions

def generate_statistics(compliance_summary, account_compliance):
    """Generate statistical insights for the dashboard"""
    
    summaries = compliance_summary['AggregateConformancePackComplianceSummaries']
    
    # Account distribution by compliance level
    compliance_distribution = {'excellent': 0, 'good': 0, 'fair': 0, 'poor': 0}
    
    for account_id, account_data in account_compliance.items():
        percentage = account_data.get('overallCompliancePercentage', 0)
        if percentage >= 95:
            compliance_distribution['excellent'] += 1
        elif percentage >= 80:
            compliance_distribution['good'] += 1
        elif percentage >= 60:
            compliance_distribution['fair'] += 1
        else:
            compliance_distribution['poor'] += 1
    
    # Top non-compliant rules
    rule_failures = {}
    for pack_name, pack_data in account_compliance.items():
        # This would need to be enhanced with actual rule failure data
        pass
    
    return {
        'totalAccounts': len(account_compliance),
        'complianceDistribution': compliance_distribution,
        'averageCompliance': round(
            sum(acc.get('overallCompliancePercentage', 0) for acc in account_compliance.values()) / 
            len(account_compliance) if account_compliance else 0, 2
        )
    }

def generate_pack_report(pack_name, pack_data, remediation_data):
    """Generate individual conformance pack report"""
    
    total_accounts = len(pack_data)
    compliant_accounts = sum(1 for acc_data in pack_data.values() 
                           if acc_data['summary'].get('CompliantRuleCount', 0) == acc_data['summary'].get('TotalRuleCount', 0))
    
    return {
        'packName': pack_name,
        'totalAccounts': total_accounts,
        'compliantAccounts': compliant_accounts,
        'compliancePercentage': round((compliant_accounts / total_accounts * 100) if total_accounts > 0 else 0, 2),
        'accountDetails': pack_data,
        'remediationSuggestions': remediation_data,
        'lastUpdated': datetime.now(timezone.utc).isoformat()
    }
