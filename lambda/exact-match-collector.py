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
        
        # Create mapping of rule suffixes to conformance pack names by account
        suffix_to_pack_mapping = {}
        for pack in conformance_packs_detail:
            account_id = pack['AccountId']
            pack_name = pack['ConformancePackName']
            
            if account_id not in suffix_to_pack_mapping:
                suffix_to_pack_mapping[account_id] = {}
            
            # Extract pack identifier from pack name
            if pack_name == 'APRA-CPG-234-Compliance':
                # APRA pack doesn't follow the same naming pattern
                suffix_to_pack_mapping[account_id]['apra'] = pack_name
            else:
                # Extract the suffix from pack name (last part after final dash)
                pack_parts = pack_name.split('-')
                if len(pack_parts) > 0:
                    pack_suffix = pack_parts[-1]
                    suffix_to_pack_mapping[account_id][pack_suffix] = pack_name
        
        print(f"Created suffix mappings for {len(suffix_to_pack_mapping)} accounts")
        
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

        # Get ALL non-compliant rule findings with exact suffix matching
        non_compliant_details = []
        non_compliant_rules = [rule for rule in rules_compliance if rule.get('Compliance', {}).get('ComplianceType') == 'NON_COMPLIANT']
        
        print(f"Processing {len(non_compliant_rules)} non-compliant rules")
        
        # Process ALL non-compliant rules with exact matching
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
                
                # Extract rule suffix and match to conformance pack
                rule_name = rule['ConfigRuleName']
                account_id = rule['AccountId']
                specific_conformance_pack = None
                
                # Extract suffix from rule name
                if '-conformance-pack-' in rule_name:
                    rule_suffix = rule_name.split('-conformance-pack-')[-1]
                    
                    # Look up the conformance pack for this account and suffix
                    if account_id in suffix_to_pack_mapping:
                        account_mappings = suffix_to_pack_mapping[account_id]
                        
                        # Try direct suffix match first
                        if rule_suffix in account_mappings:
                            specific_conformance_pack = account_mappings[rule_suffix]
                        else:
                            # Try to find a pack suffix that matches part of the rule suffix
                            for pack_suffix, pack_name in account_mappings.items():
                                if pack_suffix in rule_suffix or rule_suffix in pack_suffix:
                                    specific_conformance_pack = pack_name
                                    break
                else:
                    # Rules without conformance pack suffix might be APRA rules
                    if account_id in suffix_to_pack_mapping and 'apra' in suffix_to_pack_mapping[account_id]:
                        specific_conformance_pack = suffix_to_pack_mapping[account_id]['apra']
                
                # Get ALL evaluation results for this rule
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
                            'ConformancePackName': specific_conformance_pack,
                            'RuleSuffix': rule_suffix if '-conformance-pack-' in rule_name else None
                        })
            except Exception as e:
                print(f"Could not get details for rule {rule['ConfigRuleName']} in account {rule['AccountId']}: {e}")
                # Add basic info even if details fail
                rule_suffix = rule['ConfigRuleName'].split('-conformance-pack-')[-1] if '-conformance-pack-' in rule['ConfigRuleName'] else None
                specific_conformance_pack = None
                
                if rule['AccountId'] in suffix_to_pack_mapping and rule_suffix:
                    account_mappings = suffix_to_pack_mapping[rule['AccountId']]
                    if rule_suffix in account_mappings:
                        specific_conformance_pack = account_mappings[rule_suffix]
                
                non_compliant_details.append({
                    'ConfigRuleName': rule['ConfigRuleName'],
                    'AccountId': rule['AccountId'],
                    'AwsRegion': rule['AwsRegion'],
                    'ResourceType': 'Unknown',
                    'ResourceId': 'Unknown',
                    'ComplianceType': 'NON_COMPLIANT',
                    'ResultRecordedTime': None,
                    'ConformancePackName': specific_conformance_pack,
                    'RuleSuffix': rule_suffix
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
            'suffixToPackMapping': suffix_to_pack_mapping,
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
