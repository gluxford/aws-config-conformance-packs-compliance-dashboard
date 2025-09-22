        function renderConformancePackDetail(packName) {
            const packData = filteredData.conformancePackDetails ? 
                filteredData.conformancePackDetails.filter(p => p.ConformancePackName === packName) : [];
            const shortName = packName.replace(/^OrgConformsPack-AWS-QuickSetup-/, '').replace(/-[a-z0-9]+$/, '');

            const accountBreakdown = packData.map(pack => {
                const account = allData.accounts.find(a => a.accountId === pack.AccountId);
                const accountName = account ? account.accountName : pack.AccountId;
                const compliance = pack.Compliance || {};
                const percentage = compliance.TotalRuleCount > 0 ? 
                    Math.round((compliance.CompliantRuleCount / compliance.TotalRuleCount) * 100) : 0;
                
                return `
                    <div class="account-card">
                        <h4>${accountName}</h4>
                        <p><strong>Account ID:</strong> ${pack.AccountId}</p>
                        <p><strong>Compliance:</strong> ${percentage}% (${compliance.CompliantRuleCount || 0}/${compliance.TotalRuleCount || 0})</p>
                        <div class="progress-bar">
                            <div class="progress-fill" style="width: ${percentage}%;"></div>
                        </div>
                    </div>
                `;
            }).join('');

            // Get real non-compliant rules for this conformance pack
            const nonCompliantRules = filteredData.nonCompliantDetails ? 
                filteredData.nonCompliantDetails.filter(detail => {
                    // Check if this rule belongs to accounts that have this conformance pack
                    return packData.some(pack => pack.AccountId === detail.AccountId);
                }) : [];

            const rulesTable = nonCompliantRules.length > 0 ? `
                <h3>Non-Compliant Rules</h3>
                <table class="compliance-table">
                    <thead>
                        <tr>
                            <th>Rule Name</th>
                            <th>Account</th>
                            <th>Resource Type</th>
                            <th>Status</th>
                            <th>Description</th>
                            <th>Remediation Resources</th>
                        </tr>
                    </thead>
                    <tbody>
                        ${nonCompliantRules.map(rule => {
                            const account = allData.accounts.find(a => a.accountId === rule.AccountId);
                            const accountName = account ? account.accountName : rule.AccountId;
                            const remediation = remediationSuggestions[rule.ConfigRuleName] || {};
                            
                            return `
                                <tr>
                                    <td>${rule.ConfigRuleName}</td>
                                    <td>${accountName}</td>
                                    <td>${rule.ResourceType || 'N/A'}</td>
                                    <td><span class="status-non-compliant">NON_COMPLIANT</span></td>
                                    <td>${remediation.description || 'No description available'}</td>
                                    <td>
                                        ${remediation.documentation ? 
                                            `<a href="${remediation.documentation}" target="_blank" class="remediation-link">📖 Documentation</a>` : 
                                            ''
                                        }
                                        ${remediation.ssm ? 
                                            `<a href="https://console.aws.amazon.com/systems-manager/documents/${remediation.ssm}" target="_blank" class="remediation-link">🔧 SSM Document</a>` : 
                                            ''
                                        }
                                        ${remediation.scp ? 
                                            `<a href="${remediation.scp}" target="_blank" class="remediation-link">🛡️ SCP Example</a>` : 
                                            ''
                                        }
                                    </td>
                                </tr>
                            `;
                        }).join('')}
                    </tbody>
                </table>
            ` : '<p>All rules are compliant for this conformance pack in the selected accounts.</p>';

            return `
                <h3>${shortName} - Detailed View</h3>
                <div class="accounts-grid">
                    ${accountBreakdown}
                </div>
                ${rulesTable}
            `;
        }

        function showTab(tabId) {
            // Hide all tab contents
            document.querySelectorAll('.tab-content').forEach(content => {
                content.classList.remove('active');
            });
            
            // Remove active class from all tabs
            document.querySelectorAll('.tab').forEach(tab => {
                tab.classList.remove('active');
            });
            
            // Show selected tab content
            document.getElementById(tabId).classList.add('active');
            
            // Add active class to clicked tab
            event.target.classList.add('active');
        }

        function exportToExcel() {
            if (!filteredData.nonCompliantDetails) {
                alert('No compliance data available for export');
                return;
            }

            // Prepare data for Excel export
            const exportData = filteredData.nonCompliantDetails.map(rule => {
                const account = allData.accounts.find(a => a.accountId === rule.AccountId);
                const remediation = remediationSuggestions[rule.ConfigRuleName] || {};
                
                return {
                    'Rule Name': rule.ConfigRuleName,
                    'Account Name': account ? account.accountName : rule.AccountId,
                    'Account ID': rule.AccountId,
                    'Resource Type': rule.ResourceType || 'N/A',
                    'Resource ID': rule.ResourceId || 'N/A',
                    'Status': rule.ComplianceType,
                    'Region': rule.AwsRegion,
                    'Description': remediation.description || 'No description available',
                    'Documentation Link': remediation.documentation || '',
                    'SSM Document': remediation.ssm || '',
                    'SCP Example': remediation.scp || '',
                    'Last Recorded': rule.ResultRecordedTime || ''
                };
            });

            // Create workbook and worksheet
            const wb = XLSX.utils.book_new();
            const ws = XLSX.utils.json_to_sheet(exportData);
            
            // Add worksheet to workbook
            XLSX.utils.book_append_sheet(wb, ws, 'Non-Compliant Rules');
            
            // Add summary sheet
            const summaryData = [
                ['Metric', 'Value'],
                ['Total Rules', filteredData.organizationCompliance.totalRules],
                ['Compliant Rules', filteredData.organizationCompliance.compliantRules],
                ['Non-Compliant Rules', filteredData.organizationCompliance.nonCompliantRules],
                ['Compliance Percentage', filteredData.organizationCompliance.compliancePercentage + '%'],
                ['Export Date', new Date().toLocaleString()]
            ];
            const summaryWs = XLSX.utils.aoa_to_sheet(summaryData);
            XLSX.utils.book_append_sheet(wb, summaryWs, 'Summary');
            
            // Save file
            const fileName = `AWS_Config_Compliance_${new Date().toISOString().split('T')[0]}.xlsx`;
            XLSX.writeFile(wb, fileName);
        }

        function exportToPowerPoint() {
            if (!window.PptxGenJS) {
                alert('PowerPoint export library not loaded');
                return;
            }

            const pptx = new PptxGenJS();
            
            // Title slide
            const titleSlide = pptx.addSlide();
            titleSlide.addText('AWS Config Compliance Report', {
                x: 1, y: 1, w: 8, h: 1.5,
                fontSize: 32, bold: true, color: '363636'
            });
            titleSlide.addText(`Generated: ${new Date().toLocaleDateString()}`, {
                x: 1, y: 2.5, w: 8, h: 0.5,
                fontSize: 16, color: '666666'
            });

            // Executive Summary slide
            const summarySlide = pptx.addSlide();
            summarySlide.addText('Executive Summary', {
                x: 0.5, y: 0.5, w: 9, h: 0.8,
                fontSize: 24, bold: true, color: '363636'
            });
            
            const summaryData = [
                ['Metric', 'Value'],
                ['Overall Compliance', `${filteredData.organizationCompliance.compliancePercentage}%`],
                ['Total Rules Evaluated', filteredData.organizationCompliance.totalRules.toString()],
                ['Compliant Rules', filteredData.organizationCompliance.compliantRules.toString()],
                ['Non-Compliant Rules', filteredData.organizationCompliance.nonCompliantRules.toString()],
                ['Accounts Monitored', allData.accounts.length.toString()]
            ];
            
            summarySlide.addTable(summaryData, {
                x: 1, y: 1.5, w: 8, h: 3,
                fontSize: 14,
                border: {pt: 1, color: 'CFCFCF'}
            });

            // Account breakdown slide
            if (filteredData.conformancePackDetails) {
                const accountSlide = pptx.addSlide();
                accountSlide.addText('Account Compliance Breakdown', {
                    x: 0.5, y: 0.5, w: 9, h: 0.8,
                    fontSize: 24, bold: true, color: '363636'
                });

                const accountData = [['Account Name', 'Account ID', 'Compliance %']];
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
                    accountData.push([account.accountName, account.accountId, `${percentage}%`]);
                });

                accountSlide.addTable(accountData, {
                    x: 1, y: 1.5, w: 8, h: 4,
                    fontSize: 12,
                    border: {pt: 1, color: 'CFCFCF'}
                });
            }

            // Save PowerPoint
            const fileName = `AWS_Config_Compliance_Report_${new Date().toISOString().split('T')[0]}.pptx`;
            pptx.writeFile(fileName);
        }

        // Load data on page load
        loadData();
        
        // Refresh data every 5 minutes
        setInterval(loadData, 300000);
    </script>
</body>
</html>
