        function renderComplianceChart() {
            const ctx = document.getElementById('complianceChart').getContext('2d');
            const org = filteredData.organizationCompliance;

            // Clear existing chart safely
            if (window.complianceChart && typeof window.complianceChart.destroy === 'function') {
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
