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

        # Create conformance pack to rule mapping
        pack_rule_mapping = {}
        for pack in conformance_packs_detail:
            pack_name = pack['ConformancePackName']
            account_id = pack['AccountId']
            
            if pack_name not in pack_rule_mapping:
                pack_rule_mapping[pack_name] = set()
            
            # Get rules for this specific conformance pack
            try:
                pack_rules_response = config_client.describe_aggregate_compliance_by_config_rules(
                    ConfigurationAggregatorName=aggregator_name,
                    Filters={
                        'AccountId': account_id,
                        'ComplianceType': 'NON_COMPLIANT'
                    }
                )
                
                for rule in pack_rules_response.get('AggregateComplianceByConfigRules', []):
                    rule_name = rule['ConfigRuleName']
                    # Try to correlate rule to conformance pack by checking if rule exists in this account
                    pack_rule_mapping[pack_name].add(rule_name)
                    
            except Exception as e:
                print(f"Could not get rules for pack {pack_name} in account {account_id}: {e}")

        # Get detailed non-compliant rule findings with conformance pack correlation
        non_compliant_details = []
        non_compliant_rules = [rule for rule in rules_compliance if rule.get('Compliance', {}).get('ComplianceType') == 'NON_COMPLIANT']
        
        # Group by account to get balanced data
        rules_by_account = {}
        for rule in non_compliant_rules:
            account_id = rule['AccountId']
            if account_id not in rules_by_account:
                rules_by_account[account_id] = []
            rules_by_account[account_id].append(rule)
        
        # Get up to 20 rules per account for balanced representation
        for account_id, account_rules in rules_by_account.items():
            rules_to_process = account_rules[:20]  # Increased limit per account
            
            for rule in rules_to_process:
                try:
                    details_response = config_client.get_aggregate_compliance_details_by_config_rule(
                        ConfigurationAggregatorName=aggregator_name,
                        ConfigRuleName=rule['ConfigRuleName'],
                        AccountId=rule['AccountId'],
                        AwsRegion=rule['AwsRegion']
                    )
                    
                    # Determine which conformance pack this rule belongs to
                    rule_conformance_packs = []
                    rule_name = rule['ConfigRuleName']
                    
                    for pack_name, pack_rules in pack_rule_mapping.items():
                        if rule_name in pack_rules:
                            rule_conformance_packs.append(pack_name)
                    
                    # If no direct mapping, try pattern matching
                    if not rule_conformance_packs:
                        for pack in conformance_packs_detail:
                            if pack['AccountId'] == rule['AccountId']:
                                rule_conformance_packs.append(pack['ConformancePackName'])
                    
                    for result in details_response.get('AggregateEvaluationResults', [])[:2]:  # Limit results per rule
                        if result.get('ComplianceType') == 'NON_COMPLIANT':
                            non_compliant_details.append({
                                'ConfigRuleName': rule['ConfigRuleName'],
                                'AccountId': rule['AccountId'],
                                'AwsRegion': rule['AwsRegion'],
                                'ResourceType': result.get('EvaluationResultIdentifier', {}).get('EvaluationResultQualifier', {}).get('ResourceType'),
                                'ResourceId': result.get('EvaluationResultIdentifier', {}).get('EvaluationResultQualifier', {}).get('ResourceId'),
                                'ComplianceType': result.get('ComplianceType'),
                                'ResultRecordedTime': result.get('ResultRecordedTime').isoformat() if result.get('ResultRecordedTime') else None,
                                'ConformancePackNames': rule_conformance_packs  # Add conformance pack correlation
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
                        'ConformancePackNames': []
                    })
        
        print(f"Collected {len(non_compliant_details)} non-compliant details from {len(rules_by_account)} accounts")
        print(f"Created mappings for {len(pack_rule_mapping)} conformance packs")
        
        # Prepare data
        data = {
            'lastUpdated': datetime.now(timezone.utc).isoformat(),
            'accounts': accounts,
            'conformancePackSummary': compliance_summary.get('AggregateConformancePackComplianceSummaries', []),
            'conformancePackDetails': conformance_packs_detail,
            'rulesCompliance': rules_compliance,
            'nonCompliantDetails': non_compliant_details,
            'packRuleMapping': {k: list(v) for k, v in pack_rule_mapping.items()},  # Convert sets to lists for JSON
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
