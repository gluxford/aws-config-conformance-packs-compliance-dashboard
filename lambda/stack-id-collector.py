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

        # Create mapping of rule suffixes to conformance packs by analyzing existing rules
        # Group rules by account and suffix to understand the pattern
        rule_suffix_to_pack = {}
        
        # Analyze non-compliant rules to build suffix mapping
        non_compliant_rules = [rule for rule in rules_compliance if rule.get('Compliance', {}).get('ComplianceType') == 'NON_COMPLIANT']
        
        # Group rules by account and suffix
        account_suffix_groups = {}
        for rule in non_compliant_rules:
            account_id = rule['AccountId']
            rule_name = rule['ConfigRuleName']
            
            if '-conformance-pack-' in rule_name:
                rule_suffix = rule_name.split('-conformance-pack-')[-1]
                
                if account_id not in account_suffix_groups:
                    account_suffix_groups[account_id] = {}
                if rule_suffix not in account_suffix_groups[account_id]:
                    account_suffix_groups[account_id][rule_suffix] = []
                
                account_suffix_groups[account_id][rule_suffix].append(rule_name)
        
        # For each account, try to map suffixes to conformance packs based on rule patterns
        for account_id, suffixes in account_suffix_groups.items():
            account_packs = [p for p in conformance_packs_detail if p['AccountId'] == account_id]
            
            for suffix, rule_names in suffixes.items():
                # Analyze rule names to determine which conformance pack they likely belong to
                rule_patterns = ' '.join(rule_names).lower()
                
                best_match_pack = None
                
                # Try to match based on rule content patterns
                if any(pattern in rule_patterns for pattern in ['iam-password', 'root-account', 'mfa-enabled']):
                    # CIS patterns
                    best_match_pack = next((p for p in account_packs if 'CIS' in p['ConformancePackName']), None)
                elif any(pattern in rule_patterns for pattern in ['s3-bucket', 'cloudtrail', 'vpc-flow']):
                    # Security Pillar patterns
                    best_match_pack = next((p for p in account_packs if 'Security-Pillar' in p['ConformancePackName']), None)
                elif any(pattern in rule_patterns for pattern in ['encryption', 'kms', 'api-gw', 'logging']):
                    # NIST patterns
                    best_match_pack = next((p for p in account_packs if 'NIST' in p['ConformancePackName']), None)
                else:
                    # Default to APRA or first available
                    best_match_pack = next((p for p in account_packs if 'APRA' in p['ConformancePackName']), None)
                    if not best_match_pack and account_packs:
                        best_match_pack = account_packs[0]
                
                if best_match_pack:
                    rule_suffix_to_pack[f"{account_id}:{suffix}"] = best_match_pack['ConformancePackName']
        
        print(f"Created {len(rule_suffix_to_pack)} suffix-to-pack mappings")
        
        # Get ALL non-compliant rule findings with stack ID based mapping
        non_compliant_details = []
        
        print(f"Processing {len(non_compliant_rules)} non-compliant rules")
        
        # Process ALL non-compliant rules with stack ID matching
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
                
                # Extract rule suffix (CloudFormation stack ID) and match to conformance pack
                rule_name = rule['ConfigRuleName']
                account_id = rule['AccountId']
                specific_conformance_pack = None
                rule_suffix = None
                
                if '-conformance-pack-' in rule_name:
                    rule_suffix = rule_name.split('-conformance-pack-')[-1]
                    mapping_key = f"{account_id}:{rule_suffix}"
                    
                    if mapping_key in rule_suffix_to_pack:
                        specific_conformance_pack = rule_suffix_to_pack[mapping_key]
                else:
                    # Rules without conformance pack suffix might be APRA rules
                    account_packs = [p for p in conformance_packs_detail if p['AccountId'] == account_id]
                    apra_pack = next((p for p in account_packs if 'APRA' in p['ConformancePackName']), None)
                    if apra_pack:
                        specific_conformance_pack = apra_pack['ConformancePackName']
                
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
                            'RuleSuffix': rule_suffix
                        })
            except Exception as e:
                print(f"Could not get details for rule {rule['ConfigRuleName']} in account {rule['AccountId']}: {e}")
                # Add basic info even if details fail
                rule_suffix = rule['ConfigRuleName'].split('-conformance-pack-')[-1] if '-conformance-pack-' in rule['ConfigRuleName'] else None
                mapping_key = f"{rule['AccountId']}:{rule_suffix}" if rule_suffix else None
                specific_conformance_pack = rule_suffix_to_pack.get(mapping_key) if mapping_key else None
                
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
            'ruleSuffixToPackMapping': rule_suffix_to_pack,
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
