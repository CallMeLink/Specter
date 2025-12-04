from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
import asyncio
import json
import logging
import sys
import os
import uuid
import time
import subprocess
from pathlib import Path

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI()

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

TOTAL_SITES = 461
SHERLOCK_PATH = os.path.expandvars(r"%APPDATA%\Python\Python313\Scripts\sherlock.exe")
RESULTS_DIR = os.path.join(os.path.dirname(__file__), "results")
os.makedirs(RESULTS_DIR, exist_ok=True)
# cleanup config: delete files older than CLEANUP_AGE seconds every CLEANUP_INTERVAL seconds
CLEANUP_AGE = 60 * 10  # 10 minutes
CLEANUP_INTERVAL = 60 * 5  # run every 5 minutes


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

async def run_sherlock(username: str):
    """
    Runs sherlock as a subprocess and yields progress and results.
    """
    # Remove leading/trailing whitespace
    username = username.strip()
    
    if not username:
        yield f"data: {json.dumps({'error': 'Username cannot be empty.'})}\n\n"
        return

    command = [SHERLOCK_PATH, username, "--print-all", "--no-color"]
    
    if not os.path.exists(SHERLOCK_PATH):
        logger.error(f"Sherlock executable not found at: {SHERLOCK_PATH}")
        yield f"data: {json.dumps({'error': 'Sherlock executable not found on server.'})}\n\n"
        return

    positive_results = []

    try:
        # Use subprocess.Popen for synchronous execution
        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True
        )

        # Read output line by line
        for line in process.stdout:
            line_str = line.strip()
            logger.info(f"Sherlock Output: {line_str}")

            # Skip empty lines only
            if not line_str:
                continue

            # capture positive results for file download
            if line_str.startswith("[+]"):
                positive_results.append(line_str)

            # Send every line as a 'result'
            yield f"data: {json.dumps({'result': line_str})}\n\n"

        # Wait for process to complete
        process.wait()
        logger.info(f"Sherlock process finished with code {process.returncode}")
        
    except Exception as e:
        logger.exception(f"Error while running sherlock: {e}")
        yield f"data: {json.dumps({'error': f'Error running sherlock: {str(e)}'})}\n\n"
        return

    download_url = None
    positive_count = len(positive_results)
    if positive_results:
        # write results to a unique file
        filename = f"{username}_{uuid.uuid4().hex}.txt"
        filepath = os.path.join(RESULTS_DIR, filename)
        try:
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write('\n'.join(positive_results))
            download_url = f"/download/{filename}"
        except Exception:
            logger.exception("Failed to write results file")
    yield f"data: {json.dumps({'message': 'done', 'download': download_url, 'count': positive_count})}\n\n"


@app.get("/search")
async def search(username: str):
    return StreamingResponse(run_sherlock(username), media_type="text/event-stream")


def _is_safe_filename(filename: str) -> bool:
    # allow only alphanum, dash, underscore and .txt
    import re
    return bool(re.fullmatch(r"[\w\-]+_[0-9a-f]{32}\.txt", filename))


@app.get("/download/{filename}")
async def download_file(filename: str):
    # ensure filename is safe and file exists in results dir
    if not _is_safe_filename(filename):
        return {"error": "invalid filename"}

    full_path = os.path.join(RESULTS_DIR, filename)
    if not os.path.exists(full_path):
        return {"error": "file not found"}

    def file_iterator(path: str):
        try:
            with open(path, 'rb') as fh:
                for chunk in iter(lambda: fh.read(8192), b""):
                    yield chunk
        finally:
            try:
                os.remove(path)
                logger.info(f"Deleted result file: {path}")
            except Exception:
                logger.exception("Failed to delete result file after download")

    return StreamingResponse(file_iterator(full_path), media_type="application/octet-stream", headers={"Content-Disposition": f"attachment; filename=\"{filename}\""})


@app.on_event("startup")
async def startup_event():
    # start cleanup background task
    task = asyncio.create_task(_cleanup_results_loop())
    app.state._cleanup_task = task


@app.on_event("shutdown")
async def shutdown_event():
    # cancel cleanup task if running
    task = getattr(app.state, '_cleanup_task', None)
    if task:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

@app.get("/")
def read_root():
    return {"message": "Stella Simulator Backend"}