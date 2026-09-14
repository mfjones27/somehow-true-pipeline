"""ElevenLabs narration. Always converts to 48 kHz mono WAV for the assembler."""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

import requests

from providers.env import load_env

load_env()

TTS_URL = "https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
DEFAULT_VOICE = "JBFqnCBsd6RMkjVDRZzb"
DEFAULT_MODEL = "eleven_multilingual_v2"


def synthesize(script: str, output_wav: Path, content_id: str = "unknown") -> Path:
    api_key = os.environ.get("ELEVENLABS_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("ELEVENLABS_API_KEY is missing")
    voice_id = os.environ.get("ELEVENLABS_VOICE_ID", DEFAULT_VOICE).strip() or DEFAULT_VOICE
    model_id = os.environ.get("ELEVENLABS_MODEL_ID", DEFAULT_MODEL).strip() or DEFAULT_MODEL

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
