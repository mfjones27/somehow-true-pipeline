"""Offline idle-mode regression tests; no test client or provider SDK required.

Run from the repository root:
    python -m unittest discover -s tests -v
"""
import asyncio
from contextlib import ExitStack
import importlib
import json
import os
from pathlib import Path
import runpy
import unittest
from unittest.mock import patch


async def request(app, path, method="GET", authorization=None, body=b"{}"):
    """Exercise the ASGI stack in memory, without opening a network socket."""
    messages = []
    body_sent = False
    finished = asyncio.Event()
    headers = [(b"content-type", b"application/json")]
    if authorization is not None:
        headers.append((b"authorization", authorization.encode()))
    scope = {
        "type": "http", "asgi": {"version": "3.0", "spec_version": "2.4"},
        "http_version": "1.1", "method": method, "scheme": "http",
        "path": path, "raw_path": path.encode(), "query_string": b"",
        "root_path": "", "headers": headers,
        "client": ("127.0.0.1", 12345), "server": ("test", 80),
    }

    async def receive():
        nonlocal body_sent
        if not body_sent:
            body_sent = True
            return {"type": "http.request", "body": body, "more_body": False}
        await finished.wait()
        return {"type": "http.disconnect"}

    async def send(message):
        messages.append(message)
        if message["type"] == "http.response.body" and not message.get("more_body", False):
            finished.set()

    await asyncio.wait_for(app(scope, receive, send), timeout=5)
    status = next(m["status"] for m in messages if m["type"] == "http.response.start")
    payload = b"".join(m.get("body", b"") for m in messages if m["type"] == "http.response.body")
    return status, json.loads(payload) if payload else None


class IdleDeploymentTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.dict(os.environ, {"API_TOKEN": "offline-test-token"}))
        os.environ.pop("PIPELINE_ENABLED", None)
        self.calls = []
        # Apply these before importing the app so startup is covered too.
        for target in (
            "subprocess.run", "subprocess.Popen", "socket.create_connection",
            "socket.socket.connect", "pathlib.Path.mkdir", "pathlib.Path.write_text",
            "fastapi.BackgroundTasks.add_task",
        ):
            self.calls.append(self.stack.enter_context(
                patch(target, side_effect=AssertionError(f"Forbidden side effect: {target}"))
            ))
        self.module = importlib.import_module("app")
        self.module.JOBS.clear()
        self.addCleanup(self.assert_no_side_effects)

    def assert_no_side_effects(self):
        for mocked in self.calls:
            mocked.assert_not_called()
        self.assertEqual(self.module.JOBS, {})

    async def test_health_is_public_and_successful(self):
        os.environ.pop("API_TOKEN", None)
        status, data = await request(self.module.app, "/health")
        self.assertEqual(status, 200)
        self.assertEqual(data["status"], "ok")

    async def test_startup_and_shutdown_are_idle(self):
        async with self.module.app.router.lifespan_context(self.module.app):
            self.assertEqual(self.module.JOBS, {})

    async def test_produce_is_disabled_by_default_before_validation(self):
        for path in ("/produce", "/produce/daily", "/produce/", "/produce/daily/"):
            with self.subTest(path=path):
                status, _ = await request(
                    self.module.app, path, "POST", "Bearer offline-test-token", b"invalid json"
                )
                self.assertEqual(status, 503)

    async def test_false_and_unknown_flags_fail_closed(self):
        for flag in ("false", "", "0", "1", "yes", "invalid"):
            os.environ["PIPELINE_ENABLED"] = flag
            for path in ("/produce", "/produce/daily"):
                with self.subTest(flag=flag, path=path):
                    status, _ = await request(
                        self.module.app, path, "POST", "Bearer offline-test-token"
                    )
                    self.assertEqual(status, 503)

    async def test_unauthorized_requests_never_reach_routes(self):
        os.environ["PIPELINE_ENABLED"] = "true"
        for path, method in (
            ("/queue", "GET"), ("/jobs/example", "GET"), ("/produce", "POST"),
            ("/produce/daily", "POST"), ("/docs", "GET"), ("/openapi.json", "GET"),
            ("/redoc", "GET"), ("/unknown", "GET"), ("/health", "POST"),
        ):
            for authorization in (None, "Bearer wrong", "Basic offline-test-token", "Bearer "):
                with self.subTest(path=path, authorization=authorization):
                    status, _ = await request(self.module.app, path, method, authorization)
                    self.assertEqual(status, 401)

    async def test_missing_or_blank_server_token_denies_access(self):
        for token in (None, "", "   "):
            if token is None:
                os.environ.pop("API_TOKEN", None)
            else:
                os.environ["API_TOKEN"] = token
            for path, method in (("/queue", "GET"), ("/produce", "POST"), ("/produce/daily", "POST")):
                with self.subTest(token=token, path=path):
                    status, _ = await request(
                        self.module.app, path, method, "Bearer offline-test-token"
                    )
                    self.assertEqual(status, 401)

    async def test_documentation_is_disabled_even_when_authenticated(self):
        for path in ("/docs", "/redoc", "/openapi.json"):
            status, _ = await request(
                self.module.app, path, authorization="Bearer offline-test-token"
            )
            self.assertEqual(status, 404)

    async def test_authenticated_read_only_job_route(self):
        status, _ = await request(
            self.module.app, "/jobs/absent", authorization="Bearer offline-test-token"
        )
        self.assertEqual(status, 404)

    async def test_entrypoint_honors_port_without_starting_server(self):
        with patch.dict(os.environ, {"PORT": "9876"}), patch("uvicorn.run") as run:
            runpy.run_path(str(Path(self.module.__file__)), run_name="__main__")
        self.assertEqual(run.call_args.kwargs, {"host": "0.0.0.0", "port": 9876})
        self.assertEqual(run.call_count, 1)


if __name__ == "__main__":
    unittest.main()
