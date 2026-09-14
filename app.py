#!/usr/bin/env python3
"""FastAPI server wrapping the Somehow True video pipeline.

Endpoints:
  GET  /health          — health check for Railway
  POST /produce         — run the full pipeline from a config JSON
  POST /produce/daily   — pick next content, generate video, return result
  GET  /queue           — show content queue status
  GET  /jobs/{job_id}    — check background job status

Environment variables:
  PIPELINE_ENABLED  — default false; only true permits production requests
  API_TOKEN         — required bearer token for every route except GET /health
  PORT              — server port (set by Railway, defaults to 8000)

Idle deployment does not need provider credentials. Provider and publishing
integrations are incomplete; see README before considering activation.
"""
from __future__ import annotations

import hmac
import os
import subprocess
import sys
import time
import uuid

from fastapi import FastAPI, BackgroundTasks, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from typing import Optional

from providers.env import ROOT, load_env
from studio_api import router as studio_router

load_env()

app = FastAPI(
    title="Somehow True Pipeline",
    description="Automated video production pipeline for Somehow True YouTube channel",
    version="1.0.0",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:5173", "http://localhost:5173", "http://127.0.0.1:8765"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(studio_router)

JOBS: dict[str, dict] = {}
UI_DIST = ROOT / "ui" / "dist"


def _desktop() -> bool:
    return os.environ.get("DESKTOP_MODE", "").strip().lower() in {"1", "true", "yes"}


def _local(request: Request) -> bool:
    host = request.client.host if request.client else ""
    return host in {"127.0.0.1", "::1", "localhost"}


def _open_path(path: str) -> bool:
    if path in {"/", "/health", "/api/health", "/index.html"}:
        return True
    if path.startswith("/assets/") or path.startswith("/api/"):
        return path.startswith("/assets/") or (path == "/api/health")
    return path.endswith((".js", ".css", ".ico", ".svg", ".woff2", ".map", ".webmanifest"))


@app.middleware("http")
async def deployment_guard(request: Request, call_next):
    """Fail closed on Railway. The local desktop app is allowed through."""
    path = request.url.path.rstrip("/") or "/"
    if request.method == "OPTIONS" or path == "/health" or _open_path(path):
        if path in {"/", "/health"} or path.startswith("/assets/") or path.endswith(
            (".js", ".css", ".ico", ".svg", ".woff2", ".map")
        ):
            return await call_next(request)
        if path == "/api/health":
            return await call_next(request)

    if _desktop() and _local(request):
        return await call_next(request)

    expected = os.environ.get("API_TOKEN", "")
    scheme, _, supplied = request.headers.get("Authorization", "").partition(" ")
    if (
        not expected.strip()
        or scheme.lower() != "bearer"
        or not hmac.compare_digest(supplied.encode("utf-8"), expected.encode("utf-8"))
    ):
        if path.startswith("/api/") or path.startswith("/produce") or path.startswith("/queue") or path.startswith("/jobs"):
            return JSONResponse(
                {"detail": "Unauthorized"},
                status_code=401,
                headers={"WWW-Authenticate": "Bearer"},
            )

    producing = path.startswith("/produce") or (
        request.method == "POST" and path.startswith("/api/")
    )
    if producing and not _desktop() and (
        os.environ.get("PIPELINE_ENABLED", "false").strip().lower() != "true"
    ):
        return JSONResponse(
            {"detail": "Pipeline disabled: deployment is in idle mode"},
            status_code=503,
        )
    return await call_next(request)


class ProduceRequest(BaseModel):
    content_id: Optional[str] = None
    config_path: Optional[str] = None
    narration_path: Optional[str] = None
    skip_runway: bool = False
    skip_captions: bool = False


class DailyRequest(BaseModel):
    narration_path: Optional[str] = None
    smoke: bool = False


@app.get("/health")
async def health():
    """Health check endpoint for Railway."""
    return {"status": "ok", "service": "somehow-true-pipeline", "version": "1.0.0"}


@app.get("/queue")
async def queue():
    """Show content queue status."""
    result = subprocess.run(
        [sys.executable, str(ROOT / "daily_pipeline.py"), "--list"],
        capture_output=True, text=True, cwd=str(ROOT),
    )
    return JSONResponse({
        "queue": result.stdout,
        "exit_code": result.returncode,
    })


@app.post("/produce")
async def produce(req: ProduceRequest, background_tasks: BackgroundTasks):
    """Run the full pipeline from a config or content ID."""
    job_id = str(uuid.uuid4())[:8]
    JOBS[job_id] = {
        "id": job_id, "status": "running", "started_at": time.time(),
        "content_id": req.content_id, "result": None, "error": None,
    }

    async def run_pipeline():
        try:
            cmd = [sys.executable, str(ROOT / "produce_video.py")]
            if req.config_path:
                cmd += ["--config", req.config_path]
            elif req.content_id:
                # Generate config from content ID via daily_pipeline.py
                config_dir = ROOT / "pipeline_output" / req.content_id
                config_path = config_dir / "config.json"
                if not config_path.exists():
                    daily_cmd = [sys.executable, str(ROOT / "daily_pipeline.py")]
                    if req.narration_path:
                        daily_cmd += ["--narration", req.narration_path]
                    if req.content_id:
                        daily_cmd += ["--content", req.content_id]
                    subprocess.run(daily_cmd, cwd=str(ROOT), check=True)
                cmd += ["--config", str(config_path)]
            else:
                cmd += ["--config", str(ROOT / "config.example.json")]

            if req.skip_runway:
                cmd.append("--skip-runway")
            if req.skip_captions:
                cmd.append("--skip-captions")

            result = subprocess.run(cmd, capture_output=True, text=True, cwd=str(ROOT))
            if result.returncode == 0:
                JOBS[job_id]["status"] = "completed"
                JOBS[job_id]["result"] = result.stdout[-2000:]
            else:
                JOBS[job_id]["status"] = "failed"
                JOBS[job_id]["error"] = result.stderr[-2000:]
        except Exception as e:
            JOBS[job_id]["status"] = "failed"
            JOBS[job_id]["error"] = str(e)

    background_tasks.add_task(run_pipeline)
    return {"job_id": job_id, "status": "started", "message": "Pipeline running in background"}


@app.post("/produce/smoke")
async def produce_smoke(background_tasks: BackgroundTasks):
    """Short Astra + ElevenLabs + two Runway clips. No YouTube upload."""
    job_id = str(uuid.uuid4())[:8]
    JOBS[job_id] = {
        "id": job_id, "status": "running", "started_at": time.time(),
        "result": None, "error": None,
    }

    def run_smoke():
        try:
            result = subprocess.run(
                [sys.executable, str(ROOT / "test_flow.py")],
                capture_output=True, text=True, cwd=str(ROOT),
            )
            if result.returncode == 0:
                JOBS[job_id]["status"] = "completed"
                JOBS[job_id]["result"] = result.stdout[-2000:]
            else:
                JOBS[job_id]["status"] = "failed"
                JOBS[job_id]["error"] = (result.stderr or result.stdout)[-2000:]
        except Exception as e:
            JOBS[job_id]["status"] = "failed"
            JOBS[job_id]["error"] = str(e)

    background_tasks.add_task(run_smoke)
    return {"job_id": job_id, "status": "started", "message": "Short smoke test running"}


@app.post("/produce/daily")
async def produce_daily(req: DailyRequest, background_tasks: BackgroundTasks):
    """Pick next content from the queue and produce a video."""
    job_id = str(uuid.uuid4())[:8]
    JOBS[job_id] = {
        "id": job_id, "status": "running", "started_at": time.time(),
        "result": None, "error": None,
    }

    def run_daily():
        try:
            cmd = [sys.executable, str(ROOT / "daily_pipeline.py")]
            if req.narration_path:
                cmd += ["--narration", req.narration_path]
            result = subprocess.run(cmd, capture_output=True, text=True, cwd=str(ROOT))
            if result.returncode == 0:
                JOBS[job_id]["status"] = "completed"
                JOBS[job_id]["result"] = result.stdout[-2000:]
            else:
                JOBS[job_id]["status"] = "failed"
                JOBS[job_id]["error"] = result.stderr[-2000:]
        except Exception as e:
            JOBS[job_id]["status"] = "failed"
            JOBS[job_id]["error"] = str(e)

    background_tasks.add_task(run_daily)
    return {"job_id": job_id, "status": "started", "message": "Daily pipeline running"}


@app.get("/jobs/{job_id}")
async def job_status(job_id: str):
    """Check the status of a background job."""
    if job_id not in JOBS:
        return JSONResponse({"error": "Job not found"}, status_code=404)
    job = JOBS[job_id].copy()
    if job["status"] == "running":
        job["elapsed_seconds"] = time.time() - job["started_at"]
    return job


@app.get("/")
async def spa_index():
    index = UI_DIST / "index.html"
    if index.exists():
        return FileResponse(index)
    return {
        "status": "ok",
        "service": "somehow-true-pipeline",
        "ui": "not built — run npm run build in ui/",
    }


if UI_DIST.exists():
    assets = UI_DIST / "assets"
    if assets.exists():
        app.mount("/assets", StaticFiles(directory=assets), name="ui-assets")


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
