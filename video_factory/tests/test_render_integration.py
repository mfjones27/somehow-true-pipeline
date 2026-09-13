import json
import subprocess
import uuid
from pathlib import Path

import pytest

from video_factory.config import PROJECT_ROOT, Settings
from video_factory.errors import DuplicateError
from video_factory.jobs import JobStore, atomic_json

from conftest import make_tone


def test_three_second_technical_clip_has_expected_streams():
    # Keep evidence in the project, rather than deleting the integration render.
    root = PROJECT_ROOT / "test_artifacts" / uuid.uuid4().hex
    settings = Settings(root=root)
    make_tone(settings.assets / "synthetic-tone.wav", 3.0)
    styles = ["orbit", "wave", "network", "pulse"]
    titles = ["Motion meets clarity.", "Timing is explicit.", "Original diagrams.", "Technical test only."]
    data = {
        "content_id": "technical-test-not-factual-content",
        "script_version": "test-v1", "duration": 3.0,
        "narration_audio": "synthetic-tone.wav", "output_name": "technical-test.mp4",
        "scenes": [
            {"start": i * 0.75, "end": (i+1) * 0.75, "text": titles[i],
             "narration_transcript": "No speech. Synthetic 220 Hz test tone.",
             "visual_style": style}
            for i, style in enumerate(styles)
        ],
        "captions": [
            {"start": 0.0, "end": 1.5, "text": "Synthetic tone. Technical test only."},
            {"start": 1.5, "end": 3.0, "text": "Not a finished factual video."},
        ],
    }
    store = JobStore(settings)
    result = store.render(data, allow_short_test=True)
    assert result["status"] == "rendered_needs_qa" and result["test_only"] is True
    assert not result["editorial_approval"] and not result["publishing_approval"]
    output = Path(result["output"])
    assert output.is_file()
    probe = subprocess.run(
        ["/usr/bin/ffprobe", "-v", "error", "-show_streams", "-show_format",
         "-of", "json", str(output)], check=True, capture_output=True, text=True)
    info = json.loads(probe.stdout)
    video = next(s for s in info["streams"] if s["codec_type"] == "video")
    audio = next(s for s in info["streams"] if s["codec_type"] == "audio")
    assert (video["width"], video["height"]) == (1080, 1920)
    assert video["codec_name"] == "h264"
    assert video["pix_fmt"] == "yuv420p"
    assert video["r_frame_rate"] == "30/1"
    assert video["nb_frames"] == "90"
    assert audio["codec_name"] == "aac"
    assert abs(float(info["format"]["duration"]) - 3) <= 0.1
    assert not output.with_suffix(".partial.mp4").exists()
    with pytest.raises(DuplicateError):
        JobStore(settings).render(data, allow_short_test=True)
    atomic_json(root / "ffprobe.json", info)
    atomic_json(root / "test_result.json", result)
    print(f"\nTECHNICAL_TEST_OUTPUT={output}")
    print(f"TECHNICAL_TEST_PREVIEW={output.parent / 'preview.png'}")
