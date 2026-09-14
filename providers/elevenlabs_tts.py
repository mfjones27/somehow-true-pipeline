"""ElevenLabs narration. Always converts to 48 kHz mono WAV for the assembler."""
from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

import requests

from providers.env import load_env

load_env()

TTS_URL = "https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
DEFAULT_VOICE = "JBFqnCBsd6RMkjVDRZzb"
DEFAULT_MODEL = "eleven_multilingual_v2"

_MD_LINK = re.compile(r"!?\[[^\]]*\]\(\s*https?://[^)]+\)", re.I)
_BARE_URL = re.compile(r"https?://\S+", re.I)
_DOI = re.compile(r"\bdoi:\s*\S+", re.I)
_DOMAIN_CITE = re.compile(
    r"\([^)]*(?:https?://|www\.|\.(?:com|org|net|edu|gov|be|uk|io|pdf)\b)[^)]*\)",
    re.I,
)
_EMPTY_PARENS = re.compile(r"\(\s*\)")
_SPACE_BEFORE_PUNCT = re.compile(r"\s+([,.;:!?])")


def spoken_script(text: str) -> str:
    """Strip URLs and markdown citations so ElevenLabs does not read them aloud."""
    text = (text or "").replace("\u00a0", " ")
    text = _MD_LINK.sub("", text)
    text = _BARE_URL.sub("", text)
    text = _DOI.sub("", text)
    text = _DOMAIN_CITE.sub("", text)
    text = _EMPTY_PARENS.sub("", text)
    text = re.sub(r"[*_`]+", "", text)
    text = _SPACE_BEFORE_PUNCT.sub(r"\1", text)
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    return text.strip()


def synthesize(script: str, output_wav: Path, content_id: str = "unknown") -> Path:
    api_key = os.environ.get("ELEVENLABS_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("ELEVENLABS_API_KEY is missing")
    voice_id = os.environ.get("ELEVENLABS_VOICE_ID", DEFAULT_VOICE).strip() or DEFAULT_VOICE
    model_id = os.environ.get("ELEVENLABS_MODEL_ID", DEFAULT_MODEL).strip() or DEFAULT_MODEL

    script = spoken_script(script)
    if not script:
        raise RuntimeError("Narration script was empty after stripping URLs and citations")

    output_wav = Path(output_wav)
    output_wav.parent.mkdir(parents=True, exist_ok=True)
    mp3_path = output_wav.with_suffix(".mp3")

    payload = {"text": script, "model_id": model_id}
    url = TTS_URL.format(voice_id=voice_id)
    resp = None
    for headers in (
        {"xi-api-key": api_key, "Accept": "audio/mpeg", "Content-Type": "application/json"},
        {"Authorization": f"Bearer {api_key}", "Accept": "audio/mpeg", "Content-Type": "application/json"},
    ):
        resp = requests.post(url, headers=headers, json=payload, timeout=120)
        if resp.ok:
            break
    if resp is None or not resp.ok:
        detail = (resp.text if resp is not None else "")[:400]
        raise RuntimeError(f"ElevenLabs TTS failed ({resp.status_code if resp is not None else 'no response'}): {detail}")
    mp3_path.write_bytes(resp.content)
    from providers.costs import elevenlabs_usage
    elevenlabs_usage(content_id, len(script), model_id)

    result = subprocess.run(
        [
            "ffmpeg", "-hide_banner", "-y",
            "-i", str(mp3_path),
            "-ar", "48000", "-ac", "1", "-c:a", "pcm_s16le",
            str(output_wav),
        ],
        capture_output=True, text=True,
    )
    if result.returncode:
        raise RuntimeError(f"ffmpeg failed converting narration:\n{result.stderr[-2000:]}")
    mp3_path.unlink(missing_ok=True)
    return output_wav
