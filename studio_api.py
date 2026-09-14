"""Local studio API used by the React desktop UI."""
from __future__ import annotations

import os
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from job_runner import list_jobs, snapshot, start_job
from providers.costs import summarize
from providers.env import ROOT
from providers.youtube_upload import credentials_ready

router = APIRouter(prefix="/api")


class IdeaRequest(BaseModel):
    idea: str = ""
    surprise: bool = False
    produce: bool = True


class ProduceIdRequest(BaseModel):
    content_id: str


def _desktop() -> bool:
    return os.environ.get("DESKTOP_MODE", "").strip().lower() in {"1", "true", "yes"}


@router.get("/health")
def api_health():
    return {
        "status": "ok",
        "desktop": _desktop(),
        "pipeline_enabled": os.environ.get("PIPELINE_ENABLED", "false"),
        "youtube_ready": credentials_ready(),
    }


@router.get("/dashboard")
def dashboard():
    from daily_pipeline import list_videos, queue_snapshot

    queue = queue_snapshot()
    videos = list_videos()
    spend = summarize()
    jobs = list_jobs()
    return {
        "queue": queue,
        "videos": videos[:12],
        "spend": spend,
        "jobs": jobs[:8],
        "youtube_ready": credentials_ready(),
        "credits_per_video": 540,
        "usd_per_video": 5.40,
    }


@router.get("/queue")
def api_queue():
    from daily_pipeline import queue_snapshot
    return queue_snapshot()


@router.get("/videos")
def api_videos():
    from daily_pipeline import list_videos
    return {"videos": list_videos()}


@router.get("/costs")
def api_costs():
    return summarize()


@router.get("/jobs")
def api_jobs():
    return {"jobs": list_jobs()}


@router.get("/jobs/{job_id}")
def api_job(job_id: str):
    job = snapshot(job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    return job


@router.post("/ideas")
def api_ideas(req: IdeaRequest):
    idea = (req.idea or "").strip()
    if not req.surprise and len(idea) < 8:
        raise HTTPException(400, "Write the thought in a sentence.")
    args = [str(ROOT / "daily_pipeline.py")]
    title = "Surprise me" if req.surprise and not idea else f"Idea: {idea[:72]}"
    if req.surprise and not idea:
        args.append("--surprise")
    else:
        args += ["--idea", idea]
    if not req.produce:
        from daily_pipeline import enqueue_idea
        row = enqueue_idea(idea, surprise=req.surprise)
        return {"queued": row, "produced": False}
    job = start_job(title, args, extra={"kind": "idea"})
    return {"job": job, "produced": True}


@router.post("/produce")
def api_produce(req: ProduceIdRequest):
    cid = req.content_id.strip()
    if not cid:
        raise HTTPException(400, "content_id required")
    job = start_job(
        f"Produce {cid}",
        [str(ROOT / "daily_pipeline.py"), "--content", cid],
        extra={"kind": "produce", "content_id": cid},
    )
    return {"job": job}


@router.get("/settings")
def api_settings():
    ledger = ROOT / "pipeline_output" / "costs.jsonl"
    return {
        "desktop": _desktop(),
        "pipeline_enabled": os.environ.get("PIPELINE_ENABLED", "false"),
        "youtube_ready": credentials_ready(),
        "model": os.environ.get("OPENAI_MODEL", "gpt-6-astra"),
        "ledger_exists": ledger.exists(),
    }
