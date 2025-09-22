        // Enhanced remediation suggestions with rule matching
        function getRemediationForRule(ruleName) {
            // Remove conformance pack suffixes and normalize rule names
            const normalizedRule = ruleName
                .replace(/-conformance-pack-[a-z0-9]+$/i, '')
                .replace(/-[a-z0-9]{8,}$/i, '')
                .toLowerCase();
            
            const remediationMap = {
                'iam-password-policy': {
                    description: 'Configure strong IAM password policy with minimum requirements',
                    documentation: 'https://docs.aws.amazon.com/IAM/latest/UserGuide/id_credentials_passwords_account-policy.html',
                    ssm: 'AWSConfigRemediation-SetIAMPasswordPolicy'
                },
                'root-access-key-check': {
                    description: 'Remove root access keys to improve security',
                    documentation: 'https://docs.aws.amazon.com/IAM/latest/UserGuide/id_root-user.html#id_root-user_manage_add-key',
                    scp: 'https://docs.aws.amazon.com/organizations/latest/userguide/orgs_manage_policies_scps_examples.html#example-scp-deny-root-user'
                },
                'mfa-enabled-for-iam-console-access': {
                    description: 'Enable MFA for IAM console access',
                    documentation: 'https://docs.aws.amazon.com/IAM/latest/UserGuide/id_credentials_mfa_enable.html',
                    ssm: 'AWSConfigRemediation-EnableMFAForIAMUser'
                },
                'subnet-auto-assign-public-ip-disabled': {
                    description: 'Disable auto-assign public IP for subnets',
                    documentation: 'https://docs.aws.amazon.com/vpc/latest/userguide/vpc-ip-addressing.html#subnet-public-ip',
                    ssm: 'AWSConfigRemediation-DisableSubnetAutoAssignPublicIP'
                },
                's3-bucket-public-read-prohibited': {
                    description: 'Block S3 bucket public read access',
                    documentation: 'https://docs.aws.amazon.com/AmazonS3/latest/userguide/access-control-block-public-access.html',
                    ssm: 'AWSConfigRemediation-RemoveS3BucketPublicReadAccess'
                },
                's3-bucket-public-write-prohibited': {
                    description: 'Block S3 bucket public write access',
                    documentation: 'https://docs.aws.amazon.com/AmazonS3/latest/userguide/access-control-block-public-access.html',
                    ssm: 'AWSConfigRemediation-RemoveS3BucketPublicWriteAccess'
                },
                'cloudtrail-enabled': {
                    description: 'Enable CloudTrail logging for audit trail',
                    documentation: 'https://docs.aws.amazon.com/awscloudtrail/latest/userguide/cloudtrail-create-and-update-a-trail.html',
                    ssm: 'AWSConfigRemediation-CreateCloudTrail'
                },
                'vpc-flow-logs-enabled': {
                    description: 'Enable VPC Flow Logs for network monitoring',
                    documentation: 'https://docs.aws.amazon.com/vpc/latest/userguide/flow-logs.html',
                    ssm: 'AWSConfigRemediation-EnableVPCFlowLogs'
                },
                'encrypted-volumes': {
                    description: 'Enable EBS volume encryption',
                    documentation: 'https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/EBSEncryption.html',
                    ssm: 'AWSConfigRemediation-EncryptEBSVolume'
                }
            };
            
            // Try exact match first
            if (remediationMap[normalizedRule]) {
                return remediationMap[normalizedRule];
            }
            
            // Try partial matches
            for (const [key, value] of Object.entries(remediationMap)) {
                if (normalizedRule.includes(key) || key.includes(normalizedRule)) {
                    return value;
                }
            }
            
            // Default remediation
            return {
                description: 'Review AWS Config rule documentation for remediation steps',
                documentation: 'https://docs.aws.amazon.com/config/latest/developerguide/managed-rules-by-aws-config.html'
            };
        }
