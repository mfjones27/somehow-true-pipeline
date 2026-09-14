"""Background pipeline jobs with live logs for the desktop UI."""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path

from providers.env import ROOT
from providers.youtube_upload import extract_youtube_url, youtube_links

JOBS: dict[str, dict] = {}
_LOCK = threading.Lock()


def python_bin() -> str:
    if not getattr(sys, "frozen", False):
        return sys.executable
    venv = ROOT / ".venv" / "Scripts" / "python.exe"
    if venv.exists():
        return str(venv)
    found = shutil.which("python")
    if found:
        return found
    raise RuntimeError("This exe needs Python on PATH, or a .venv in the pipeline folder")


def start_job(title: str, args: list[str], extra: dict | None = None) -> dict:
    job_id = uuid.uuid4().hex[:8]
    job = {
        "id": job_id,
        "title": title,
        "status": "running",
        "started_at": time.time(),
        "log": "",
        "error": None,
        "result": None,
        **(extra or {}),
    }
    with _LOCK:
        JOBS[job_id] = job
    threading.Thread(target=_run, args=(job_id, args), daemon=True).start()
    return snapshot(job_id)


def _run(job_id: str, args: list[str]) -> None:
    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    cmd = [python_bin(), *[str(a) for a in args]]
    try:
        proc = subprocess.Popen(
            cmd,
            cwd=str(ROOT),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        JOBS[job_id]["pid"] = proc.pid
        lines: list[str] = []
        assert proc.stdout is not None
        for line in proc.stdout:
            lines.append(line)
            JOBS[job_id]["log"] = "".join(lines[-300:])
        code = proc.wait()
        JOBS[job_id]["status"] = "completed" if code == 0 else "failed"
        tail = JOBS[job_id]["log"][-2500:]
        if code == 0:
            JOBS[job_id]["result"] = tail
        else:
            JOBS[job_id]["error"] = tail
    except Exception as exc:
        JOBS[job_id]["status"] = "failed"
        JOBS[job_id]["error"] = str(exc)


def snapshot(job_id: str) -> dict | None:
    job = JOBS.get(job_id)
    if not job:
        return None
    out = dict(job)
    if out["status"] == "running":
        out["elapsed_seconds"] = round(time.time() - out["started_at"], 1)
    raw = extract_youtube_url(f"{out.get('log') or ''}\n{out.get('result') or ''}")
    links = youtube_links(raw)
    out["youtube"] = links["studio"]
    out["watch"] = links["watch"]
    return out


def list_jobs() -> list[dict]:
    rows = sorted(JOBS.values(), key=lambda item: item["started_at"], reverse=True)
    return [snapshot(item["id"]) for item in rows if snapshot(item["id"])]
