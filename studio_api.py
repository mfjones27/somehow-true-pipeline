"""Local studio API used by the React desktop UI."""
from __future__ import annotations

import os
import sys
import webbrowser
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from job_runner import list_jobs, snapshot, start_job
from providers.costs import summarize
from providers.env import ROOT
from providers.youtube_upload import credentials_ready, list_posted_videos

router = APIRouter(prefix="/api")


class IdeaRequest(BaseModel):
    idea: str = ""
    surprise: bool = False
    produce: bool = True


class ProduceIdRequest(BaseModel):
    content_id: str
    skip_runway: bool = False
    skip_captions: bool = False


class LinkRequest(BaseModel):
    url: str = ""
    text: str = ""


YOUTUBE_PREFIXES = (
    "https://studio.youtube.com/",
    "https://youtu.be/",
    "https://www.youtube.com/",
    "https://youtube.com/",
)


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
    from daily_pipeline import list_local_projects, queue_snapshot

    queue = queue_snapshot()
    return {
        "queue": queue,
        "projects": list_local_projects()[:24],
        "videos": list_posted_videos()[:24],
        "spend": summarize(),
        "jobs": list_jobs()[:12],
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
    return {"videos": list_posted_videos()}


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
    args = [str(ROOT / "daily_pipeline.py"), "--content", cid]
    if req.skip_runway:
        args.append("--skip-runway")
    if req.skip_captions:
        args.append("--skip-captions")
    label = f"Continue {cid}" if req.skip_runway else f"Produce {cid}"
    job = start_job(label, args, extra={"kind": "produce", "content_id": cid})
    return {"job": job}


def _copy_text(text: str) -> None:
    if sys.platform != "win32":
        raise RuntimeError("Clipboard is only wired on Windows")
    import ctypes

    cf_unicode = 13
    gmem_moveable = 0x0002
    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32
    if not user32.OpenClipboard(None):
        raise RuntimeError("Clipboard is busy")
    try:
        user32.EmptyClipboard()
        payload = text.encode("utf-16-le") + b"\x00\x00"
        handle = kernel32.GlobalAlloc(gmem_moveable, len(payload))
        locked = kernel32.GlobalLock(handle)
        ctypes.memmove(locked, payload, len(payload))
        kernel32.GlobalUnlock(handle)
        user32.SetClipboardData(cf_unicode, handle)
    finally:
        user32.CloseClipboard()


@router.post("/open")
def api_open(req: LinkRequest):
    url = (req.url or "").strip()
    if not url.startswith(YOUTUBE_PREFIXES):
        raise HTTPException(400, "Only YouTube links can be opened from here.")
    webbrowser.open(url)
    return {"ok": True}


@router.post("/copy")
def api_copy(req: LinkRequest):
    text = (req.text or req.url or "").strip()
    if not text:
        raise HTTPException(400, "Nothing to copy.")
    try:
        _copy_text(text)
    except Exception as exc:
        raise HTTPException(500, f"Could not copy: {exc}") from exc
    return {"ok": True}


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
