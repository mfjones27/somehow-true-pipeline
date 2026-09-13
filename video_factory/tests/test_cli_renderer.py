import json
from dataclasses import replace

import pytest
import uvicorn

from video_factory.cli import main
from video_factory.errors import RenderError
from video_factory.jobs import JobStore
from video_factory.renderer import probe_output

from conftest import make_tone


def test_cli_server_is_loopback_single_worker(monkeypatch):
    seen = {}

    def run(app, **kwargs):
        seen.update(kwargs)

    monkeypatch.setattr(uvicorn, "run", run)
    assert main(["serve", "--port", "8765"]) == 0
    assert seen["host"] == "127.0.0.1"
    assert seen["workers"] == 1
    assert seen["proxy_headers"] is False
    assert seen["limit_concurrency"] == 8


def test_cli_has_no_short_test_or_host_override():
    with pytest.raises(SystemExit):
        main(["serve", "--host", "0.0.0.0"])
    with pytest.raises(SystemExit):
        main(["render", "x.json", "--allow-short-test"])


def test_cli_rejects_invalid_manifest_without_running(tmp_path, capsys):
    path = tmp_path / "invalid.json"
    path.write_text('{"duration":25,"duration":30}')
    assert main(["render", str(path)]) == 1
    assert "Duplicate JSON keys" in capsys.readouterr().err


def test_encoder_failure_cannot_report_success(settings, manifest_data):
    manifest_data.update(duration=3.0)
    manifest_data["scenes"] = [dict(manifest_data["scenes"][0], end=3.0)]
    manifest_data["captions"] = [dict(manifest_data["captions"][0], end=3.0)]
    make_tone(settings.assets / "narration.wav", 3)
    store = JobStore(replace(settings, ffmpeg="/usr/bin/false"))
    with pytest.raises(RenderError):
        store.render(manifest_data, allow_short_test=True)
    record = json.loads(next(settings.jobs.glob("*/job.json")).read_text())
    assert record["status"] == "failed"
    assert record["output"] is None
    assert not list(settings.jobs.glob("*/final.mp4"))


def test_invalid_encoded_file_fails_probe(settings):
    path = settings.root / "not-a-video.mp4"
    path.write_bytes(b"not an mp4")
    with pytest.raises(RenderError, match="technical validation"):
        probe_output(path, 3, settings)
