import json
from dataclasses import replace

import pytest

from video_factory.assets import snapshot_audio
from video_factory.errors import BusyError, CapacityError, DuplicateError, FactoryError
from video_factory.jobs import JobStore, atomic_json

from conftest import make_tone


def test_valid_pcm_snapshot(settings):
    make_tone(settings.assets / "nested/voice.wav", 3)
    destination = settings.root / "copy.wav"
    info = snapshot_audio("nested/voice.wav", destination, settings, 3)
    assert info["duration"] == 3
    assert destination.read_bytes() == (settings.assets / "nested/voice.wav").read_bytes()


@pytest.mark.parametrize("directory", [False, True])
def test_symlinks_rejected(settings, directory):
    settings.assets.mkdir()
    make_tone(settings.root / "outside/voice.wav", 3)
    if directory:
        (settings.assets / "escape").symlink_to(settings.root / "outside", target_is_directory=True)
        name = "escape/voice.wav"
    else:
        (settings.assets / "voice.wav").symlink_to(settings.root / "outside/voice.wav")
        name = "voice.wav"
    with pytest.raises(FactoryError):
        snapshot_audio(name, settings.root / "copy.wav", settings, 3)


def test_fifo_rejected_without_blocking(settings):
    import os
    settings.assets.mkdir()
    os.mkfifo(settings.assets / "voice.wav")
    with pytest.raises(FactoryError, match="regular"):
        snapshot_audio("voice.wav", settings.root / "copy.wav", settings, 3)


def test_audio_duration_must_match(settings):
    make_tone(settings.assets / "voice.wav", 3)
    with pytest.raises(FactoryError, match="duration"):
        snapshot_audio("voice.wav", settings.root / "copy.wav", settings, 25)


def test_audio_size_bounded(settings):
    make_tone(settings.assets / "voice.wav", 3)
    with pytest.raises(FactoryError, match="limit"):
        snapshot_audio("voice.wav", settings.root / "copy.wav",
                       replace(settings, max_audio_bytes=100), 3)


def test_truncated_audio_rejected(settings):
    make_tone(settings.assets / "voice.wav", 3)
    path = settings.assets / "voice.wav"
    path.write_bytes(path.read_bytes()[:-1000])
    with pytest.raises(FactoryError, match="truncated"):
        snapshot_audio("voice.wav", settings.root / "copy.wav", settings, 3)


def test_fake_wav_cannot_be_playlist(settings):
    settings.assets.mkdir()
    (settings.assets / "voice.wav").write_text("https://example.invalid/voice.wav")
    with pytest.raises(FactoryError, match="supported"):
        snapshot_audio("voice.wav", settings.root / "copy.wav", settings, 3)


def test_render_lock_is_cross_instance(settings, manifest_data):
    first, second = JobStore(settings), JobStore(settings)
    with first.exclusive():
        with pytest.raises(BusyError):
            second.render(manifest_data)


def test_failure_persists_and_duplicate_is_disallowed(settings, manifest_data):
    store = JobStore(settings)
    with pytest.raises(FactoryError, match="job"):
        store.render(manifest_data)  # Deliberately missing WAV.
    path = next(settings.jobs.glob("*/job.json"))
    job = json.loads(path.read_text())
    assert job["status"] == "failed"
    assert job["output"] is None
    assert store.get(job["job_id"])["status"] == "failed"
    with pytest.raises(DuplicateError):
        JobStore(settings).render(manifest_data)
    assert len(list(settings.jobs.glob("*/job.json"))) == 1


def test_capacity_checked_before_job_creation(settings, manifest_data):
    store = JobStore(replace(settings, max_jobs=0))
    with pytest.raises(CapacityError):
        store.render(manifest_data)
    assert not list(settings.jobs.glob("*/job.json"))


def test_job_id_validation(settings):
    store = JobStore(settings)
    assert store.get("../assets") is None
    assert store.get("a" * 32) is None


def test_interrupted_state_recovered(settings):
    store = JobStore(settings)
    job_id = "a" * 32
    folder = settings.jobs / job_id
    folder.mkdir()
    atomic_json(folder / "job.json",
                {"job_id": job_id, "status": "rendering", "content_version_key": "unused"})
    assert store.get(job_id)["status"] == "failed"

