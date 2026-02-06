const input = document.getElementById('input');
const searchButton = document.getElementById('search-btn');
const cancelButton = document.getElementById('cancel-btn');
const searchingText = document.getElementById('searching-text');
const progressText = document.getElementById('progress-text');
const resultsContainer = document.getElementById('results-inner');
const downloadButton = document.getElementById('download-btn');
const summary = document.getElementById('summary');

// Base URL: use current origin when served via FastAPI;
// fall back to localhost:8000 when opening index.html as a file.
// Change this when deploying.
const API_BASE = (window.location.protocol === 'file:' || window.location.origin === 'null' || window.location.port === '5500')
    ? 'http://127.0.0.1:8000'
    : window.location.origin;

let eventSource = null;
let currentSearchId = null;
let searchingDots = 0;
let searchingInterval = null;
let searchCompleted = false;

function animateSearching() {
    searchingDots = (searchingDots + 1) % 4;
    searchingText.textContent = `scanning${'.'.repeat(searchingDots)}`;
}

function setSearchingUI(active) {
    searchButton.disabled = active;
    cancelButton.style.display = active ? 'inline-block' : 'none';
    searchingText.style.display = active ? 'block' : 'none';
    progressText.style.display = active ? 'block' : 'none';
    if (active) {
        searchingDots = 0;
        searchingInterval = setInterval(animateSearching, 500);
    } else {
        clearInterval(searchingInterval);
        searchingInterval = null;
    }
}

function resetUI() {
    resultsContainer.innerHTML = '';
    summary.style.display = 'none';
    downloadButton.disabled = true;
    downloadButton.dataset.downloadUrl = '';
    progressText.textContent = '';
    searchCompleted = false;
}

input.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') searchButton.click();
});

searchButton.addEventListener('click', () => {
    const username = input.value.trim();
    if (!username) {
        alert('Please enter a username.');
        return;
    }

    // Basic client-side validation
    if (username.length > 64) {
        alert('Username is too long (max 64 characters).');
        return;
    }
    if (!/^[a-zA-Z0-9._-]+$/.test(username)) {
        alert('Username contains invalid characters. Only letters, numbers, \'.\', \'_\' and \'-\' are allowed.');
        return;
    }

    resetUI();
    setSearchingUI(true);

    const encodedUsername = encodeURIComponent(username);
    const url = `${API_BASE}/search?username=${encodedUsername}`;

    eventSource = new EventSource(url);

    eventSource.onmessage = (event) => {
        const data = JSON.parse(event.data);

        // Capture search_id sent by the backend as the first event
        if (data.search_id) {
            currentSearchId = data.search_id;
            return;
        }

        if (data.error) {
            setSearchingUI(false);
            const errorDiv = document.createElement('div');
            errorDiv.textContent = `⚠ ${data.error}`;
            errorDiv.className = 'result-error';
            resultsContainer.appendChild(errorDiv);
            eventSource.close();
            eventSource = null;
            return;
        }

        if (data.result) {
            const el = document.createElement('div');
            el.textContent = data.result;

            if (data.result.startsWith('[+]')) {
                el.className = 'result-found';
            } else if (data.result.startsWith('[-]') || data.result.startsWith('[!]')) {
                el.className = 'result-not-found';
            }
            resultsContainer.appendChild(el);
            resultsContainer.scrollTop = resultsContainer.scrollHeight;
        }

        if (data.message === 'done') {
            searchCompleted = true;
            setSearchingUI(false);
            progressText.style.display = 'none';

            if (data.download) {
                const downloadUrl = `${API_BASE}${data.download}`;
                downloadButton.dataset.downloadUrl = downloadUrl;
                downloadButton.disabled = false;

                const count = data.count || 0;
                summary.textContent = `✓ Found ${count} positive result${count === 1 ? '' : 's'}`;
                summary.style.display = 'block';
            } else {
                summary.textContent = '✓ Search completed – No results found';
                summary.style.display = 'block';
            }
            eventSource.close();
            eventSource = null;
        }
    };

    eventSource.onerror = () => {
        if (searchCompleted) return;

        setSearchingUI(false);
        const errorDiv = document.createElement('div');
        errorDiv.textContent = '⚠ Connection lost. Make sure the backend server is running.';
        errorDiv.className = 'result-error';
        resultsContainer.appendChild(errorDiv);

        if (eventSource) {
            eventSource.close();
            eventSource = null;
        }
    };
});

cancelButton.addEventListener('click', () => {
    if (eventSource) {
        eventSource.close();
        eventSource = null;
    }

    // Tell backend to kill the process
    if (currentSearchId) {
        fetch(`${API_BASE}/cancel/${currentSearchId}`, { method: 'POST' }).catch(() => {});
        currentSearchId = null;
    }

    setSearchingUI(false);
    progressText.style.display = 'none';

    const infoDiv = document.createElement('div');
    infoDiv.textContent = '— Search cancelled by user';
    infoDiv.className = 'result-not-found';
    resultsContainer.appendChild(infoDiv);
});

// Download results
downloadButton.addEventListener('click', () => {
    const url = downloadButton.dataset.downloadUrl;
    if (!url || downloadButton.disabled) return;

    const a = document.createElement('a');
    a.href = url;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    downloadButton.disabled = true;
});
