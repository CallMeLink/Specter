# Specter

A web-based OSINT tool that provides a clean, real-time interface for scanning username presence across hundreds of online platforms. Built on top of the [Sherlock Project](https://github.com/sherlock-project/sherlock), Specter wraps the CLI tool in a FastAPI backend and streams results to the browser via Server-Sent Events (SSE), giving users immediate visual feedback as each platform is checked.

---

## Table of Contents

- [Overview](#overview)
- [Features](#features)
- [Prerequisites](#prerequisites)
- [Installation](#installation)
- [Usage](#usage)
- [Configuration](#configuration)
- [API Reference](#api-reference)
- [Project Structure](#project-structure)
- [Security](#security)
- [License](#license)

---

## Overview

Traditional OSINT username enumeration tools run exclusively in the terminal. Specter solves this by providing a browser-based interface that streams results in real time, making the process more accessible and visually informative. The backend manages Sherlock as a child process, parses its output line by line, and forwards each result to the frontend through an SSE connection. This means the user sees results appearing one by one as they are discovered, rather than waiting for the entire scan to complete.


## Features

- **Real-time streaming** — results appear in the browser as each platform is checked, powered by Server-Sent Events.
- **Scan cancellation** — users can abort a running scan at any time. The backend terminates the underlying Sherlock process immediately.
- **Downloadable reports** — positive results are compiled into a `.txt` file available for download once the scan completes.
- **Rate limiting** — configurable per-IP rate limits prevent abuse (default: 5 requests per minute).
- **Concurrency control** — a semaphore limits the number of simultaneous Sherlock processes to prevent resource exhaustion.
- **Process timeout** — searches that exceed the configured timeout are automatically killed.
- **Input validation** — usernames are validated on both client and server side (alphanumeric, dots, underscores, hyphens; max 64 characters).
- **Security headers** — responses include `X-Content-Type-Options`, `X-Frame-Options`, `Referrer-Policy`, `Permissions-Policy`, and `X-XSS-Protection`.
- **Automatic cleanup** — a background task periodically removes result files older than 10 minutes.
- **Cross-platform** — Sherlock path detection works on Windows, macOS, and Linux without manual configuration.

## Prerequisites

- **Python 3.10** or later
- **Sherlock** installed and accessible via `PATH` or configured through the `SHERLOCK_PATH` environment variable

Install Sherlock:

```bash
pip install sherlock-project
```

Verify it works:

```bash
sherlock --version
```

## Installation

Clone the repository:

```bash
git clone https://github.com/YOUR-USERNAME/specter.git
cd specter
```

Install Python dependencies (FastAPI, Uvicorn, and slowapi):

```bash
pip install -r requirements.txt
```

This installs everything needed to run the server. The full dependency list is defined in `requirements.txt`:

```
fastapi>=0.110
uvicorn>=0.29
slowapi>=0.1.9
```

## Usage

Start the server:

```bash
uvicorn src.backend.main:app --host 0.0.0.0 --port 8000
```

Then open `http://localhost:8000` in your browser.

For development with auto-reload:

```bash
uvicorn src.backend.main:app --host 127.0.0.1 --port 8000 --reload
```

## Configuration

All configuration is done through environment variables. Defaults are provided for local development.

| Variable | Default | Description |
|---|---|---|
| `ALLOWED_ORIGIN` | `*` | CORS allowed origin. Set to your domain in production (e.g. `https://specter.example.com`). |
| `MAX_CONCURRENT_SEARCHES` | `3` | Maximum number of Sherlock processes running simultaneously. |
| `SEARCH_TIMEOUT` | `300` | Maximum time in seconds before a search is forcefully terminated. |
| `LOG_LEVEL` | `INFO` | Python logging level (`DEBUG`, `INFO`, `WARNING`, `ERROR`). |
| `SHERLOCK_PATH` | auto-detected | Absolute path to the Sherlock executable. Only needed if auto-detection fails. |

Example for production:

```bash
export ALLOWED_ORIGIN=https://specter.example.com
export MAX_CONCURRENT_SEARCHES=5
export SEARCH_TIMEOUT=300
export LOG_LEVEL=WARNING
```

## API Reference

### `GET /search?username={username}`

Initiates a scan and returns a stream of Server-Sent Events.

**Query parameters:**

| Parameter | Type | Constraints | Description |
|---|---|---|---|
| `username` | string | 1–64 chars, `[a-zA-Z0-9._-]` | The username to scan. |

**Rate limit:** 5 requests per minute per IP.

**SSE event format** (each line is a JSON object in `data:`):

```jsonc
// First event — search identifier for cancellation
{"search_id": "a1b2c3d4..."}

// Result events — one per platform checked
{"result": "[+] GitHub: https://github.com/username", "checked": 42, "total": 461}
{"result": "[-] SomeSite: Not Found!", "checked": 43, "total": 461}

// Final event
{"message": "done", "download": "/download/username_abc123.txt", "count": 12}
```

**Error responses:**

| Status | Condition |
|---|---|
| 429 | Rate limit exceeded |
| 503 | All search slots are in use |

### `POST /cancel/{search_id}`

Aborts a running scan. The Sherlock subprocess is terminated.

**Response:**

```json
{"status": "cancelled"}
```

### `GET /download/{filename}`

Downloads the result file. The file is deleted from the server after the download completes.

**Response:** `application/octet-stream` with `Content-Disposition: attachment`.

## Project Structure

```
specter/
├── src/
│   ├── index.html          # Single-page frontend
│   ├── main.js             # Client-side logic (SSE handling, UI updates)
│   ├── style.css           # Terminal-themed UI styles
│   └── backend/
│       └── main.py         # FastAPI application (API, process management, security)
├── requirements.txt        # Python dependencies
├── .gitignore
└── README.md
```

## Security

The following measures are implemented for production use:

- **Input sanitization** — usernames are validated against a strict regex on both client and server. No shell interpolation is possible (the subprocess receives arguments as a list, not a shell string).
- **Rate limiting** — per-IP request throttling via slowapi to mitigate brute-force and abuse.
- **Concurrency limiting** — a bounded semaphore prevents an attacker from exhausting server resources by opening many simultaneous searches.
- **Process timeout** — long-running or stuck Sherlock processes are automatically killed after the configured timeout.
- **CORS policy** — configurable allowed origin. In production, set `ALLOWED_ORIGIN` to your specific domain to prevent unauthorized cross-origin requests.
- **Security headers** — every response includes headers that prevent clickjacking, MIME sniffing, and other common web attacks.
- **File access control** — download filenames are validated against a strict pattern (`username_hex.txt`). Path traversal is not possible.
- **Automatic file cleanup** — result files are deleted after download, and a background task removes any stale files older than 10 minutes.

## License

This project is licensed under the MIT License.

---

> **Disclaimer:** This tool is intended for educational purposes and authorized security research only. Always obtain proper authorization before performing reconnaissance on any individual or organization. The author is not responsible for any misuse.
