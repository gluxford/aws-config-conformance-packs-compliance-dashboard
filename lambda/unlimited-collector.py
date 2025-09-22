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
        
        # Get conformance pack compliance summary
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
        rules_compliance = []
        try:
            rules_response = config_client.describe_aggregate_compliance_by_config_rules(
                ConfigurationAggregatorName=aggregator_name
            )
            rules_compliance = rules_response.get('AggregateComplianceByConfigRules', [])
            
            # Calculate totals from all rules
            total_compliant = sum(1 for rule in rules_compliance if rule.get('Compliance', {}).get('ComplianceType') == 'COMPLIANT')
            total_non_compliant = sum(1 for rule in rules_compliance if rule.get('Compliance', {}).get('ComplianceType') == 'NON_COMPLIANT')
            total_rules = total_compliant + total_non_compliant
            compliance_percentage = (total_compliant / total_rules * 100) if total_rules > 0 else 0
            
        except Exception as e:
            print(f"Could not get rule compliance: {e}")
            total_compliant = 0
            total_non_compliant = 0
            total_rules = 0
            compliance_percentage = 0

        # Get ALL non-compliant rule findings without limits
        non_compliant_details = []
        non_compliant_rules = [rule for rule in rules_compliance if rule.get('Compliance', {}).get('ComplianceType') == 'NON_COMPLIANT']
        
        print(f"Processing {len(non_compliant_rules)} non-compliant rules")
        
        # Process ALL non-compliant rules (no account limits)
        for i, rule in enumerate(non_compliant_rules):
            if i % 50 == 0:
                print(f"Processed {i}/{len(non_compliant_rules)} rules")
                
            try:
                details_response = config_client.get_aggregate_compliance_details_by_config_rule(
                    ConfigurationAggregatorName=aggregator_name,
                    ConfigRuleName=rule['ConfigRuleName'],
                    AccountId=rule['AccountId'],
                    AwsRegion=rule['AwsRegion']
                )
                
                # Determine which specific conformance pack this rule belongs to based on rule name pattern
                rule_name = rule['ConfigRuleName']
                specific_conformance_pack = None
                account_id = rule['AccountId']
                
                # Extract conformance pack suffix from rule name
                if '-conformance-pack-' in rule_name:
                    # Find which conformance pack in this account has rules with this suffix
                    account_packs = [p for p in conformance_packs_detail if p['AccountId'] == account_id]
                    
                    # Use rule name patterns to identify specific conformance pack
                    if 'iam-password-policy' in rule_name or 'root-access' in rule_name or 'mfa-enabled' in rule_name:
                        # These are typically CIS rules
                        cis_pack = next((p for p in account_packs if 'CIS' in p['ConformancePackName']), None)
                        if cis_pack:
                            specific_conformance_pack = cis_pack['ConformancePackName']
                    elif 's3-bucket' in rule_name or 'cloudtrail' in rule_name or 'vpc-flow' in rule_name:
                        # These are typically Security Pillar rules
                        security_pack = next((p for p in account_packs if 'Security-Pillar' in p['ConformancePackName']), None)
                        if security_pack:
                            specific_conformance_pack = security_pack['ConformancePackName']
                    elif 'encryption' in rule_name or 'logging' in rule_name or 'api-gw' in rule_name:
                        # These are typically NIST rules
                        nist_pack = next((p for p in account_packs if 'NIST' in p['ConformancePackName']), None)
                        if nist_pack:
                            specific_conformance_pack = nist_pack['ConformancePackName']
                    else:
                        # Default to APRA if no specific pattern matches
                        apra_pack = next((p for p in account_packs if 'APRA' in p['ConformancePackName']), None)
                        if apra_pack:
                            specific_conformance_pack = apra_pack['ConformancePackName']
                
                # If still no specific pack identified, assign to first available pack for this account
                if not specific_conformance_pack:
                    account_packs = [p for p in conformance_packs_detail if p['AccountId'] == account_id]
                    if account_packs:
                        specific_conformance_pack = account_packs[0]['ConformancePackName']
                
                # Get ALL evaluation results for this rule (no limit)
                for result in details_response.get('AggregateEvaluationResults', []):
                    if result.get('ComplianceType') == 'NON_COMPLIANT':
                        non_compliant_details.append({
                            'ConfigRuleName': rule['ConfigRuleName'],
                            'AccountId': rule['AccountId'],
                            'AwsRegion': rule['AwsRegion'],
                            'ResourceType': result.get('EvaluationResultIdentifier', {}).get('EvaluationResultQualifier', {}).get('ResourceType'),
                            'ResourceId': result.get('EvaluationResultIdentifier', {}).get('EvaluationResultQualifier', {}).get('ResourceId'),
                            'ComplianceType': result.get('ComplianceType'),
                            'ResultRecordedTime': result.get('ResultRecordedTime').isoformat() if result.get('ResultRecordedTime') else None,
                            'ConformancePackName': specific_conformance_pack
                        })
            except Exception as e:
                print(f"Could not get details for rule {rule['ConfigRuleName']} in account {rule['AccountId']}: {e}")
                # Add basic info even if details fail
                non_compliant_details.append({
                    'ConfigRuleName': rule['ConfigRuleName'],
                    'AccountId': rule['AccountId'],
                    'AwsRegion': rule['AwsRegion'],
                    'ResourceType': 'Unknown',
                    'ResourceId': 'Unknown',
                    'ComplianceType': 'NON_COMPLIANT',
                    'ResultRecordedTime': None,
                    'ConformancePackName': specific_conformance_pack
                })
        
        print(f"Collected {len(non_compliant_details)} non-compliant details from {len(non_compliant_rules)} rules")
        
        # Prepare data
        data = {
            'lastUpdated': datetime.now(timezone.utc).isoformat(),
            'accounts': accounts,
            'conformancePackSummary': compliance_summary.get('AggregateConformancePackComplianceSummaries', []),
            'conformancePackDetails': conformance_packs_detail,
            'rulesCompliance': rules_compliance,
            'nonCompliantDetails': non_compliant_details,
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
            Body=json.dumps(data, indent=2, default=str),
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
