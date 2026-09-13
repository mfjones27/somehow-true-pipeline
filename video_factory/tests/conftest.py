import array
import math
import sys
import wave

import pytest

from video_factory.config import Settings


def make_tone(path, duration, sample_rate=24000):
    """Generate test-only synthetic audio; never stand in for an approved narration."""
    path.parent.mkdir(parents=True, exist_ok=True)
    samples = array.array("h")
    for i in range(round(sample_rate * duration)):
        t = i / sample_rate
        fade = min(1, t / 0.08, (duration - t) / 0.08)
        samples.append(round(2000 * fade * math.sin(math.tau * 220 * t)))
    if sys.byteorder != "little":
        samples.byteswap()
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate)
        handle.writeframes(samples.tobytes())


@pytest.fixture
def manifest_data():
    return {
        "content_id": "test-content",
        "script_version": "v1",
        "duration": 25.0,
        "narration_audio": "narration.wav",
        "output_name": "final.mp4",
        "scenes": [
            {"start": 0.0, "end": 12.0, "text": "Motion meets clarity.",
             "narration_transcript": "Placeholder transcript. Not verified content.",
             "visual_style": "orbit"},
            {"start": 12.0, "end": 25.0, "text": "Explicit timing.",
             "narration_transcript": "Placeholder transcript. Not verified content.",
             "visual_style": "wave"},
        ],
        "captions": [
            {"start": 0.0, "end": 3.0, "text": "A technical fixture, not factual content."},
            {"start": 12.0, "end": 16.0, "text": "Timing comes from the manifest."},
        ],
    }


@pytest.fixture
def settings(tmp_path):
    return Settings(root=tmp_path, min_free_bytes=0)

