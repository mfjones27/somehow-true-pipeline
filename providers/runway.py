"""Locked Runway text-to-video settings. Always Seedance 2.5 at 1080p 9:16."""
from __future__ import annotations

from pathlib import Path

# Newest cinematic TTV model on Runway Dev. Native 1080p 9:16 matches Shorts output.
RUNWAY_MODEL = "seedance2_5"
RUNWAY_RATIO = "1080:1920"
RUNWAY_AUDIO = False
RUNWAY_MIN_DURATION = 4
RUNWAY_MAX_DURATION = 15
PROMPT_MAX_UNITS = 14_000
PROMPT_MIN_BODY = 400

STYLE_LOCK = (
    "Portrait 9:16 cinematic photoreal illustration, 1080x1920. "
    "35mm spherical lens, shallow depth of field, warm film grade, fine grain, "
    "natural physically plausible motion."
)

HARD_BANS = (
    "No on-screen text, numbers, captions, subtitles, logos, watermarks, UI, "
    "lower-third graphics, or readable signage. No real celebrity or public-figure faces. "
    "No documentary talking-head, stock b-roll, or generic drone establishing shot. "
    "Keep the bottom third of the frame empty and visually calm for captions. "
    "One continuous camera move, no cuts, no morphs, no scene changes."
)

_GENERIC = (
    "cinematic shot of a fictional",
    "cinematic travel-documentary",
    "evoking the concept of",
    "abstract scene with rich textures",
)


def utf16_units(text: str) -> int:
    return len(text.encode("utf-16-le")) // 2


def clip_prompt(text: str, max_units: int = PROMPT_MAX_UNITS) -> str:
    text = " ".join((text or "").split())
    if utf16_units(text) <= max_units:
        return text
    lo, hi = 0, len(text)
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if utf16_units(text[:mid]) <= max_units:
            lo = mid
        else:
            hi = mid - 1
    return text[:lo].rstrip(" ,;")


def clamp_duration(seconds: int | float) -> int:
    return max(RUNWAY_MIN_DURATION, min(RUNWAY_MAX_DURATION, int(seconds)))


def lock_runway_config(config: dict) -> dict:
    config["runway_model"] = RUNWAY_MODEL
    config["runway_ratio"] = RUNWAY_RATIO
    config["runway_audio"] = RUNWAY_AUDIO
    return config


def prepare_prompt(text: str) -> str:
    prompt = " ".join((text or "").split()).rstrip(".")
    if not prompt:
        raise RuntimeError("Empty Runway prompt")
    lower = prompt.lower()
    if "no on-screen text" not in lower and "no text" not in lower:
        prompt = f"{prompt}. {HARD_BANS}"
    if "9:16" not in lower and "1080" not in lower and "portrait" not in lower:
        prompt = f"{STYLE_LOCK} {prompt}"
    return clip_prompt(prompt)


def prompt_problems(prompt: str) -> list[str]:
    prompt = " ".join((prompt or "").split())
    body = prompt
    for extra in (HARD_BANS, STYLE_LOCK):
        body = body.replace(extra, "")
    body = " ".join(body.split())
    lower = body.lower()
    issues: list[str] = []
    if len(body) < PROMPT_MIN_BODY:
        issues.append("visual body too short")
    if any(marker in lower for marker in _GENERIC):
        issues.append("generic stock-footage language")
    camera = ("camera", "dolly", "lens", "close-up", "close up", "wide", "tracking",
              "crane", "pan", "push-in", "push in", "pull back", "handheld", "locked-off",
              "locked off", "macro", "aerial", "over-the-shoulder")
    if not any(word in lower for word in camera):
        issues.append("no camera language")
    light = ("light", "sun", "lamp", "glow", "grade", "golden", "shadow", "overcast",
             "practical", "neon", "daylight", "moon", "fire")
    if not any(word in lower for word in light):
        issues.append("no lighting")
    return issues


def weak_prompts(prompts: list[str]) -> list[tuple[int, list[str]]]:
    flagged = []
    for i, prompt in enumerate(prompts):
        issues = prompt_problems(prompt)
        if issues:
            flagged.append((i, issues))
    return flagged


def text_to_video_request(prompt: str, duration: int) -> dict:
    return {
        "model": RUNWAY_MODEL,
        "promptText": prepare_prompt(prompt),
        "duration": clamp_duration(duration),
        "ratio": RUNWAY_RATIO,
        "audio": RUNWAY_AUDIO,
    }


def clip_file_issues(
    path: Path,
    probe: dict,
    expected_seconds: float | None = None,
    *,
    require_1080: bool = True,
) -> list[str]:
    issues: list[str] = []
    if not path.exists():
        return ["missing file"]
    if path.stat().st_size < 80_000:
        issues.append("file too small")
    video = next((s for s in probe.get("streams") or [] if s.get("codec_type") == "video"), None)
    if video is None:
        issues.append("no video stream")
        return issues
    width, height = int(video["width"]), int(video["height"])
    if require_1080 and (width, height) != (1080, 1920):
        issues.append(f"{width}x{height}, expected 1080x1920")
    elif width < 720 or height < 1280:
        issues.append(f"{width}x{height} is below 720x1280")
    duration = float(video.get("duration") or (probe.get("format") or {}).get("duration") or 0)
    if duration < 3:
        issues.append(f"only {duration:.2f}s long")
    if expected_seconds and abs(duration - float(expected_seconds)) > 1.5:
        issues.append(f"duration {duration:.2f}s vs requested {expected_seconds}s")
    return issues
