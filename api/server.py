"""
novel-editor HTTP API server.

Usage:
    python -m api.server
    or: uvicorn api.server:app --host 0.0.0.0 --port 19080
"""

import os
import sys
from fastapi import FastAPI
from fastapi.responses import JSONResponse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import config
from api.models import HealthResponse, ErrorResponse
from api.middleware import setup_cors, RequestLoggingMiddleware
from api.routes import books, tasks, chapters
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


@app.on_event("startup")
def on_startup():
    task_queue.start(num_workers=2)
    print("[API] Task queue started")


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


def main():
    import uvicorn
    uvicorn.run("api.server:app",
                host=config.server_host,
                port=config.server_port,
                reload=False)


if __name__ == "__main__":
    main()
