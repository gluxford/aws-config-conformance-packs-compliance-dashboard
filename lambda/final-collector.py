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

        # Get ALL non-compliant rules and their details
        non_compliant_rules = [rule for rule in rules_compliance if rule.get('Compliance', {}).get('ComplianceType') == 'NON_COMPLIANT']
        
        # Process rules in parallel to get detailed findings
        def get_rule_details(rule):
            local_config_client = boto3.client('config')
            rule_details = []
            
            try:
                # Get ALL results for this rule using pagination
                paginator = local_config_client.get_paginator('get_aggregate_compliance_details_by_config_rule')
                page_iterator = paginator.paginate(
                    ConfigurationAggregatorName=aggregator_name,
                    ConfigRuleName=rule['ConfigRuleName'],
                    AccountId=rule['AccountId'],
                    AwsRegion=rule['AwsRegion']
                )
                
                # Process ALL pages of results
                for page in page_iterator:
                    for result in page.get('AggregateEvaluationResults', []):
                        if result.get('ComplianceType') == 'NON_COMPLIANT':
                            rule_details.append({
                                'ConfigRuleName': rule['ConfigRuleName'],
                                'AccountId': rule['AccountId'],
                                'AwsRegion': rule['AwsRegion'],
                                'ResourceType': result.get('EvaluationResultIdentifier', {}).get('EvaluationResultQualifier', {}).get('ResourceType'),
                                'ResourceId': result.get('EvaluationResultIdentifier', {}).get('EvaluationResultQualifier', {}).get('ResourceId'),
                                'ComplianceType': result.get('ComplianceType'),
                                'ResultRecordedTime': result.get('ResultRecordedTime').isoformat() if result.get('ResultRecordedTime') else None,
                                'ConformancePackName': None  # Will be set after correlation
                            })
                        
            except Exception as e:
                print(f"Error getting details for rule {rule['ConfigRuleName']}: {e}")
                # Add basic info even if details fail
                rule_details.append({
                    'ConfigRuleName': rule['ConfigRuleName'],
                    'AccountId': rule['AccountId'],
                    'AwsRegion': rule['AwsRegion'],
                    'ResourceType': 'Unknown',
                    'ResourceId': 'Unknown',
                    'ComplianceType': 'NON_COMPLIANT',
                    'ResultRecordedTime': None,
                    'ConformancePackName': None
                })
            
            return rule_details

        # Process rules in parallel
        all_non_compliant_details = []
        print(f"Processing {len(non_compliant_rules)} rules in parallel...")
        
        with ThreadPoolExecutor(max_workers=8) as executor:
            future_to_rule = {executor.submit(get_rule_details, rule): rule for rule in non_compliant_rules}
            
            completed = 0
            for future in as_completed(future_to_rule):
                try:
                    rule_details = future.result()
                    all_non_compliant_details.extend(rule_details)
                    completed += 1
                    
                    if completed % 50 == 0:
                        print(f"Processed {completed}/{len(non_compliant_rules)} rules, collected {len(all_non_compliant_details)} details in {time.time() - start_time:.2f} seconds")
                        
                except Exception as e:
                    print(f"Error processing rule: {e}")

        print(f"Collected {len(all_non_compliant_details)} non-compliant details in {time.time() - start_time:.2f} seconds")
        
        # NOW correlate each finding with its conformance pack
        # Create a mapping of account+pack to the pack name
        pack_mapping = {}
        for pack in conformance_packs_detail:
            pack_mapping[f"{pack['AccountId']}:{pack['ConformancePackName']}"] = pack['ConformancePackName']
        
        # For each finding, determine which conformance pack it belongs to
        for detail in all_non_compliant_details:
            account_id = detail['AccountId']
            
            # Find all conformance packs for this account
            account_packs = [p for p in conformance_packs_detail if p['AccountId'] == account_id]
            
            # If there's only one pack for this account, assign it
            if len(account_packs) == 1:
                detail['ConformancePackName'] = account_packs[0]['ConformancePackName']
            else:
                # Multiple packs - need to determine which one based on the rule
                # This is where we distribute rules across packs for the same account
                rule_name = detail['ConfigRuleName'].lower()
                
                # Find NIST pack first (highest priority for encryption/logging rules)
                nist_pack = next((p for p in account_packs if 'NIST' in p['ConformancePackName']), None)
                if nist_pack and ('encryption' in rule_name or 'kms' in rule_name or 'logging' in rule_name or 'api-gw' in rule_name):
                    detail['ConformancePackName'] = nist_pack['ConformancePackName']
                    continue
                
                # Find CIS pack for identity/access rules
                cis_pack = next((p for p in account_packs if 'CIS' in p['ConformancePackName']), None)
                if cis_pack and ('iam-password' in rule_name or 'root-account' in rule_name or 'mfa' in rule_name):
                    detail['ConformancePackName'] = cis_pack['ConformancePackName']
                    continue
                
                # Find Security Pillar pack for infrastructure rules
                security_pack = next((p for p in account_packs if 'Security-Pillar' in p['ConformancePackName']), None)
                if security_pack and ('s3-bucket' in rule_name or 'cloudtrail' in rule_name or 'vpc' in rule_name):
                    detail['ConformancePackName'] = security_pack['ConformancePackName']
                    continue
                
                # Find APRA pack for remaining rules
                apra_pack = next((p for p in account_packs if 'APRA' in p['ConformancePackName']), None)
                if apra_pack:
                    detail['ConformancePackName'] = apra_pack['ConformancePackName']
                    continue
                
                # Fallback to first available pack
                if account_packs:
                    detail['ConformancePackName'] = account_packs[0]['ConformancePackName']

        print(f"Correlated {len(all_non_compliant_details)} findings with conformance packs")
        
        # Prepare data
        data = {
            'lastUpdated': datetime.now(timezone.utc).isoformat(),
            'accounts': accounts,
            'conformancePackSummary': compliance_summary.get('AggregateConformancePackComplianceSummaries', []),
            'conformancePackDetails': conformance_packs_detail,
            'rulesCompliance': rules_compliance,
            'nonCompliantDetails': all_non_compliant_details,
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
