from contextlib import asynccontextmanager
from fastapi import FastAPI, Query, Request
from fastapi.responses import StreamingResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from slowapi import Limiter
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from starlette.middleware.base import BaseHTTPMiddleware
import asyncio
import json
import logging
import shutil
import sys
import os
import re
import uuid
import time
import tempfile
import subprocess
from pathlib import Path

# Environment variables configuration
LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO").upper()
ALLOWED_ORIGIN = os.environ.get("ALLOWED_ORIGIN", "*")
MAX_CONCURRENT_SEARCHES = int(os.environ.get("MAX_CONCURRENT_SEARCHES", "3"))
SEARCH_TIMEOUT = int(os.environ.get("SEARCH_TIMEOUT", "300"))  # 5 min default

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Sherlock path detection (multi-platform)
def _find_sherlock() -> str | None:
    env_path = os.environ.get("SHERLOCK_PATH")
    if env_path and os.path.isfile(env_path):
        return env_path

    which = shutil.which("sherlock")
    if which:
        return which

    candidates: list[str] = []
    if sys.platform == "win32":
        appdata = os.environ.get("APPDATA", "")
        local = os.environ.get("LOCALAPPDATA", "")
        for pyver in ("Python313", "Python312", "Python311", "Python310"):
            if appdata:
                candidates.append(os.path.join(appdata, "Python", pyver, "Scripts", "sherlock.exe"))
            if local:
                candidates.append(os.path.join(local, "Programs", "Python", pyver, "Scripts", "sherlock.exe"))
    else:
        home = Path.home()
        candidates += [
            str(home / ".local" / "bin" / "sherlock"),
            "/usr/local/bin/sherlock",
            "/usr/bin/sherlock",
        ]

    for path in candidates:
        if os.path.isfile(path):
            return path

    return None


SHERLOCK_PATH = _find_sherlock()
if SHERLOCK_PATH:
    logger.info(f"Sherlock found at: {SHERLOCK_PATH}")
else:
    logger.warning("Sherlock executable NOT found. Set SHERLOCK_PATH env var or install sherlock-project.")

# Store results in a temp directory outside the project tree so that
# file-watcher tools (e.g. VS Code Live Server) don't reload the page
# when result files are created or deleted.
_SPECTER_TEMP = os.path.join(tempfile.gettempdir(), "specter")
RESULTS_DIR = os.path.join(_SPECTER_TEMP, "results")
os.makedirs(RESULTS_DIR, exist_ok=True)

CLEANUP_AGE = 60 * 10  # 10 minutes
CLEANUP_INTERVAL = 60 * 5  # run every 5 minutes

# Active search processes keyed by search_id for cancellation
_active_searches: dict[str, subprocess.Popen] = {}
_search_semaphore = asyncio.Semaphore(MAX_CONCURRENT_SEARCHES)

# Username validation
_USERNAME_RE = re.compile(r"^[a-zA-Z0-9._-]{1,64}$")


def _validate_username(username: str) -> str | None:
    """Return an error message if the username is invalid, else None."""
    if not username:
        return "Username cannot be empty."
    if len(username) > 64:
        return "Username is too long (max 64 characters)."
    if not _USERNAME_RE.match(username):
        return "Username contains invalid characters. Only letters, numbers, '.', '_' and '-' are allowed."
    return None


# Cleanup loop
async def _cleanup_results_loop():
    logger.info("Result cleanup loop started")
    try:
        while True:
            now = time.time()
            for name in os.listdir(RESULTS_DIR):
                path = os.path.join(RESULTS_DIR, name)
                try:
                    if os.path.isfile(path):
                        mtime = os.path.getmtime(path)
                        if now - mtime > CLEANUP_AGE:
                            os.remove(path)
                            logger.info(f"Removed stale result file: {path}")
                except Exception:
                    logger.exception(f"Error while cleaning file: {path}")
            await asyncio.sleep(CLEANUP_INTERVAL)
    except asyncio.CancelledError:
        logger.info("Result cleanup loop cancelled")

@asynccontextmanager
async def lifespan(app: FastAPI):
    task = asyncio.create_task(_cleanup_results_loop())
    yield
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


app = FastAPI(lifespan=lifespan)

# Rate limiting
limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter


@app.exception_handler(RateLimitExceeded)
async def _rate_limit_handler(request: Request, exc: RateLimitExceeded):
    return JSONResponse({"error": "Too many requests. Try again later."}, status_code=429)

# Security headers middleware
class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        return response


app.add_middleware(SecurityHeadersMiddleware)

# Configure CORS
_origins = [ALLOWED_ORIGIN] if ALLOWED_ORIGIN != "*" else ["*"]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins,
    allow_credentials=(ALLOWED_ORIGIN != "*"),
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


def run_sherlock(username: str, search_id: str):
    """Runs sherlock as a subprocess and yields SSE events with progress."""
    username = username.strip()

    # Validate
    err = _validate_username(username)
    if err:
        yield f"data: {json.dumps({'error': err})}\n\n"
        return

    if not SHERLOCK_PATH:
        logger.error("Sherlock executable not found")
        yield f"data: {json.dumps({'error': 'Sherlock not found on the server. Set SHERLOCK_PATH or install sherlock-project.'})}\n\n"
        return

    command = [SHERLOCK_PATH, username, "--print-all", "--no-color"]
    positive_results: list[str] = []
    process = None
    checked = 0
    start_time = time.monotonic()

    try:
        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            universal_newlines=True,
            cwd=_SPECTER_TEMP,
        )
        _active_searches[search_id] = process

        for line in process.stdout:
            # If the process was cancelled externally, stop
            if search_id not in _active_searches:
                break

            # Enforce timeout
            if time.monotonic() - start_time > SEARCH_TIMEOUT:
                logger.warning(f"Search {search_id} timed out after {SEARCH_TIMEOUT}s")
                yield f"data: {json.dumps({'error': 'Search timed out.'})}\n\n"
                break

            line_str = line.strip()
            if not line_str:
                continue

            # Skip non-result lines (update notices, banners, etc.)
            if not line_str.startswith(("[+]", "[-]", "[!]")):
                continue

            # Count checked sites
            if line_str.startswith(("[+]", "[-]", "[!]")):
                checked += 1

            if line_str.startswith("[+]"):
                positive_results.append(line_str)

            yield f"data: {json.dumps({'result': line_str, 'checked': checked, 'total': TOTAL_SITES})}\n\n"

        if process:
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
            logger.info(f"Sherlock finished with code {process.returncode}")

    except Exception as e:
        logger.exception(f"Error running sherlock: {e}")
        yield f"data: {json.dumps({'error': f'Error running sherlock: {str(e)}'})}\n\n"
        return
    finally:
        _active_searches.pop(search_id, None)
        if process:
            try:
                if process.stdout:
                    process.stdout.close()
                if process.poll() is None:
                    process.terminate()
                    try:
                        process.wait(timeout=2)
                    except subprocess.TimeoutExpired:
                        process.kill()
            except Exception:
                pass

    # Build download file
    download_url = None
    positive_count = len(positive_results)
    if positive_results:
        filename = f"{username}_{uuid.uuid4().hex}.txt"
        filepath = os.path.join(RESULTS_DIR, filename)
        try:
            with open(filepath, "w", encoding="utf-8") as f:
                f.write("\n".join(positive_results))
            download_url = f"/download/{filename}"
        except Exception:
            logger.exception("Failed to write results file")

    yield f"data: {json.dumps({'message': 'done', 'download': download_url, 'count': positive_count})}\n\n"


# Main search endpoint
@app.get("/search")
@limiter.limit("5/minute")
async def search(request: Request, username: str = Query(..., min_length=1, max_length=64)):
    if _search_semaphore.locked() and _search_semaphore._value == 0:
        return JSONResponse(
            {"error": "Server is busy. Please try again shortly."},
            status_code=503,
        )

    search_id = uuid.uuid4().hex

    async def _guarded_stream():
        async with _search_semaphore:
            # Send search_id as first event so the client can use it for cancellation
            yield f"data: {json.dumps({'search_id': search_id})}\n\n"
            for chunk in run_sherlock(username, search_id):
                yield chunk

    headers = {
        "X-Search-Id": search_id,
        "Cache-Control": "no-cache",
    }
    return StreamingResponse(
        _guarded_stream(),
        media_type="text/event-stream",
        headers=headers,
    )


@app.post("/cancel/{search_id}")
async def cancel_search(search_id: str):
    """Cancel a running search by its search_id."""
    process = _active_searches.pop(search_id, None)
    if process is None:
        return JSONResponse({"status": "not_found"}, status_code=404)
    try:
        process.terminate()
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            process.kill()
    except Exception:
        logger.exception("Error terminating search process")
    return {"status": "cancelled"}


_SAFE_FILENAME_RE = re.compile(r"[\w\-]+_[0-9a-f]{32}\.txt")

# Download endpoint
@app.get("/download/{filename}")
async def download_file(filename: str):
    if not _SAFE_FILENAME_RE.fullmatch(filename):
        return JSONResponse({"error": "invalid filename"}, status_code=400)

    full_path = os.path.join(RESULTS_DIR, filename)
    if not os.path.exists(full_path):
        return JSONResponse({"error": "file not found"}, status_code=404)

    def file_iterator(path: str):
        try:
            with open(path, "rb") as fh:
                for chunk in iter(lambda: fh.read(8192), b""):
                    yield chunk
        finally:
            try:
                os.remove(path)
                logger.info(f"Deleted result file: {path}")
            except Exception:
                logger.exception("Failed to delete result file after download")

    return StreamingResponse(
        file_iterator(full_path),
        media_type="application/octet-stream",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# Serve the frontend static files (index.html, main.js, style.css)
_FRONTEND_DIR = os.path.join(os.path.dirname(__file__), os.pardir)
if os.path.isfile(os.path.join(_FRONTEND_DIR, "index.html")):
    app.mount("/", StaticFiles(directory=_FRONTEND_DIR, html=True), name="frontend")