"""
novel-editor HTTP API server.

Usage:
    python -m api.server
    or: uvicorn api.server:app --host 0.0.0.0 --port 19080
"""

import os
import signal
import subprocess
import sys
import time
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Monkey-patch h11 to accept non-ASCII bytes (e.g. Chinese) in HTTP request target.
# h11's request_line_re only accepts [\x21-\x7e] for the target, causing
# RemoteProtocolError / "Empty reply from server" when curl sends raw UTF-8.
import re as _re
import h11._readers as _h11_readers
import h11._events as _h11_events

_h11_readers.request_line_re = _re.compile(
    b"(?P<method>[-!#$%&'*+.^_`|~0-9a-zA-Z]+) (?P<target>[\\x21-\\xff]+) HTTP/(?P<http_version>[0-9]\\.[0-9])"
)
_h11_events.request_target_re = _re.compile(b"[\\x21-\\xff]+")

_original_maybe_read = _h11_readers.maybe_read_from_IDLE_client

def _patched_maybe_read(buf):
    result = _original_maybe_read(buf)
    if result is not None:
        target = result.target
        if isinstance(target, bytes):
            encoded = bytearray()
            for b in target:
                if b > 127:
                    encoded.extend(("%{:02X}".format(b)).encode("ascii"))
                else:
                    encoded.append(b)
            result.__dict__["target"] = bytes(encoded)
    return result

_h11_readers.maybe_read_from_IDLE_client = _patched_maybe_read
_h11_readers.READERS[(_h11_readers.CLIENT, _h11_readers.IDLE)] = _patched_maybe_read

from config import config
from api.models import HealthResponse, ErrorResponse
from api.middleware import setup_cors, RequestLoggingMiddleware
from api.routes import books, tasks, chapters, admin_catalog, admin_register
from worker.task_queue import task_queue

app = FastAPI(
    title="novel-editor API",
    description="Novel generation pipeline as a service",
    version="1.0.0",
)

setup_cors(app)
app.add_middleware(RequestLoggingMiddleware)

app.include_router(books.router)
app.include_router(tasks.router)
app.include_router(chapters.router)
app.include_router(admin_catalog.router)
app.include_router(admin_register.router)

admin_web_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "admin_web")
if os.path.isdir(admin_web_dir):
    app.mount("/admin", StaticFiles(directory=admin_web_dir, html=True), name="admin")


@app.on_event("startup")
def on_startup():
    from services.db import init_db
    init_db()
    task_queue.start(num_workers=2)
    print("[API] DB initialized, task queue started")


@app.on_event("shutdown")
def on_shutdown():
    task_queue.shutdown(wait=False)
    print("[API] Task queue stopped")


@app.get("/api/v1/health", response_model=HealthResponse)
def health():
    return HealthResponse(status="ok")


@app.exception_handler(Exception)
async def global_exception_handler(request, exc):
    return JSONResponse(
        status_code=500,
        content={"error": str(exc)},
    )


def kill_port(port: int) -> bool:
    pids = []
    try:
        result = subprocess.run(
            ["fuser", f"{port}/tcp"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            universal_newlines=True, timeout=5,
        )
        for token in result.stdout.strip().split():
            try:
                pids.append(int(token))
            except ValueError:
                pass
    except Exception:
        pass

    if not pids:
        try:
            result = subprocess.run(
                ["lsof", "-ti", f":{port}"],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                universal_newlines=True, timeout=5,
            )
            for line in result.stdout.strip().splitlines():
                try:
                    pids.append(int(line.strip()))
                except ValueError:
                    pass
        except Exception:
            pass

    if not pids:
        return False

    for pid in pids:
        try:
            os.kill(pid, signal.SIGKILL)
        except Exception:
            pass

    time.sleep(0.5)
    return True


def main():
    import uvicorn
    port = config.server_port
    if kill_port(port):
        print(f"[API] Killed existing process on port {port}")
    uvicorn.run("api.server:app",
                host=config.server_host,
                port=port,
                reload=False)


if __name__ == "__main__":
    main()
