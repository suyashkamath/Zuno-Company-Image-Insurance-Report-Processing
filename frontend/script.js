// Enable/disable process button based on file input
document.getElementById('policy-file').addEventListener('change', function() {
    document.getElementById('process-button').disabled = !this.files.length;
});

// Tab switching
document.querySelectorAll('.tab-button').forEach(button => {
    button.addEventListener('click', () => {
        document.querySelectorAll('.tab-button').forEach(btn => btn.classList.remove('active'));
        document.querySelectorAll('.tab').forEach(tab => tab.classList.remove('active'));
        button.classList.add('active');
        document.getElementById(button.dataset.tab).classList.add('active');
    });
});

// Process button click
document.getElementById('process-button').addEventListener('click', async () => {
    const companyName = document.getElementById('company-name').value;
    const policyFile = document.getElementById('policy-file').files[0];
    if (!policyFile) return;

    document.getElementById('initial-message').classList.add('hidden');
    document.getElementById('processing-spinner').style.display = 'block';
    document.getElementById('error-message').classList.add('hidden');
    document.getElementById('success-message').classList.add('hidden');
    document.getElementById('results-container').classList.add('hidden');

    const formData = new FormData();
    formData.append('company_name', companyName);
    formData.append('policy_file', policyFile);

    try {
        console.log('🚀 Sending request to backend...');
        const response = await fetch('https://zuno-company-image-insurance-report.onrender.com/process', {
            method: 'POST',
            body: formData
        });

        console.log('📡 Response status:', response.status);
        
        const responseText = await response.text();
        console.log('📄 Response received (length):', responseText.length);

        document.getElementById('processing-spinner').style.display = 'none';

        if (!responseText || responseText.trim() === '') {
            throw new Error('Backend returned empty response. Please check if the FastAPI server is running.');
        }

        let result;
        try {
            result = JSON.parse(responseText);
        } catch (jsonError) {
            console.error('❌ JSON Parse Error:', jsonError);
            console.error('Response text:', responseText.substring(0, 500));
            throw new Error(`Backend returned invalid JSON: ${responseText.substring(0, 200)}`);
        }

        if (response.ok) {
            document.getElementById('success-message').textContent = '🎉 Processing completed successfully!';
            document.getElementById('success-message').classList.remove('hidden');
            document.getElementById('results-container').classList.remove('hidden');

            // Populate Final Results
            const resultsTableBody = document.getElementById('results-table-body');
            resultsTableBody.innerHTML = '';
            result.calculated_data.forEach(record => {
                const row = document.createElement('tr');
                row.innerHTML = `
    <td class="border border-gray-300 p-2">${record.segment || 'N/A'}</td>
    <td class="border border-gray-300 p-2">${record.location || 'N/A'}</td>
    <td class="border border-gray-300 p-2">${record['policy type'] || 'N/A'}</td>
    <td class="border border-gray-300 p-2">${record.payin || 'N/A'}</td>
    <td class="border border-gray-300 p-2">${record.location || 'N/A'}</td>
    <td class="border border-gray-300 p-2">${record.remark || ''}</td>
    <td class="border border-gray-300 p-2">${record['Calculated Payout'] || 'N/A'}</td>
    <td class="border border-gray-300 p-2">${record['Formula Used'] || 'N/A'}</td>
    <td class="border border-gray-300 p-2">${record['Rule Explanation'] || 'N/A'}</td>
`;
                resultsTableBody.appendChild(row);
            });

            // Populate Metrics
            document.getElementById('total-records').textContent = result.calculated_data.length;
            document.getElementById('avg-payin').textContent = result.avg_payin ? `${result.avg_payin}%` : '0.0%';
            document.getElementById('unique-segments').textContent = result.unique_segments || 0;
            document.getElementById('company-name-display').textContent = companyName;

            // Populate Formula Summary
            const formulaSummary = document.getElementById('formula-summary');
            formulaSummary.innerHTML = '';
            Object.entries(result.formula_summary || {}).forEach(([formula, count]) => {
                const li = document.createElement('li');
                li.textContent = `${formula}: Applied to ${count} record(s)`;
                formulaSummary.appendChild(li);
            });

            // Populate Extracted Text
            document.getElementById('extracted-text').value = result.extracted_text || '';

            // Populate Formula Table
            const formulaTableBody = document.getElementById('formula-table-body');
            formulaTableBody.innerHTML = '';
            result.formula_data.forEach(rule => {
                const row = document.createElement('tr');
                row.innerHTML = `
                    <td class="border border-gray-300 p-2">${rule.LOB}</td>
                    <td class="border border-gray-300 p-2">${rule.SEGMENT}</td>
                    <td class="border border-gray-300 p-2">${rule.INSURER}</td>
                    <td class="border border-gray-300 p-2">${rule.PO}</td>
                    <td class="border border-gray-300 p-2">${rule.REMARKS}</td>
                `;
                formulaTableBody.appendChild(row);
            });

            // Populate Parsed Data
            document.getElementById('parsed-data').textContent = JSON.stringify(result.parsed_data, null, 2);

            // Populate Calculated Data and Rule Explanations
            document.getElementById('calculated-data').textContent = JSON.stringify(result.calculated_data, null, 2);
            const ruleExplanations = document.getElementById('rule-explanations');
            ruleExplanations.innerHTML = '';
            result.calculated_data.forEach((record, index) => {
                const div = document.createElement('div');
                div.className = 'border border-gray-300 p-4 mb-2 rounded';
                div.innerHTML = `
                    <h3 class="font-semibold">Record ${index + 1}: ${record.Segment || 'Unknown'}</h3>
                    <p><strong>Payin</strong>: ${record.Payin || 'N/A'}</p>
                    <p><strong>Calculated Payout</strong>: ${record['Calculated Payout'] || 'N/A'}</p>
                    <p><strong>Formula Used</strong>: ${record['Formula Used'] || 'N/A'}</p>
                    <p><strong>Rule Explanation</strong>: ${record['Rule Explanation'] || 'N/A'}</p>
                `;
                ruleExplanations.appendChild(div);
            });

            // Set up download buttons
            document.getElementById('download-excel').onclick = () => {
                const link = document.createElement('a');
                link.href = `data:application/vnd.openxmlformats-officedocument.spreadsheetml.sheet;base64,${result.excel_data}`;
                link.download = `${companyName}_processed_policies.xlsx`;
                link.click();
            };
            document.getElementById('download-json').onclick = () => {
                const link = document.createElement('a');
                link.href = `data:application/json,${encodeURIComponent(JSON.stringify(result.calculated_data, null, 2))}`;
                link.download = `${companyName}_processed_data.json`;
                link.click();
            };
            document.getElementById('download-csv').onclick = () => {
                const link = document.createElement('a');
                link.href = `data:text/csv,${encodeURIComponent(result.csv_data)}`;
                link.download = `${companyName}_processed_policies.csv`;
                link.click();
            };
        } else {
            document.getElementById('error-message').textContent = `❌ ${result.error || 'Processing error'}`;
            document.getElementById('error-message').classList.remove('hidden');
        }
    } catch (e) {
        document.getElementById('processing-spinner').style.display = 'none';
        console.error('Full error:', e);
        document.getElementById('error-message').textContent = `❌ Error: ${e.message}`;
        document.getElementById('error-message').classList.remove('hidden');
    }
});
