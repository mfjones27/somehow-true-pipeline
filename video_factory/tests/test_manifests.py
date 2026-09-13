import pytest
from pydantic import ValidationError

from video_factory.api import strict_json
from video_factory.config import Settings
from video_factory.errors import FactoryError
from video_factory.graphics import FramePainter
from video_factory.models import parse_manifest


def test_valid_explicit_manifest(manifest_data):
    manifest = parse_manifest(manifest_data)
    assert manifest.duration == 25
    assert manifest.scenes[0].narration_transcript
    assert manifest.captions[0].start == 0


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -1.0, 61.0, True, "25"])
def test_invalid_duration(manifest_data, value):
    manifest_data["duration"] = value
    with pytest.raises(ValidationError):
        parse_manifest(manifest_data)


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf"), True])
@pytest.mark.parametrize("kind", ["scenes", "captions"])
@pytest.mark.parametrize("field", ["start", "end"])
def test_all_segment_times_finite(manifest_data, value, kind, field):
    manifest_data[kind][0][field] = value
    with pytest.raises(ValidationError):
        parse_manifest(manifest_data)


@pytest.mark.parametrize("path", [
    "../outside.wav", "/tmp/narration.wav", "nested/../voice.wav",
    "./voice.wav", "nested//voice.wav", "https://host/voice.wav",
    "file:voice.wav", "voice.wav;touch-hacked", "voice.mp3",
    "voice.WAV", r"nested\voice.wav", "C:/voice.wav", "-input.wav",
])
def test_asset_traversal_and_unsupported_paths(manifest_data, path):
    manifest_data["narration_audio"] = path
    with pytest.raises(ValidationError):
        parse_manifest(manifest_data)


@pytest.mark.parametrize("field,value", [
    ("output_name", "../final.mp4"), ("output_name", "/tmp/final.mp4"),
    ("output_name", "x.mp4;echo"), ("content_id", "../id"),
    ("script_version", "v1;touch"),
])
def test_safe_names(manifest_data, field, value):
    manifest_data[field] = value
    with pytest.raises(ValidationError):
        parse_manifest(manifest_data)


@pytest.mark.parametrize("mutate", [
    lambda d: d["scenes"].reverse(),
    lambda d: d["scenes"][0].update(start=0.1),
    lambda d: d["scenes"][1].update(start=12.1),
    lambda d: d["scenes"][1].update(start=11.0),
    lambda d: d["scenes"][1].update(end=26.0),
    lambda d: d["scenes"][1].update(end=24.0),
    lambda d: d["captions"].reverse(),
    lambda d: d["captions"][1].update(start=2.0),
    lambda d: d["captions"][1].update(end=26.0),
    lambda d: d["captions"][0].update(end=0.0),
    lambda d: d["scenes"][0].update(visual_style="external_asset"),
    lambda d: d.update(shell_command="echo unsafe"),
    lambda d: d.update(allow_short_test=True),
    lambda d: d["scenes"][0].update(text="   "),
    lambda d: d["captions"][0].update(text="Invisible\u202econtrol"),
])
def test_invalid_timeline_and_fields(manifest_data, mutate):
    mutate(manifest_data)
    with pytest.raises(ValidationError):
        parse_manifest(manifest_data)


def test_short_test_bypass_is_explicit_and_not_serialized(manifest_data):
    manifest_data.update(duration=3.0)
    manifest_data["scenes"] = [dict(manifest_data["scenes"][0], end=3.0)]
    manifest_data["captions"] = [dict(manifest_data["captions"][0], end=3.0)]
    with pytest.raises(ValidationError):
        parse_manifest(manifest_data)
    manifest = parse_manifest(manifest_data, allow_short_test=True)
    assert "allow_short_test" not in manifest.model_dump()
    with pytest.raises(ValidationError):
        parse_manifest(manifest.model_dump())


def test_large_unbreakable_title_rejected(manifest_data):
    manifest_data["scenes"][0]["text"] = "W" * 80
    with pytest.raises(FactoryError, match="cannot fit"):
        FramePainter(parse_manifest(manifest_data), Settings())


@pytest.mark.parametrize("raw", [
    b'{"duration":25,"duration":30}', b'{"duration":NaN}', b'{"duration":Infinity}',
    b'{"scenes":[{"start":0,"start":1}]}',
])
def test_ambiguous_json_rejected(raw):
    with pytest.raises(ValueError):
        strict_json(raw)

