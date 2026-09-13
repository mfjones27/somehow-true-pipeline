import pytest
from PIL import ImageChops, ImageDraw

from video_factory.config import Settings
from video_factory.graphics import BELGIAN, LIME, FramePainter
from video_factory.models import parse_manifest


@pytest.mark.parametrize("style", ["nested-enclaves", "border-house"])
def test_schematic_styles_are_whitelisted_and_animated(manifest_data, style):
    manifest_data["scenes"][0]["visual_style"] = style
    painter = FramePainter(parse_manifest(manifest_data), Settings())
    early = painter.frame(0).crop((100, 690, 900, 1160))
    later = painter.frame(0.6).crop((100, 690, 900, 1160))
    assert ImageChops.difference(early, later).getbbox() is not None
    assert BELGIAN != LIME


@pytest.mark.parametrize("style,labels", [
    ("nested-enclaves", ["Dutch", "Belgian", "Dutch"]),
    ("border-house", ["Netherlands", "Belgium"]),
])
def test_schematic_labels_disclaimer_and_safe_region(manifest_data, style, labels, monkeypatch):
    manifest_data["scenes"][0]["visual_style"] = style
    drawn = []
    original = ImageDraw.ImageDraw.text

    def record(draw, xy, text, **kwargs):
        bounds = draw.textbbox(xy, text, **{
            key: value for key, value in kwargs.items() if key in ("font", "anchor")
        })
        drawn.append((text, bounds))
        return original(draw, xy, text, **kwargs)

    monkeypatch.setattr(ImageDraw.ImageDraw, "text", record)
    painter = FramePainter(parse_manifest(manifest_data), Settings())
    painter.frame(1)
    texts = [text for text, _ in drawn]
    assert "SCHEMATIC NOT A MAP" in texts
    assert [text for text in texts if text in labels] == labels
    assert "THINGS THAT SOUND FAKE" in texts
    assert not any("SYNTHETIC" in text or "FACT CHECK" in text for text in texts)
    for text, (left, top, right, bottom) in drawn:
        assert 100 <= left <= right <= 900, text
        assert 200 <= top <= bottom <= 1550, text


def test_short_technical_manifest_still_has_test_header(manifest_data, monkeypatch):
    manifest_data["duration"] = 3.0
    manifest_data["scenes"] = [dict(manifest_data["scenes"][0], end=3.0,
                                     visual_style="nested-enclaves")]
    manifest_data["captions"] = [dict(manifest_data["captions"][0], end=3.0)]
    drawn = []
    original = ImageDraw.ImageDraw.text

    def record(draw, xy, text, **kwargs):
        drawn.append(text)
        return original(draw, xy, text, **kwargs)

    monkeypatch.setattr(ImageDraw.ImageDraw, "text", record)
    FramePainter(parse_manifest(manifest_data, allow_short_test=True), Settings()).frame(1)
    assert "TECHNICAL TEST / SYNTHETIC AUDIO" in drawn
    assert "THINGS THAT SOUND FAKE" not in drawn
