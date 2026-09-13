"""ASGI tests use stdlib only; no external HTTP client dependency."""

import asyncio
import json

import pytest

from video_factory.api import MAX_BODY_BYTES, create_app


def request(app, method="GET", path="/health", body=b"", headers=None,
            client="127.0.0.1", host="127.0.0.1:8765"):
    async def run():
        sent = []
        used = False

        async def receive():
            nonlocal used
            if not used:
                used = True
                return {"type": "http.request", "body": body, "more_body": False}
            return {"type": "http.disconnect"}

        async def send(message):
            sent.append(message)

        all_headers = [(b"host", host.encode())]
        all_headers.extend((k.encode(), v.encode()) for k, v in (headers or {}).items())
        await app(
            {"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1",
             "method": method, "scheme": "http", "path": path, "raw_path": path.encode(),
             "query_string": b"", "headers": all_headers,
             "client": (client, 45000), "server": ("127.0.0.1", 8765)},
            receive, send,
        )
        status = next(m["status"] for m in sent if m["type"] == "http.response.start")
        raw = b"".join(m.get("body", b"") for m in sent if m["type"] == "http.response.body")
        return status, json.loads(raw) if raw else None

    return asyncio.run(run())


def test_health_and_unknown_job(settings):
    app = create_app(settings)
    status, body = request(app)
    assert status == 200 and body["tts"] is False
    assert request(app, path="/jobs/not-a-job")[0] == 404
    assert request(app, path="/docs")[0] == 404


@pytest.mark.parametrize("kwargs", [
    {"client": "203.0.113.7"}, {"host": "evil.example"},
    {"headers": {"origin": "https://evil.example"}},
    {"headers": {"origin": "http://localhost:8765"}},
    {"headers": {"x-forwarded-for": "127.0.0.1"}},
    {"headers": {"forwarded": "for=127.0.0.1"}},
    {"headers": {"sec-fetch-site": "cross-site"}},
])
def test_nonlocal_and_browser_requests_rejected(settings, kwargs):
    assert request(create_app(settings), **kwargs)[0] == 403


def test_media_type_and_size_limits(settings):
    app = create_app(settings)
    assert request(app, "POST", "/render", b"{}")[0] == 415
    assert request(app, "POST", "/render", b"x" * (MAX_BODY_BYTES + 1),
                   {"content-type": "application/json"})[0] == 413


def test_invalid_manifest_and_json(settings):
    app = create_app(settings)
    for raw, expected in [(b"{}", 422), (b'{"x":NaN}', 400),
                          (b'{"x":1,"x":2}', 400), (b"[]", 422), (b"null", 422)]:
        assert request(app, "POST", "/render", raw,
                       {"content-type": "application/json"})[0] == expected


def test_api_never_accepts_short_test_flag(settings, manifest_data):
    manifest_data["allow_short_test"] = True
    manifest_data["duration"] = 3.0
    status, _ = request(create_app(settings), "POST", "/render",
                        json.dumps(manifest_data).encode(), {"content-type": "application/json"})
    assert status == 422
    assert not list(settings.jobs.glob("*/job.json"))


def test_missing_audio_and_duplicate_have_honest_states(settings, manifest_data):
    app = create_app(settings)
    body = json.dumps(manifest_data).encode()
    assert request(app, "POST", "/render", body, {"content-type": "application/json"})[0] == 400
    assert request(app, "POST", "/render", body, {"content-type": "application/json"})[0] == 409
    job_path = next(settings.jobs.glob("*/job.json"))
    status, job = request(app, path=f"/jobs/{job_path.parent.name}")
    assert status == 200 and job["status"] == "failed" and job["output"] is None


def test_busy_returns_429_without_queue(settings, manifest_data):
    app = create_app(settings)
    with app.state.store.exclusive():
        status, body = request(app, "POST", "/render", json.dumps(manifest_data).encode(),
                               {"content-type": "application/json"})
    assert status == 429 and body["error"] == "renderer_busy"


def test_successful_route_returns_201_after_store_completion(settings, manifest_data, monkeypatch):
    # Route unit test; the separate integration test uses the real encoder.
    app = create_app(settings)
    calls = []

    def completed_render(manifest):
        calls.append(manifest.content_id)
        return {"job_id": "b" * 32, "status": "rendered_needs_qa",
                "editorial_approval": False, "publishing_approval": False}

    monkeypatch.setattr(app.state.store, "render", completed_render)
    status, body = request(app, "POST", "/render", json.dumps(manifest_data).encode(),
                           {"content-type": "application/json"})
    assert calls == [manifest_data["content_id"]]
    assert status == 201 and body["status"] == "rendered_needs_qa"
