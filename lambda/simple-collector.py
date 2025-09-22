import json
import boto3
import os
from datetime import datetime, timezone

def lambda_handler(event, context):
    config_client = boto3.client('config')
    s3_client = boto3.client('s3')
    org_client = boto3.client('organizations')
    
    bucket = os.environ['DASHBOARD_BUCKET']
    aggregator_name = os.environ['CONFIG_AGGREGATOR_NAME']
    
    try:
        # Get organization accounts
        accounts_response = org_client.list_accounts()
        accounts = [
            {
                'accountId': acc['Id'], 
                'accountName': acc['Name'], 
                'status': acc['Status']
            } 
            for acc in accounts_response['Accounts']
        ]
        
        # Get conformance pack compliance summary for ALL packs
        compliance_summary = config_client.get_aggregate_conformance_pack_compliance_summary(
            ConfigurationAggregatorName=aggregator_name
        )
        
        # Get detailed compliance for each conformance pack
        conformance_packs_detail = []
        try:
            packs_response = config_client.describe_aggregate_compliance_by_conformance_packs(
                ConfigurationAggregatorName=aggregator_name
            )
            conformance_packs_detail = packs_response.get('AggregateComplianceByConformancePacks', [])
        except Exception as e:
            print(f"Could not get conformance pack details: {e}")
        
        # Get aggregate compliance by config rules
        try:
            rules_response = config_client.describe_aggregate_compliance_by_config_rules(
                ConfigurationAggregatorName=aggregator_name
            )
            
            # Calculate totals from all rules
            total_compliant = 0
            total_non_compliant = 0
            
            for rule in rules_response.get('AggregateComplianceByConfigRules', []):
                compliance = rule.get('Compliance', {})
                if compliance.get('ComplianceType') == 'COMPLIANT':
                    total_compliant += 1
                elif compliance.get('ComplianceType') == 'NON_COMPLIANT':
                    total_non_compliant += 1
            
            total_rules = total_compliant + total_non_compliant
            compliance_percentage = (total_compliant / total_rules * 100) if total_rules > 0 else 0
            
        except Exception as e:
            print(f"Could not get rule compliance: {e}")
            total_compliant = 0
            total_non_compliant = 0
            total_rules = 0
            compliance_percentage = 0
        
        # Prepare data
        data = {
            'lastUpdated': datetime.now(timezone.utc).isoformat(),
            'accounts': accounts,
            'conformancePackSummary': compliance_summary.get('AggregateConformancePackComplianceSummaries', []),
            'conformancePackDetails': conformance_packs_detail,
            'organizationCompliance': {
                'compliantRules': total_compliant,
                'nonCompliantRules': total_non_compliant,
                'totalRules': total_rules,
                'compliancePercentage': round(compliance_percentage, 2)
            },
            'remediationSuggestions': {}
        }
        
        # Upload to S3
        s3_client.put_object(
            Bucket=bucket,
            Key='data/compliance-summary.json',
            Body=json.dumps(data, indent=2),
            ContentType='application/json'
        )
        
        return {
            'statusCode': 200,
            'body': json.dumps('Data collection completed successfully')
        }
        
    except Exception as e:
        print(f"Error: {str(e)}")
        return {
            'statusCode': 500,
            'body': json.dumps(f'Error: {str(e)}')
        }
