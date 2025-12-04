const input = document.getElementById('input');
const searchButton = document.getElementById('search-btn');
const searchingText = document.getElementById('searching-text');
const resultsContainer = document.getElementById('results-container');
const downloadButton = document.getElementById('download-btn');
const summary = document.getElementById('summary');

let eventSource;
let searchingDots = 0;
let searchingInterval;

// Função para animar o texto "searching"
function animateSearching() {
    searchingDots = (searchingDots + 1) % 4;
    const dots = '.'.repeat(searchingDots);
    searchingText.textContent = `searching${dots}`;
}

searchButton.addEventListener('click', () => {
    const username = input.value.trim();
    if (!username) {
        alert('Please enter a username.');
        return;
    }
    
    // Reset UI
    resultsContainer.innerHTML = '<legend>Results</legend>';
    resultsContainer.style.display = 'block';
    searchingText.style.display = 'block';
    downloadButton.style.display = 'none';
    summary.style.display = 'none';
    searchButton.disabled = true;
    searchingDots = 0;
    
    // Iniciar animação
    searchingInterval = setInterval(animateSearching, 500);

    // URL encoding correto para o username
    const encodedUsername = encodeURIComponent(username);
    const url = `http://127.0.0.1:8000/search?username=${encodedUsername}`;
    console.log('Connecting to:', url);
    
    eventSource = new EventSource(url);

    eventSource.onmessage = (event) => {
        console.log('Message received:', event.data);
        const data = JSON.parse(event.data);
        console.log('Parsed data:', data);

        // Handle fatal errors from the backend
        if (data.error) {
            clearInterval(searchingInterval);
            const errorDiv = document.createElement('div');
            errorDiv.textContent = `Error: ${data.error}`;
            resultsContainer.appendChild(errorDiv);
            searchingText.style.display = 'none';
            searchButton.disabled = false;
            eventSource.close();
            return;
        }

        if (data.result) {
            console.log('Adding result:', data.result);
            const resultElement = document.createElement('div');
            const resultText = data.result;
            resultElement.textContent = resultText;

            // Add styling based on Sherlock's output prefixes
            if (resultText.startsWith('[+]')) {
                resultElement.className = 'result-found';
            } else if (resultText.startsWith('[-]') || resultText.startsWith('[!]')) {
                resultElement.className = 'result-not-found';
            }
            resultsContainer.appendChild(resultElement);
            // Auto-scroll to the bottom
            resultsContainer.scrollTop = resultsContainer.scrollHeight;
        }

        if (data.message === 'done') {
            console.log('Search completed');
            clearInterval(searchingInterval);
            searchingText.style.display = 'none';
            searchButton.disabled = false;
            
            // if backend provided a download URL, show download button
            if (data.download) {
                // full absolute URL for the download
                const downloadUrl = `http://127.0.0.1:8000${data.download}`;
                downloadButton.dataset.downloadUrl = downloadUrl;
                downloadButton.style.display = 'block';

                // show summary
                const positiveCount = data.count || 0;
                summary.textContent = `✓ Found ${positiveCount} positive result${positiveCount === 1 ? '' : 's'}`;
                summary.style.display = 'block';
            } else {
                summary.textContent = '✓ Search completed - No results found';
                summary.style.display = 'block';
            }
            eventSource.close();
        }
    };

    eventSource.onerror = () => {
        clearInterval(searchingInterval);
        const errorDiv = document.createElement('div');
        errorDiv.textContent = 'Error: Connection to the backend failed. Ensure the server is running on http://127.0.0.1:8000';
        resultsContainer.appendChild(errorDiv);
        searchingText.style.display = 'none';
        searchButton.disabled = false;
        eventSource.close();
    };
});

downloadButton.addEventListener('click', () => {
    const url = downloadButton.dataset.downloadUrl;
    if (!url) return;

    // trigger browser download from server
    const a = document.createElement('a');
    a.href = url;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    // hide the button after starting download
    downloadButton.style.display = 'none';
});
