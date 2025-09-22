    <script>
        let allData = {};
        let filteredData = {};
        let selectedAccounts = [];
        
        // Enhanced remediation suggestions mapping
        const remediationSuggestions = {
            'root-access-key-check': {
                description: 'Remove root access keys to improve security',
                documentation: 'https://docs.aws.amazon.com/IAM/latest/UserGuide/id_root-user.html#id_root-user_manage_add-key',
                ssm: 'AWSConfigRemediation-RemoveRootAccessKeys',
                scp: 'https://docs.aws.amazon.com/organizations/latest/userguide/orgs_manage_policies_scps_examples.html#example-scp-deny-root-user'
            },
            'mfa-enabled-for-iam-console-access': {
                description: 'Enable MFA for IAM console access',
                documentation: 'https://docs.aws.amazon.com/IAM/latest/UserGuide/id_credentials_mfa_enable.html',
                ssm: 'AWSConfigRemediation-EnableMFAForIAMUser'
            },
            'iam-password-policy': {
                description: 'Configure strong IAM password policy',
                documentation: 'https://docs.aws.amazon.com/IAM/latest/UserGuide/id_credentials_passwords_account-policy.html',
                ssm: 'AWSConfigRemediation-SetIAMPasswordPolicy'
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
            'encrypted-volumes': {
                description: 'Enable EBS volume encryption',
                documentation: 'https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/EBSEncryption.html',
                ssm: 'AWSConfigRemediation-EncryptEBSVolume'
            },
            'cloudtrail-enabled': {
                description: 'Enable CloudTrail logging',
                documentation: 'https://docs.aws.amazon.com/awscloudtrail/latest/userguide/cloudtrail-create-and-update-a-trail.html',
                ssm: 'AWSConfigRemediation-CreateCloudTrail'
            },
            'vpc-flow-logs-enabled': {
                description: 'Enable VPC Flow Logs',
                documentation: 'https://docs.aws.amazon.com/vpc/latest/userguide/flow-logs.html',
                ssm: 'AWSConfigRemediation-EnableVPCFlowLogs'
            }
        };

        async function loadData() {
            try {
                document.getElementById('loading').style.display = 'block';
                document.getElementById('overview-content').style.display = 'none';

                const response = await fetch('./data/compliance-summary.json');
                if (!response.ok) throw new Error('Failed to fetch compliance data');
                allData = await response.json();
                
                // Initialize filtered data
                filteredData = JSON.parse(JSON.stringify(allData));
                
                populateAccountFilter();
                renderOverview();
                createConformancePackTabs();
                
                document.getElementById('last-updated').textContent = 
                    `Last updated: ${new Date(allData.lastUpdated).toLocaleString()}`;
                
                document.getElementById('loading').style.display = 'none';
                document.getElementById('overview-content').style.display = 'block';
                
            } catch (error) {
                console.error('Error loading data:', error);
                document.getElementById('loading').innerHTML = `<div class="error">Error loading data: ${error.message}</div>`;
            }
        }

        function populateAccountFilter() {
            const select = document.getElementById('account-filter');
            select.innerHTML = '<option value="">All Accounts</option>';
            
            allData.accounts.forEach(account => {
                const option = document.createElement('option');
                option.value = account.accountId;
                option.textContent = `${account.accountName} (${account.accountId})`;
                select.appendChild(option);
            });
        }

        function applyFilters() {
            const accountFilter = document.getElementById('account-filter').value;
            
            if (accountFilter) {
                selectedAccounts = [accountFilter];
                // Filter data based on selected account
                filteredData = {
                    ...allData,
                    conformancePackDetails: allData.conformancePackDetails ? 
                        allData.conformancePackDetails.filter(p => p.AccountId === accountFilter) : [],
                    nonCompliantDetails: allData.nonCompliantDetails ? 
                        allData.nonCompliantDetails.filter(d => d.AccountId === accountFilter) : []
                };
            } else {
                selectedAccounts = [];
                filteredData = JSON.parse(JSON.stringify(allData));
            }
            
            renderOverview();
            updateAllTabs();
        }

        function renderOverview() {
            renderMetrics();
            renderComplianceChart();
            renderAccountsBreakdown();
            renderConformancePacksBreakdown();
        }

        function renderMetrics() {
            const org = filteredData.organizationCompliance;
            const totalPacks = filteredData.conformancePackDetails ? filteredData.conformancePackDetails.length : 0;
            const uniquePacks = filteredData.conformancePackDetails ? 
                [...new Set(filteredData.conformancePackDetails.map(p => p.ConformancePackName))].length : 0;
            const accountCount = selectedAccounts.length > 0 ? selectedAccounts.length : allData.accounts.length;

            document.getElementById('metrics').innerHTML = `
                <div class="metric-card">
                    <div class="metric-value">${org.compliancePercentage}%</div>
                    <div class="metric-label">Overall Compliance</div>
                </div>
                <div class="metric-card">
                    <div class="metric-value">${org.totalRules}</div>
                    <div class="metric-label">Total Rules</div>
                </div>
                <div class="metric-card">
                    <div class="metric-value">${org.compliantRules}</div>
                    <div class="metric-label">Compliant Rules</div>
                </div>
                <div class="metric-card">
                    <div class="metric-value">${org.nonCompliantRules}</div>
                    <div class="metric-label">Non-Compliant Rules</div>
                </div>
                <div class="metric-card">
                    <div class="metric-value">${uniquePacks}</div>
                    <div class="metric-label">Conformance Packs</div>
                </div>
                <div class="metric-card">
                    <div class="metric-value">${accountCount}</div>
                    <div class="metric-label">Accounts</div>
                </div>
            `;
        }

        function renderComplianceChart() {
            const ctx = document.getElementById('complianceChart').getContext('2d');
            const org = filteredData.organizationCompliance;

            // Clear existing chart
            if (window.complianceChart) {
                window.complianceChart.destroy();
            }

            window.complianceChart = new Chart(ctx, {
                type: 'doughnut',
                data: {
                    labels: ['Compliant', 'Non-Compliant'],
                    datasets: [{
                        data: [org.compliantRules, org.nonCompliantRules],
                        backgroundColor: ['#22c55e', '#ef4444'],
                        borderWidth: 0
                    }]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: {
                        legend: {
                            labels: {
                                color: '#e0e6ed'
                            }
                        }
                    }
                }
            });
        }

        function renderAccountsBreakdown() {
            if (!filteredData.conformancePackDetails) {
                document.getElementById('accounts').innerHTML = '<p>Account breakdown will be available once conformance pack details are loaded.</p>';
                return;
            }

            const accountCompliance = {};
            const accountsToShow = selectedAccounts.length > 0 ? 
                allData.accounts.filter(a => selectedAccounts.includes(a.accountId)) : 
                allData.accounts;
            
            accountsToShow.forEach(account => {
                const accountPacks = filteredData.conformancePackDetails.filter(p => p.AccountId === account.accountId);
                let totalCompliant = 0;
                let totalRules = 0;
                
                accountPacks.forEach(pack => {
                    totalCompliant += pack.Compliance?.CompliantRuleCount || 0;
                    totalRules += pack.Compliance?.TotalRuleCount || 0;
                });
                
                const percentage = totalRules > 0 ? Math.round((totalCompliant / totalRules) * 100) : 0;
                
                accountCompliance[account.accountId] = {
                    name: account.accountName,
                    compliant: totalCompliant,
                    total: totalRules,
                    percentage
                };
            });

            const accountsHtml = Object.entries(accountCompliance).map(([accountId, data]) => `
                <div class="account-card">
                    <h4>${data.name}</h4>
                    <p><strong>Account ID:</strong> ${accountId}</p>
                    <p><strong>Compliance:</strong> ${data.percentage}% (${data.compliant}/${data.total})</p>
                    <div class="progress-bar">
                        <div class="progress-fill" style="width: ${data.percentage}%;"></div>
                    </div>
                </div>
            `).join('');

            document.getElementById('accounts').innerHTML = accountsHtml;
        }

        function renderConformancePacksBreakdown() {
            if (!filteredData.conformancePackDetails) {
                document.getElementById('conformance-packs').innerHTML = '<p>Conformance pack details will be available once data is loaded.</p>';
                return;
            }

            const packCompliance = {};
            
            filteredData.conformancePackDetails.forEach(pack => {
                if (!packCompliance[pack.ConformancePackName]) {
                    packCompliance[pack.ConformancePackName] = {
                        compliant: 0,
                        total: 0,
                        accounts: new Set()
                    };
                }
                
                packCompliance[pack.ConformancePackName].compliant += pack.Compliance?.CompliantRuleCount || 0;
                packCompliance[pack.ConformancePackName].total += pack.Compliance?.TotalRuleCount || 0;
                packCompliance[pack.ConformancePackName].accounts.add(pack.AccountId);
            });

            const packsHtml = Object.entries(packCompliance).map(([packName, data]) => {
                const percentage = data.total > 0 ? Math.round((data.compliant / data.total) * 100) : 0;
                const shortName = packName.replace(/^OrgConformsPack-AWS-QuickSetup-/, '').replace(/-[a-z0-9]+$/, '');
                
                return `
                    <div class="account-card">
                        <h4>${shortName}</h4>
                        <p><strong>Accounts:</strong> ${data.accounts.size}</p>
                        <p><strong>Compliance:</strong> ${percentage}% (${data.compliant}/${data.total})</p>
                        <div class="progress-bar">
                            <div class="progress-fill" style="width: ${percentage}%;"></div>
                        </div>
                    </div>
                `;
            }).join('');

            document.getElementById('conformance-packs').innerHTML = packsHtml;
        }

        function createConformancePackTabs() {
            if (!allData.conformancePackDetails) return;
            
            const uniquePacks = [...new Set(allData.conformancePackDetails.map(p => p.ConformancePackName))];
            const tabsContainer = document.getElementById('tabs');
            
            // Remove existing pack tabs
            const existingTabs = tabsContainer.querySelectorAll('.tab:not([onclick*="overview"])');
            existingTabs.forEach(tab => tab.remove());
            
            uniquePacks.forEach(packName => {
                const shortName = packName.replace(/^OrgConformsPack-AWS-QuickSetup-/, '').replace(/-[a-z0-9]+$/, '');
                const tabId = packName.replace(/[^a-zA-Z0-9]/g, '-');
                
                // Add tab button
                const tabButton = document.createElement('button');
                tabButton.className = 'tab';
                tabButton.textContent = shortName;
                tabButton.onclick = () => showTab(tabId);
                tabsContainer.appendChild(tabButton);
                
                // Remove existing tab content if it exists
                const existingContent = document.getElementById(tabId);
                if (existingContent) existingContent.remove();
                
                // Add tab content
                const tabContent = document.createElement('div');
                tabContent.id = tabId;
                tabContent.className = 'tab-content';
                tabContent.innerHTML = renderConformancePackDetail(packName);
                document.querySelector('.container').appendChild(tabContent);
            });
        }

        function updateAllTabs() {
            if (!allData.conformancePackDetails) return;
            
            const uniquePacks = [...new Set(allData.conformancePackDetails.map(p => p.ConformancePackName))];
            
            uniquePacks.forEach(packName => {
                const tabId = packName.replace(/[^a-zA-Z0-9]/g, '-');
                const tabContent = document.getElementById(tabId);
                if (tabContent) {
                    tabContent.innerHTML = renderConformancePackDetail(packName);
                }
            });
        }
