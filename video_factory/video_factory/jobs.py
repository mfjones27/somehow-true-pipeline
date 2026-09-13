"""Serial, bounded, restart-aware local jobs; never a publishing approval state."""

import fcntl
import hashlib
import json
import logging
import os
import re
import shutil
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from .assets import snapshot_audio
from .config import Settings
from .errors import BusyError, CapacityError, DuplicateError, FactoryError, RenderError
from .graphics import FramePainter
from .models import Manifest, parse_manifest
from .renderer import encode

LOGGER = logging.getLogger(__name__)


def now():
    return datetime.now(timezone.utc).isoformat()


def atomic_json(path: Path, value):
    temporary = path.with_suffix(".tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2, allow_nan=False)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    temporary.replace(path)


class JobStore:
    def __init__(self, settings: Settings | None = None):
        self.settings = settings or Settings()
        self.settings.assets.mkdir(parents=True, exist_ok=True)
        self.settings.jobs.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def exclusive(self):
        with (self.settings.jobs / ".render.lock").open("a") as handle:
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise BusyError("One local render is already running; retry after completion") from exc
            try:
                yield
            finally:
                fcntl.flock(handle, fcntl.LOCK_UN)

    def recover_interrupted(self):
        # Called only while holding the same cross-process render lock.
        for path in self.settings.jobs.glob("*/job.json"):
            job = json.loads(path.read_text(encoding="utf-8"))
            if job["status"] == "rendering":
                job.update(status="failed", error="Interrupted; output requires inspection",
                           updated_at=now())
                atomic_json(path, job)

    def get(self, job_id: str) -> dict | None:
        if not re.fullmatch(r"[a-f0-9]{32}", job_id):
            return None
        path = self.settings.jobs / job_id / "job.json"
        if not path.is_file():
            return None
        # A rendering job with no active lock is from an interrupted process.
        job = json.loads(path.read_text(encoding="utf-8"))
        if job["status"] == "rendering":
            try:
                with self.exclusive():
                    self.recover_interrupted()
            except BusyError:
                pass
            job = json.loads(path.read_text(encoding="utf-8"))
        return job

    def check_capacity(self):
        count = sum(1 for p in self.settings.jobs.iterdir() if p.is_dir())
        storage = sum(p.stat().st_size for p in self.settings.jobs.rglob("*") if p.is_file())
        # Reserve space for a WAV snapshot and a bounded 60-second encode.
        if (count >= self.settings.max_jobs
                or storage + 256 * 1024**2 > self.settings.max_storage_bytes
                or shutil.disk_usage(self.settings.jobs).free < self.settings.min_free_bytes):
            raise CapacityError("Local job/disk limit reached; archive jobs manually")

    def render(self, manifest: Manifest | dict, *, allow_short_test: bool = False) -> dict:
        # Revalidate even already-constructed models; context bypass never persists.
        data = manifest.model_dump() if isinstance(manifest, Manifest) else manifest
        manifest = parse_manifest(data, allow_short_test=allow_short_test)
        key = hashlib.sha256(
            f"{manifest.content_id}\0{manifest.script_version}".encode()
        ).hexdigest()
        with self.exclusive():
            self.recover_interrupted()
            # No second render for a content/version pair, even after a failure.
            for path in self.settings.jobs.glob("*/job.json"):
                existing = json.loads(path.read_text(encoding="utf-8"))
                if existing["content_version_key"] == key:
                    raise DuplicateError(
                        f"Content/version already attempted as job {existing['job_id']}; "
                        "inspect it or use a new script_version"
                    )
            self.check_capacity()
            painter = FramePainter(manifest, self.settings)
            job_id = uuid.uuid4().hex
            directory = self.settings.jobs / job_id
            directory.mkdir(mode=0o700)
            job = {
                "job_id": job_id, "content_id": manifest.content_id,
                "script_version": manifest.script_version, "content_version_key": key,
                "status": "rendering", "created_at": now(), "updated_at": now(),
                "test_only": manifest.duration < 25, "output": None,
                "editorial_approval": False, "publishing_approval": False,
            }
            atomic_json(directory / "job.json", job)
            try:
                atomic_json(directory / "manifest.json", manifest.model_dump())
                audio_path = directory / "narration.wav"
                job["audio"] = snapshot_audio(
                    manifest.narration_audio, audio_path, self.settings, manifest.duration)
                output_path = directory / manifest.output_name
                job["technical_checks"] = encode(
                    manifest, audio_path, output_path, painter, self.settings)
                job.update(status="rendered_needs_qa", output=str(output_path),
                           updated_at=now())
                atomic_json(directory / "job.json", job)
                return job
            except Exception as exc:
                message = str(exc) if isinstance(exc, FactoryError) else "Unexpected local render failure"
                job.update(status="failed", error=message, output=None, updated_at=now())
                atomic_json(directory / "job.json", job)
                LOGGER.exception("Job %s failed", job_id)
                if isinstance(exc, FactoryError):
                    exc.args = (f"{message} (job {job_id})",)
                    raise
                raise RenderError(f"{message} (job {job_id})") from exc
