"""Keep burned-in Shorts captions inside the 1080x1920 frame."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from PIL import ImageFont

FRAME_WIDTH = 1080
FRAME_HEIGHT = 1920
SIDE_MARGIN = 90
CAPTION_POS_X = FRAME_WIDTH // 2
CAPTION_POS_Y = 1400
CAPTION_MAX_WIDTH = FRAME_WIDTH - 2 * SIDE_MARGIN
CAPTION_MAX_WORDS = 3
MIN_FONT_SIZE = 40


@lru_cache(maxsize=32)
def load_font(path: str, size: int):
    candidates = [
        path,
        r"C:\Windows\Fonts\arialbd.ttf",
        r"C:\Windows\Fonts\Arial.ttf",
        "/usr/share/fonts/truetype/lato/Lato-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    ]
    for candidate in candidates:
        if candidate and Path(candidate).exists():
            return ImageFont.truetype(candidate, size=size)
    return ImageFont.load_default()


def measure_text(text: str, font_path: str, font_size: int) -> float:
    return float(load_font(font_path, font_size).getlength(text))


def scale_font_to_fit(text: str, font_path: str, font_size: int, max_width: int = CAPTION_MAX_WIDTH) -> int:
    size = int(font_size)
    while size > MIN_FONT_SIZE and measure_text(text, font_path, size) > max_width:
        size -= 2
    return size


def fit_caption_phrases(
    phrases: list[str],
    font_path: str,
    font_size: int,
    max_width: int = CAPTION_MAX_WIDTH,
    max_words: int = CAPTION_MAX_WORDS,
) -> list[str]:
    """Split phrases so each on-screen line fits the frame."""
    fitted: list[str] = []
    for phrase in phrases:
        words = [word for word in str(phrase).split() if word]
        if not words:
            continue
        buf: list[str] = []
        for word in words:
            trial = " ".join(buf + [word])
            too_many = bool(buf) and len(buf) >= max_words
            too_wide = bool(buf) and measure_text(trial, font_path, font_size) > max_width
            if too_many or too_wide:
                fitted.append(" ".join(buf))
                buf = [word]
            else:
                buf.append(word)
        if buf:
            fitted.append(" ".join(buf))
    return fitted


def lock_caption_style(config: dict) -> dict:
    style = dict(config.get("caption_style") or {})
    style["pos_x"] = CAPTION_POS_X
    style["pos_y"] = int(style.get("pos_y") or CAPTION_POS_Y)
    style["max_width_px"] = CAPTION_MAX_WIDTH
    color = str(style.get("active_word_color") or "&H87E2C5").rstrip("&")
    if not color.startswith("&H"):
        color = "&H87E2C5"
    style["active_word_color"] = color
    config["caption_style"] = style
    config["caption_font_size"] = int(config.get("caption_font_size") or 66)
    return config
