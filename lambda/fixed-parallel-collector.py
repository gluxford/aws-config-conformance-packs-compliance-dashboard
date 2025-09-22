import json
import boto3
import os
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed
import time

def lambda_handler(event, context):
    config_client = boto3.client('config')
    s3_client = boto3.client('s3')
    org_client = boto3.client('organizations')
    
    bucket = os.environ['DASHBOARD_BUCKET']
    aggregator_name = os.environ['CONFIG_AGGREGATOR_NAME']
    
    start_time = time.time()
    
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

        print(f"Initial data collection took {time.time() - start_time:.2f} seconds")

        # Create rule suffix to conformance pack mapping
        rule_suffix_to_pack = {}
        non_compliant_rules = [rule for rule in rules_compliance if rule.get('Compliance', {}).get('ComplianceType') == 'NON_COMPLIANT']
        
        # Build mapping by analyzing rule patterns per account
        for rule in non_compliant_rules:
            account_id = rule['AccountId']
            rule_name = rule['ConfigRuleName']
            
            if '-conformance-pack-' in rule_name:
                rule_suffix = rule_name.split('-conformance-pack-')[-1]
                mapping_key = f"{account_id}:{rule_suffix}"
                
                if mapping_key not in rule_suffix_to_pack:
                    account_packs = [p for p in conformance_packs_detail if p['AccountId'] == account_id]
                    
                    # Pattern-based matching for conformance pack assignment
                    if 'iam-password' in rule_name or 'root-account' in rule_name or 'mfa-enabled' in rule_name:
                        pack = next((p for p in account_packs if 'CIS' in p['ConformancePackName']), None)
                    elif 's3-bucket' in rule_name or 'cloudtrail' in rule_name or 'vpc-flow' in rule_name:
                        pack = next((p for p in account_packs if 'Security-Pillar' in p['ConformancePackName']), None)
                    elif 'encryption' in rule_name or 'kms' in rule_name or 'api-gw' in rule_name or 'logging' in rule_name:
                        pack = next((p for p in account_packs if 'NIST' in p['ConformancePackName']), None)
                    else:
                        pack = next((p for p in account_packs if 'APRA' in p['ConformancePackName']), None)
                    
                    if pack:
                        rule_suffix_to_pack[mapping_key] = pack['ConformancePackName']

        print(f"Created {len(rule_suffix_to_pack)} suffix mappings in {time.time() - start_time:.2f} seconds")

        # Parallel processing function for rule details
        def get_rule_details(rule):
            local_config_client = boto3.client('config')
            rule_details = []
            
            try:
                details_response = local_config_client.get_aggregate_compliance_details_by_config_rule(
                    ConfigurationAggregatorName=aggregator_name,
                    ConfigRuleName=rule['ConfigRuleName'],
                    AccountId=rule['AccountId'],
                    AwsRegion=rule['AwsRegion'],
                    MaxResults=10
                )
                
                # Get conformance pack mapping - fix variable scope
                rule_name = rule['ConfigRuleName']
                account_id = rule['AccountId']
                rule_suffix = None
                specific_conformance_pack = None
                
                if '-conformance-pack-' in rule_name:
                    rule_suffix = rule_name.split('-conformance-pack-')[-1]
                    mapping_key = f"{account_id}:{rule_suffix}"
                    specific_conformance_pack = rule_suffix_to_pack.get(mapping_key)
                else:
                    # APRA rules without conformance pack suffix
                    account_packs = [p for p in conformance_packs_detail if p['AccountId'] == account_id]
                    apra_pack = next((p for p in account_packs if 'APRA' in p['ConformancePackName']), None)
                    if apra_pack:
                        specific_conformance_pack = apra_pack['ConformancePackName']
                
                # Process results
                for result in details_response.get('AggregateEvaluationResults', []):
                    if result.get('ComplianceType') == 'NON_COMPLIANT':
                        rule_details.append({
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
                # Add basic info if API call fails - fix variable scope
                rule_name = rule['ConfigRuleName']
                account_id = rule['AccountId']
                rule_suffix = rule_name.split('-conformance-pack-')[-1] if '-conformance-pack-' in rule_name else None
                mapping_key = f"{account_id}:{rule_suffix}" if rule_suffix else None
                specific_conformance_pack = rule_suffix_to_pack.get(mapping_key) if mapping_key else None
                
                rule_details.append({
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
            
            return rule_details

        # Process rules in parallel with limited concurrency
        non_compliant_details = []
        print(f"Processing {len(non_compliant_rules)} rules in parallel...")
        
        with ThreadPoolExecutor(max_workers=8) as executor:  # Reduced workers to avoid throttling
            future_to_rule = {executor.submit(get_rule_details, rule): rule for rule in non_compliant_rules}
            
            completed = 0
            for future in as_completed(future_to_rule):
                try:
                    rule_details = future.result()
                    non_compliant_details.extend(rule_details)
                    completed += 1
                    
                    if completed % 50 == 0:
                        print(f"Processed {completed}/{len(non_compliant_rules)} rules in {time.time() - start_time:.2f} seconds")
                        
                except Exception as e:
                    print(f"Error processing rule: {e}")

        print(f"Collected {len(non_compliant_details)} non-compliant details in {time.time() - start_time:.2f} seconds")
        
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
            'processingTimeSeconds': round(time.time() - start_time, 2),
            'remediationSuggestions': {}
        }
        
        # Upload to S3
        s3_client.put_object(
            Bucket=bucket,
            Key='data/compliance-summary.json',
            Body=json.dumps(data, indent=2, default=str),
            ContentType='application/json'
        )
        
        total_time = time.time() - start_time
        print(f"Total processing time: {total_time:.2f} seconds")
        
        return {
            'statusCode': 200,
            'body': json.dumps(f'Data collection completed in {total_time:.2f} seconds')
        }
        
    except Exception as e:
        print(f"Error: {str(e)}")
        return {
            'statusCode': 500,
            'body': json.dumps(f'Error: {str(e)}')
        }
