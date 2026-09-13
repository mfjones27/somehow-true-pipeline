"""Local, synchronous API. No CORS, remote assets, auth hosting, or publication."""

import ipaddress
import json

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from starlette.concurrency import run_in_threadpool

from .config import Settings
from .errors import FactoryError
from .jobs import JobStore
from .models import parse_manifest

MAX_BODY_BYTES = 128 * 1024


def strict_json(raw: bytes):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("Duplicate JSON keys are forbidden")
            result[key] = value
        return result

    def bad_constant(value):
        raise ValueError(f"Nonfinite JSON number: {value}")

    return json.loads(raw, object_pairs_hook=pairs, parse_constant=bad_constant)


class LocalOnly:
    """Check both client and Host; reject browser-origin mutation requests."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = {k.lower(): v for k, v in scope["headers"]}
        host = headers.get(b"host", b"").decode("latin1").split(":")[0]
        client = (scope.get("client") or ("", 0))[0]
        try:
            local = ipaddress.ip_address(client).is_loopback
        except ValueError:
            local = False
        if (not local or host not in ("localhost", "127.0.0.1")
                or b"origin" in headers or b"forwarded" in headers
                or any(k.startswith(b"x-forwarded-") for k in headers)
                or b"sec-fetch-site" in headers):
            response = JSONResponse({"error": "localhost_only"}, status_code=403)
            await response(scope, receive, send)
            return
        await self.app(scope, receive, send)


def create_app(settings: Settings | None = None):
    store = JobStore(settings)
    app = FastAPI(title="Local Video Factory", docs_url=None, redoc_url=None,
                  openapi_url=None)
    app.add_middleware(LocalOnly)
    app.state.store = store

    @app.get("/health")
    def health():
        return {"status": "ok", "scope": "local_prototype", "render_mode": "serial_synchronous",
                "tts": False, "publishing": False, "editorial_checks": False}

    @app.get("/jobs/{job_id}")
    def get_job(job_id: str):
        job = store.get(job_id)
        if job is None:
            raise HTTPException(404, "Job not found")
        return job

    @app.post("/render", status_code=201)
    async def render(request: Request):
        if request.headers.get("content-type", "").split(";")[0].strip() != "application/json":
            raise HTTPException(415, "Use application/json")
        raw = bytearray()
        async for chunk in request.stream():
            raw.extend(chunk)
            if len(raw) > MAX_BODY_BYTES:
                raise HTTPException(413, "Manifest exceeds 128 KiB")
        try:
            manifest = parse_manifest(strict_json(bytes(raw)))
        except ValidationError as exc:
            # Never echo arbitrary original input, NaN, or non-JSON exception context.
            return JSONResponse(
                {"error": "invalid_manifest",
                 "details": [{"location": list(e["loc"]), "message": e["msg"]}
                             for e in exc.errors()]}, status_code=422)
        except (ValueError, UnicodeError, RecursionError):
            raise HTTPException(400, "Invalid JSON object, duplicate keys, or nonfinite numbers")
        try:
            return await run_in_threadpool(store.render, manifest)
        except FactoryError as exc:
            return JSONResponse({"error": exc.code, "detail": str(exc)},
                                status_code=exc.status_code)
        except OSError:
            return JSONResponse({"error": "local_storage_error"}, status_code=500)

    return app

