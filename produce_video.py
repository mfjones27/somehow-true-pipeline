#!/usr/bin/env python3
"""Unified video production pipeline — runs the full pipeline in ONE command.

Replaces 27+ agent turns with a single local script execution.
Agent involvement: write config → run this script → review output.

Usage:
  python produce_video.py --config config.json
  python produce_video.py --config config.json --skip-runway   # use existing clips
  python produce_video.py --config config.json --skip-captions # use existing captions
  python produce_video.py --config config.json --upload       # also upload + publish

Config format (see config.example.json):
{
  "content_id": "FCT-011",
  "title": "Dutch Land Inside Belgium Inside the Netherlands",
  "description": "...",
  "tags": ["Baarle", "geography", ...],
  "script": "There's Dutch land inside Belgian land...",
  "sources": ["https://...", "https://..."],
  "clips_dir": "full_pilot",          # existing clips dir (relative to content_factory)
  "captions_dir": "full_pilot/captions", # existing captions dir (relative to content_factory)
  "intro_clip": "runway-test-raw.mp4",    # scene01 fallback (relative to content_factory)
  "narration_path": "video_factory/assets/pilot/narration.wav",
  "scene_prompts": ["prompt1", "prompt2", ...],
  "scene_durations": [5, 8, 8, 8, 8, 10],
  "brand": "SOMEHOW TRUE",
  "output_name": "somehow-true-baarle-full.mp4",
  "youtube_channel_id": "UCZqmUx29Va8Zud78Fj_0Geg",
  "drive_folder_id": "...",
  "notion_page_id": "...",
  "runway_model": "gen4.5",
  "runway_ratio": "720:1280",
  "caption_font": "/usr/share/fonts/truetype/lato/Lato-Bold.ttf",
  "caption_font_size": 72,
  "caption_style": {
    "text_color": "&H00FFFFFF",
    "active_word_color": "&H87E2C5&",
    "outline_color": "&H0018100D",
    "pos_x": 485,
    "pos_y": 1400,
    "max_width_px": 780
  }
}

What this replaces (credit savings):
  OLD: 27+ agent turns, 185 JSON state files, 5+ subagent spawns, dual-model ASR, per-asset Notion pages
  NEW: 1 script run, 1 state file, 0 subagents, single ASR pass, 1 Notion update

Credit estimate: ~500 Runway API credits + ~200-500 agent credits = ~1k total (vs ~15k)
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from fractions import Fraction

import numpy as np
from scipy import signal
from scipy.io import wavfile

from providers.clip_coverage import (
    COVERAGE_SLACK_SECONDS,
    fill_clip_durations,
    hold_prompt,
    plan_scene_coverage,
)
from providers.env import load_env

load_env()

ROOT = Path(__file__).resolve().parent
SR = 48000


def resolve_font():
    for path in (
        os.environ.get("CAPTION_FONT", ""),
        "/usr/share/fonts/truetype/lato/Lato-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        r"C:\Windows\Fonts\arialbd.ttf",
        r"C:\Windows\Fonts\Arial.ttf",
    ):
        if path and Path(path).exists():
            return path
    return "Arial"


FONT = resolve_font()


# ─── Utilities ───────────────────────────────────────────────────────────────

def run(args, log=None, timeout=600, cwd=None):
    result = subprocess.run(
        [str(a) for a in args], stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, text=True, timeout=timeout, cwd=cwd,
    )
    if log:
        log.parent.mkdir(parents=True, exist_ok=True)
        log.write_text(result.stderr)
    if result.returncode:
        raise RuntimeError(f"Command failed ({result.returncode}): {args}\n{result.stderr[-4000:]}")
    return result


def ffmpeg(args, log=None, timeout=600, cwd=None):
    return run(["ffmpeg", "-hide_banner", "-y", "-threads", "2", *args], log, timeout, cwd=cwd)


def ffprobe(path):
    return json.loads(run([
        "ffprobe", "-v", "error", "-show_format", "-show_streams",
        "-of", "json", path
    ]).stdout)


def sha256(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def write_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n")


def ass_time(seconds):
    centis = round(seconds * 100)
    return f"{centis // 360000}:{centis // 6000 % 60:02}:{centis // 100 % 60:02}.{centis % 100:02}"


def srt_time(seconds):
    millis = round(seconds * 1000)
    return f"{millis // 3600000:02}:{millis // 60000 % 60:02}:{millis // 1000 % 60:02},{millis % 1000:03}"


# ─── Step 1: Runway Generation (batch) ───────────────────────────────────────

RUNWAY_BASE = "https://api.dev.runwayml.com/v1"


def runway_headers():
    key = os.environ.get("RUNWAY_API_KEY", "").strip()
    if not key:
        raise RuntimeError("RUNWAY_API_KEY is missing")
    return {
        "Authorization": f"Bearer {key}",
        "X-Runway-Version": "2024-11-06",
        "Content-Type": "application/json",
    }


def scene_clip_paths(clips_dir):
    return sorted(Path(clips_dir).glob("scene[0-9][0-9].mp4"))


def clip_seconds(path):
    data = ffprobe(path)
    video = next(stream for stream in data["streams"] if stream["codec_type"] == "video")
    frames = video.get("nb_frames")
    if frames not in (None, "N/A"):
        rate = video.get("avg_frame_rate") or video.get("r_frame_rate") or "24/1"
        num, den = (rate.split("/", 1) + ["1"])[:2]
        fps = float(num) / max(float(den), 1e-9)
        return int(frames) / fps
    return float(video.get("duration") or data["format"]["duration"])


def clips_total_seconds(clips_dir):
    return sum(clip_seconds(path) for path in scene_clip_paths(clips_dir))


def persist_config(config_path, config):
    write_json(config_path, config)


def apply_narration_coverage(config, needed_seconds, config_path=None):
    """Stretch scene lengths and append hold clips until they cover narration."""
    prompts, durations = plan_scene_coverage(
        config.get("scene_prompts") or [],
        config.get("scene_durations") or [],
        needed_seconds,
    )
    changed = (
        prompts != list(config.get("scene_prompts") or [])
        or durations != list(config.get("scene_durations") or [])
    )
    config["scene_prompts"] = prompts
    config["scene_durations"] = durations
    if changed and config_path is not None:
        persist_config(config_path, config)
    return changed


def append_fill_clips(config, gap, config_path=None):
    extras = fill_clip_durations(gap)
    if not extras:
        return []
    last = (config.get("scene_prompts") or [""])[-1]
    for duration in extras:
        config.setdefault("scene_prompts", []).append(hold_prompt(last))
        config.setdefault("scene_durations", []).append(duration)
    if config_path is not None:
        persist_config(config_path, config)
    return extras


def generate_runway_clips(config, work_dir, clips_dir=None):
    """Create all Runway clips in one batch, poll in one loop, download all at once."""
    import requests
    clips_dir = Path(clips_dir) if clips_dir else work_dir / "clips"
    clips_dir.mkdir(exist_ok=True)
    prompts = config["scene_prompts"]
    durations = config["scene_durations"]
    model = config.get("runway_model", "gen4.5")
    ratio = config.get("runway_ratio", "720:1280")
    headers = runway_headers()

    results = []

    # Phase 1: Create all tasks
    for i, (prompt, dur) in enumerate(zip(prompts, durations), 1):
        clip_path = clips_dir / f"scene{i:02d}.mp4"
        if clip_path.exists():
            results.append({"scene": i, "status": "already_exists", "path": str(clip_path)})
            continue

        request = {"model": model, "duration": dur, "ratio": ratio, "promptText": prompt}
        marker = clips_dir / f"scene{i:02d}_creation.json"
        if marker.exists():
            creation = json.loads(marker.read_text())
            task_id = creation.get("task_id")
            if task_id:
                results.append({"scene": i, "status": "polling", "task_id": task_id})
                continue

        resp = None
        for attempt in range(4):
            resp = requests.post(f"{RUNWAY_BASE}/text_to_video", headers=headers, json=request, timeout=90)
            if resp.ok:
                break
            print(f"  Scene {i}: Runway {resp.status_code}: {resp.text[:400]}")
            if resp.status_code not in (400, 429, 500, 502, 503):
                resp.raise_for_status()
            time.sleep(8 * (attempt + 1))
        resp.raise_for_status()
        data = resp.json()
        task_id = data["id"]
        estimated = data.get("estimatedCost")
        write_json(marker, {"task_id": task_id, "request": request, "estimated_cost": estimated})
        from providers.costs import runway_clip
        cost = runway_clip(config.get("content_id", "unknown"), model, int(dur), estimated)
        results.append({"scene": i, "status": "created", "task_id": task_id, "credits": cost["credits"]})
        print(f"  Scene {i}: created task {task_id} (~{cost['credits']} credits / ${cost['usd']:.2f})")

    # Phase 2: Poll all pending tasks in a single loop
    pending = [r for r in results if r["status"] in ("created", "polling")]
    if pending:
        max_rounds = 60
        for round_num in range(1, max_rounds + 1):
            still_pending = []
            for item in pending:
                scene = item["scene"]
                task_id = item["task_id"]
                clip_path = clips_dir / f"scene{scene:02d}.mp4"
                if clip_path.exists():
                    item["status"] = "downloaded"
                    item["path"] = str(clip_path)
                    continue

                status_file = clips_dir / f"scene{scene:02d}_status.json"
                status_data = None
                for attempt in range(5):
                    try:
                        resp = requests.get(f"{RUNWAY_BASE}/tasks/{task_id}", headers=headers, timeout=60)
                        resp.raise_for_status()
                        status_data = resp.json()
                        break
                    except (requests.exceptions.ConnectionError, requests.exceptions.Timeout):
                        time.sleep(5 * (attempt + 1))
                if status_data is None:
                    still_pending.append(item)
                    continue
                write_json(status_file, status_data)

                if status_data["status"] == "SUCCEEDED":
                    output_url = status_data["output"][0]
                    clip_bytes = None
                    for attempt in range(5):
                        try:
                            resp2 = requests.get(output_url, timeout=120)
                            resp2.raise_for_status()
                            clip_bytes = resp2.content
                            break
                        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout):
                            time.sleep(5 * (attempt + 1))
                    if clip_bytes is None:
                        still_pending.append(item)
                        continue
                    clip_path.write_bytes(clip_bytes)
                    receipt = {
                        "task_id": task_id, "file": clip_path.name,
                        "bytes": clip_path.stat().st_size,
                        "sha256": hashlib.sha256(resp2.content).hexdigest(),
                    }
                    write_json(clips_dir / f"scene{scene:02d}_receipt.json", receipt)
                    item["status"] = "downloaded"
                    item["path"] = str(clip_path)
                    print(f"  Scene {scene}: downloaded ({clip_path.stat().st_size:,} bytes)")
                elif status_data["status"] in ("FAILED", "CANCELED", "CANCELLED"):
                    item["status"] = "failed"
                    print(f"  Scene {scene}: FAILED")
                else:
                    still_pending.append(item)

            pending = still_pending
            if not pending:
                break
            if round_num < max_rounds:
                time.sleep(30)
                print(f"  Polling round {round_num}: {len(pending)} clips pending...")

    return results, clips_dir


# ─── Step 2: Caption Generation (single Whisper pass) ────────────────────────

def generate_captions(config, narration_path, output_dir):
    """Single Whisper pass → ASS + SRT. No dual-model cross-validation, no QA frames.

    Uses faster-whisper small.en (462MB) for word-level timestamps.
    Groups words into 2-4 word phrases based on punctuation and natural pauses.
    """
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        print("  WARNING: faster-whisper not installed. Using ffmpeg subtitle filter as fallback.")
        return _ffmpeg_subtitle_fallback(narration_path, output_dir, config)

    model_cache = output_dir / "model_cache"
    model_cache.mkdir(parents=True, exist_ok=True)
    os.environ["HF_HOME"] = str(model_cache)

    print("  Loading Whisper small.en model...")
    model = WhisperModel("small.en", device="cpu", compute_type="int8",
                         download_root=str(model_cache))

    print("  Transcribing narration...")
    segments, _info = model.transcribe(str(narration_path), word_timestamps=True,
                                       beam_size=1, best_of=1)

    words = []
    for seg in segments:
        for w in (seg.words or []):
            word_text = w.word.strip()
            if not word_text:
                continue
            if word_text.startswith("-") and words:
                words[-1]["text"] += word_text
                words[-1]["end"] = w.end
            else:
                words.append({"text": word_text, "start": w.start, "end": w.end})

    if not words:
        raise RuntimeError("Whisper produced no words")

    # Group into 2-4 word phrases based on punctuation and natural breaks
    script_text = config.get("script", "")
    phrase_texts = _group_phrases(script_text, words)

    # Generate ASS with word-highlight captions
    style = config.get("caption_style", {})
    pos_x = style.get("pos_x", 485)
    pos_y = style.get("pos_y", 1400)
    max_width = style.get("max_width_px", 780)
    font_size = config.get("caption_font_size", 66)
    text_color = style.get("text_color", "&H00FFFFFF")
    active_color = style.get("active_word_color", "&H87E2C5&")
    outline_color = style.get("outline_color", "&H0018100D")

    # Map phrase words to ASR words
    phrases = []
    cursor = 0
    audio_duration = float(ffprobe(narration_path)["format"]["duration"])
    for i, text in enumerate(phrase_texts):
        count = len(text.split())
        selected = words[cursor:cursor + count]
        if not selected:
            break
        next_word = words[cursor + count] if cursor + count < len(words) else None
        end = min(audio_duration, selected[-1]["end"] + 0.14)
        if next_word:
            end = min(end, next_word["start"])
        phrases.append({
            "id": i + 1, "text": text,
            "start": selected[0]["start"],
            "end": min(round(end, 3), audio_duration),
            "word_ids": list(range(cursor + 1, cursor + count + 1)),
        })
        cursor += count

    # Write ASS — modern borderless style: no outline, subtle drop shadow, larger text
    header = f"""[Script Info]
Title: {config.get('title', 'Somehow True')} — captions
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
WrapStyle: 2
ScaledBorderAndShadow: yes
YCbCr Matrix: TV.709

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Caption,{Path(FONT).stem if Path(FONT).exists() else "Arial"},{font_size},{text_color},{text_color},&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,0,3.5,5,95,205,0,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    events = []
    for p in phrases:
        selected = [words[i - 1] for i in p["word_ids"] if i - 1 < len(words)]
        if not selected:
            continue
        boundaries = sorted(set([p["start"], p["end"]] +
                                [min(p["end"], max(p["start"], t))
                                 for w in selected for t in [w["start"], w["end"]]]))
        for start, end in zip(boundaries, boundaries[1:]):
            if ass_time(start) == ass_time(end):
                continue
            mid = (start + end) / 2
            parts = []
            for w in selected:
                color = active_color if w["start"] <= mid < w["end"] else text_color
                parts.append(r"{\1c" + color + "}" + w["text"])
            text = rf"{{\an5\pos({pos_x},{pos_y})\q2}}" + " ".join(parts)
            events.append(f"Dialogue: 0,{ass_time(start)},{ass_time(end)},Caption,,0,0,0,,{text}")

    ass_path = output_dir / "captions.ass"
    ass_path.write_text(header + "\n".join(events) + "\n", encoding="utf-8")

    # Write SRT
    srt_path = output_dir / "captions.srt"
    srt_path.write_text(
        "\n\n".join(f"{p['id']}\n{srt_time(p['start'])} --> {srt_time(p['end'])}\n{p['text']}"
                    for p in phrases) + "\n", encoding="utf-8")

    stats = {
        "word_count": len(words), "phrase_count": len(phrases),
        "ass_event_count": len(events), "audio_duration": audio_duration,
        "model": "faster-whisper small.en CPU int8 (single pass, no cross-validation)",
    }
    write_json(output_dir / "caption_stats.json", stats)
    print(f"  Captions: {len(words)} words, {len(phrases)} phrases, {len(events)} ASS events")
    return {"ass": str(ass_path), "srt": str(srt_path), "stats": stats}


def _group_phrases(script_text, words):
    """Group words into 2-4 word phrases. Tries to match script punctuation."""
    if script_text:
        # Split script by natural phrase boundaries
        raw_phrases = re.split(r'(?<=[.,;:!?])\s+', script_text.strip())
        phrases = []
        for rp in raw_phrases:
            word_count = len(rp.split())
            if word_count <= 4:
                phrases.append(rp)
            else:
                # Split long phrases into 3-word chunks
                parts = rp.split()
                for j in range(0, len(parts), 3):
                    chunk = parts[j:j+3]
                    if len(chunk) >= 2:
                        phrases.append(" ".join(chunk))
                    elif chunk:
                        if phrases:
                            phrases[-1] += " " + " ".join(chunk)
                        else:
                            phrases.append(" ".join(chunk))
        return phrases
    else:
        # Fallback: group ASR words into 3-word phrases
        phrases = []
        for i in range(0, len(words), 3):
            chunk = words[i:i+3]
            if len(chunk) >= 2:
                phrases.append(" ".join(w["text"] for w in chunk))
            elif chunk and phrases:
                phrases[-1] += " " + " ".join(w["text"] for w in chunk)
        return phrases


def _ffmpeg_subtitle_fallback(narration_path, output_dir, config):
    """Fallback: use ffmpeg's subtitle filter if Whisper isn't available."""
    srt_path = output_dir / "captions.srt"
    ass_path = output_dir / "captions.ass"
    # Try ffmpeg's built-in speech recognition
    ffmpeg([
        "-i", str(narration_path),
        "-vf", "subtitles=filter_speech",
        "-f", "srt", str(srt_path)
    ], timeout=120)
    # Convert to basic ASS
    ass_path.write_text(f"""[Script Info]
PlayResX: 1080
PlayResY: 1920

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Caption,Lato,66,&H00FFFFFF,&H00FFFFFF,&H0018100D,&H9018100D,-1,0,0,0,100,100,0,0,1,4,1.2,5,95,205,0,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
""")
    return {"ass": str(ass_path), "srt": str(srt_path), "stats": {"model": "ffmpeg subtitle filter fallback"}}


# ─── Step 3: Audio Preparation ───────────────────────────────────────────────

def midi(note):
    return 440 * 2 ** ((note - 69) / 12)


def add_note(bed, start, duration, note, level, pan, rng, pluck=False):
    a = round(start * SR)
    b = min(len(bed), a + round(duration * SR))
    if b <= a:
        return
    t = np.arange(b - a, dtype=np.float64) / SR
    f = midi(note)
    tone = np.zeros(len(t))
    for cents, weight in [(-5.5, .22), (0, .56), (4.5, .22)]:
        frequency = f * 2 ** (cents / 1200)
        for harmonic in range(1, 7 if pluck else 6):
            phase = rng.uniform(0, 2 * np.pi)
            amplitude = weight / harmonic ** (1.9 if pluck else 2.35)
            decay = np.exp(-t * harmonic * .40) if pluck else 1
            tone += amplitude * decay * np.sin(
                2 * np.pi * frequency * harmonic * t + .002 * np.sin(2 * np.pi * .37 * t) + phase
            )
    if pluck:
        env = (1 - np.exp(-t / .026)) * np.exp(-t / 1.12)
        env *= np.minimum(1, (duration - t) / .5).clip(0, 1)
    else:
        env = np.sin(np.pi / 2 * np.minimum(t / 1.65, 1)) ** 2
        env *= np.sin(np.pi / 2 * np.minimum((duration - t) / 2.2, 1)) ** 2
        env *= .94 + .06 * np.sin(2 * np.pi * .11 * t + rng.uniform(0, 6.28))
    tone *= env * level
    bed[a:b, 0] += tone * math.sqrt((1 - pan) / 2)
    bed[a:b, 1] += tone * math.sqrt((1 + pan) / 2)


def make_music(duration):
    """Original deterministic warm-minor pad/pluck score, no percussion."""
    rng = np.random.default_rng(20260912)
    bed = np.zeros((math.ceil(duration * SR), 2), dtype=np.float64)
    harmony = [
        (0.0, [38, 57, 60, 64], 11.3),
        (9.4, [34, 53, 57, 62], 11.6),
        (19.0, [41, 55, 60, 64], 11.5),
        (28.7, [36, 55, 60, 62], 10.7),
        (37.5, [38, 57, 60, 64], 10.8),
    ]
    for start, notes, length in harmony:
        for i, note in enumerate(notes):
            add_note(bed, start, length, note, .18 if i == 0 else .13,
                     [-.1, -.5, .45, .15][i], rng)
    for start, note, pan in [
        (2.4, 69, -.25), (5.8, 64, .25), (10.9, 65, -.2),
        (15.5, 62, .3), (21.2, 67, -.3), (25.9, 64, .25),
        (31.7, 67, -.2), (35.7, 62, .3), (40.2, 64, -.25), (43.0, 62, .15),
    ]:
        add_note(bed, start, 3.6, note, .095, pan, rng, pluck=True)
    dry = bed.copy()
    for delay, gain in [(.113, .14), (.227, .09), (.373, .05)]:
        lag = round(SR * delay)
        bed[lag:] += dry[:-lag, ::-1] * gain
    bed = signal.sosfilt(signal.butter(2, 95, "highpass", fs=SR, output="sos"), bed, axis=0)
    bed = signal.sosfilt(signal.butter(2, 2600, "lowpass", fs=SR, output="sos"), bed, axis=0)
    times = np.arange(len(bed)) / SR
    fade = np.minimum(times / 1.2, 1)
    fade *= np.sin(np.pi / 2 * np.clip((duration - times) / 2.5, 0, 1)) ** 2
    bed *= fade[:, None]
    bed /= max(float(np.sqrt(np.mean(bed ** 2))), 1e-8)
    return bed


def db(value):
    return 20 * math.log10(max(float(value), 1e-12))


def loudness(path, log_path=None):
    r = ffmpeg(["-i", path, "-vn", "-af",
                "loudnorm=I=-16:TP=-1.5:LRA=11:print_format=json",
                "-f", "null", "-"], log_path)
    blocks = re.findall(r'\{\s*"input_i".*?\}', r.stderr, re.S)
    if not blocks:
        raise RuntimeError("Could not parse loudness meter output")
    return json.loads(blocks[-1])


def prepare_audio(narration_path, duration, work_dir, qa_dir):
    """Prepare mixed audio: narration + procedural music, normalized to -16 LUFS."""
    work_dir.mkdir(exist_ok=True)
    qa_dir.mkdir(exist_ok=True)

    rate, voice = wavfile.read(narration_path)
    if rate != SR:
        raise RuntimeError(f"Narration expected at {SR}Hz; got {rate}Hz")
    if np.issubdtype(voice.dtype, np.integer):
        voice = voice.astype(np.float64) / (np.iinfo(voice.dtype).max + 1)
    else:
        voice = voice.astype(np.float64)
    if voice.ndim != 1:
        voice = voice.mean(axis=1)

    count = math.ceil(duration * SR)
    voice = np.pad(voice, (0, max(0, count - len(voice))))

    bed = make_music(duration)

    # Ducking: detect narration activity and reduce music during speech
    block = 480
    padded = np.pad(voice, (0, (-len(voice)) % block))
    rms = np.sqrt(np.mean(padded.reshape(-1, block) ** 2, axis=1))
    smooth = np.zeros_like(rms)
    for i in range(len(rms)):
        previous = smooth[i - 1] if i else 0
        coefficient = math.exp(-.010 / (.035 if rms[i] > previous else .45))
        smooth[i] = coefficient * previous + (1 - coefficient) * rms[i]
    activity = np.clip((20 * np.log10(np.maximum(smooth, 1e-8)) + 48) / 24, 0, 1)
    gain = 10 ** (np.interp(np.arange(count) / block, np.arange(len(activity)), -7 * activity) / 20)
    active = np.abs(voice) > .02
    voice_active_rms = float(np.sqrt(np.mean(voice[active] ** 2))) if active.any() else .1
    bed_base = min(10 ** (-32 / 20), voice_active_rms * 10 ** (-22 / 20))
    ducked = (bed * bed_base) * gain[:, None]
    mix = np.repeat(voice[:, None], 2, axis=1) + ducked

    wavfile.write(work_dir / "mix-before-normalization.wav", SR, mix.astype(np.float32))

    # Two-pass loudness normalization
    measured = loudness(work_dir / "mix-before-normalization.wav", qa_dir / "premix-loudness.log")
    af = (
        "loudnorm=I=-16:TP=-1.5:LRA=11:"
        f"measured_I={measured['input_i']}:measured_TP={measured['input_tp']}:"
        f"measured_LRA={measured['input_lra']}:measured_thresh={measured['input_thresh']}:"
        f"offset={measured['target_offset']}:linear=true:print_format=json"
    )
    ffmpeg(["-i", work_dir / "mix-before-normalization.wav", "-af", af,
            "-ar", str(SR), "-ac", "2", "-c:a", "pcm_s24le",
            work_dir / "final-mix.wav"], qa_dir / "normalization.log")

    post = loudness(work_dir / "final-mix.wav", qa_dir / "mix-loudness.log")
    if not -16.8 <= float(post["input_i"]) <= -15.2:
        raise RuntimeError(f"Loudness {post['input_i']} outside -16±0.8 LUFS")
    if float(post["input_tp"]) > -1.1:
        raise RuntimeError(f"True peak {post['input_tp']} exceeds -1.1 dBTP")

    return work_dir / "final-mix.wav", post


# ─── Step 4: Video Assembly ──────────────────────────────────────────────────

def filter_path(path):
    posix = Path(path).resolve().as_posix()
    if len(posix) >= 2 and posix[1] == ":":
        posix = posix[0] + "\\:" + posix[2:]
    return posix.replace("'", "\\'")


def assemble_video(clips_dir, narration_path, captions_ass, audio_path, output_path,
                   brand_text, qa_dir, scene_durations, intro_clip_path=None):
    """Concatenate clips, upscale to 1080x1920, burn captions, mix audio."""
    qa_dir.mkdir(exist_ok=True)

    clip_files = scene_clip_paths(clips_dir)
    if intro_clip_path and Path(intro_clip_path).exists():
        intro = Path(intro_clip_path)
        clip_files = [intro] + [c for c in clip_files if c.resolve() != intro.resolve()]
    if not clip_files:
        raise RuntimeError("No scene clips found")

    # Verify clips
    total_frames = 0
    for cf in clip_files:
        data = ffprobe(cf)
        v = next(s for s in data["streams"] if s["codec_type"] == "video")
        if (v["width"], v["height"]) != (720, 1280):
            print(f"  WARNING: {cf.name} is {v['width']}x{v['height']}, expected 720x1280")
        total_frames += int(v.get("nb_frames", round(float(v["duration"]) * 24)))

    duration = total_frames / 24
    print(f"  Assembling {len(clip_files)} clips, {total_frames} frames, {duration:.2f}s")
    audio_seconds = float(ffprobe(audio_path)["format"]["duration"])
    if duration + COVERAGE_SLACK_SECONDS < audio_seconds:
        raise RuntimeError(
            f"Clips are {duration:.2f}s but audio is {audio_seconds:.2f}s; "
            "visuals end before narration"
        )

    # Build ffmpeg filter chain
    inputs = []
    for cf in clip_files:
        inputs += ["-i", str(cf)]
    inputs += ["-i", str(audio_path)]

    n_clips = len(clip_files)
    chain = (
        "".join(f"[{i}:v:0]" for i in range(n_clips))
        + f"concat=n={n_clips}:v=1:a=0,"
        + "scale=1080:1920:flags=lanczos,setsar=1,format=yuv420p"
    )

    if brand_text and os.name != "nt" and Path(FONT).exists():
        chain += (
            f",drawtext=fontfile='{FONT}':text='{brand_text}':"
            "fontsize=24:fontcolor=white@0.70:x=58:y=130:"
            "shadowcolor=black@0.35:shadowx=0:shadowy=2"
        )

    burn = qa_dir / "burn.ass"
    burn.write_bytes(Path(captions_ass).read_bytes())
    chain += ",ass=burn.ass[v]"

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    ffmpeg([
        *inputs, "-filter_complex", chain, "-map", "[v]", f"-map", f"{n_clips}:a:0",
        "-c:v", "libx264", "-threads:v", "2", "-preset", "fast",
        "-crf", "18", "-pix_fmt", "yuv420p", "-fps_mode", "passthrough",
        "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
        "-movflags", "+faststart",
        str(output_path)
    ], qa_dir / "render.log", timeout=1200, cwd=str(qa_dir))

    # Quick QA: verify output
    data = ffprobe(output_path)
    v = next(s for s in data["streams"] if s["codec_type"] == "video")
    meter = loudness(output_path, qa_dir / "final-loudness.log")

    qa = {
        "dimensions": [v["width"], v["height"]],
        "fps": str(v.get("avg_frame_rate", "?")),
        "frame_count": int(v.get("nb_frames", 0)),
        "duration_seconds": float(data["format"]["duration"]),
        "loudness_lufs": float(meter["input_i"]),
        "true_peak_dbtp": float(meter["input_tp"]),
        "file_size_bytes": output_path.stat().st_size,
        "sha256": sha256(output_path),
        "all_checks_pass": (
            [v["width"], v["height"]] == [1080, 1920]
            and -16.8 <= float(meter["input_i"]) <= -15.2
            and float(meter["input_tp"]) <= -1.0
        ),
    }
    write_json(qa_dir / "final-qa.json", qa)
    print(f"  Output: {output_path.name} ({output_path.stat().st_size:,} bytes, {qa['duration_seconds']:.2f}s)")
    return output_path, qa


# ─── Step 5: Upload (Drive + YouTube + Notion) ────────────────────────────────

def upload_to_youtube(video_path, config):
    """Upload the finished video to YouTube as private with AI disclosure."""
    from providers.youtube_upload import upload_private

    result = upload_private(
        Path(video_path),
        title=config.get("title", ""),
        description=config.get("description", ""),
        tags=config.get("tags", []),
    )
    write_json(ROOT / "youtube_upload_input.json", result)
    print(f"  YouTube private upload: {result['url']}")
    return result


# ─── Main Pipeline ────────────────────────────────────────────────────────────

def run_pipeline(config_path, skip_runway=False, skip_captions=False, upload=False):
    config = json.loads(Path(config_path).read_text())
    content_id = config["content_id"]
    work_dir = ROOT / "pipeline_output" / content_id
    work_dir.mkdir(parents=True, exist_ok=True)

    state = {"content_id": content_id, "started_at": time.time(), "steps": []}
    print(f"\n{'='*60}")
    print(f"PIPELINE: {content_id}")
    print(f"Title: {config.get('title', 'N/A')}")
    print(f"{'='*60}\n")

    narration_path = Path(config["narration_path"])
    if not narration_path.is_absolute():
        narration_path = ROOT / config["narration_path"]
    narration_seconds = float(ffprobe(narration_path)["format"]["duration"])
    print(f"Narration: {narration_seconds:.2f}s")

    before_count = len(config.get("scene_durations") or [])
    before_sum = sum(int(d) for d in (config.get("scene_durations") or []))
    if apply_narration_coverage(config, narration_seconds, config_path):
        extra = len(config["scene_durations"]) - before_count
        note = f" including {extra} fill clip(s)" if extra else ""
        print(
            f"  Planned visuals {before_sum}s → {sum(config['scene_durations'])}s"
            f"{note} to cover narration"
        )

    # Step 1: Runway generation
    raw_clips = config.get("clips_dir")
    clips_dir = ROOT / raw_clips if skip_runway and raw_clips else work_dir / "clips"
    if not skip_runway:
        print("STEP 1: Generating Runway clips (batch)...")
        clip_results, clips_dir = generate_runway_clips(config, work_dir, clips_dir)
        state["steps"].append({"step": "runway", "results": clip_results})
        print()
    else:
        print(f"STEP 1: Using existing clips from {clips_dir}\n")

    if not scene_clip_paths(clips_dir):
        raise RuntimeError(f"No scene clips found in {clips_dir}")
    visual_seconds = clips_total_seconds(clips_dir)
    if visual_seconds + COVERAGE_SLACK_SECONDS < narration_seconds:
        gap = narration_seconds - visual_seconds
        extras = append_fill_clips(config, gap, config_path)
        print(
            f"  Clips are {visual_seconds:.2f}s, narration {narration_seconds:.2f}s. "
            f"Generating {len(extras)} fill clip(s) {extras}..."
        )
        fill_results, clips_dir = generate_runway_clips(config, work_dir, clips_dir)
        state["steps"].append({"step": "runway_fill", "results": fill_results, "durations": extras})
        visual_seconds = clips_total_seconds(clips_dir)
        if visual_seconds + COVERAGE_SLACK_SECONDS < narration_seconds:
            raise RuntimeError(
                f"Clips total {visual_seconds:.2f}s after fill, narration is {narration_seconds:.2f}s"
            )
    print(f"  Visuals {visual_seconds:.2f}s cover narration {narration_seconds:.2f}s\n")

    # Step 2: Caption generation
    if not skip_captions:
        print("STEP 2: Generating captions (single Whisper pass)...")
        caption_dir = work_dir / "captions"
        caption_dir.mkdir(parents=True, exist_ok=True)
        caption_results = generate_captions(config, narration_path, caption_dir)
        state["steps"].append({"step": "captions", "results": caption_results})
        print()
    else:
        raw_captions = config.get("captions_dir")
        caption_dir = ROOT / raw_captions if raw_captions else work_dir / "captions"
        print(f"STEP 2: Using existing captions from {caption_dir}\n")

    # Step 3: Audio preparation
    print("STEP 3: Preparing audio (narration + procedural music)...")
    audio_path, audio_qa = prepare_audio(
        narration_path,
        duration=max(narration_seconds, visual_seconds),
        work_dir=work_dir / "audio",
        qa_dir=work_dir / "qa",
    )
    state["steps"].append({"step": "audio", "loudness": audio_qa})
    print()

    # Step 4: Video assembly
    print("STEP 4: Assembling final video...")
    output_path = work_dir / config.get("output_name", f"{content_id}.mp4")
    captions_ass = caption_dir / "captions.ass"
    brand = config.get("brand", "SOMEHOW TRUE")
    scene_durations = config.get("scene_durations", [])
    intro_raw = config.get("intro_clip")
    intro_clip = (ROOT / intro_raw) if intro_raw else None

    video_path, video_qa = assemble_video(
        clips_dir, narration_path, captions_ass, audio_path,
        output_path, brand, work_dir / "qa", scene_durations,
        intro_clip_path=intro_clip,
    )
    state["steps"].append({"step": "assembly", "results": video_qa})
    print()

    # Step 5: Upload (optional)
    if upload:
        print("STEP 5: Uploading to YouTube as private...")
        youtube_result = upload_to_youtube(video_path, config)
        state["steps"].append({"step": "upload", "youtube": youtube_result})
        print()

    # Final state
    state["completed_at"] = time.time()
    state["duration_seconds"] = state["completed_at"] - state["started_at"]
    state["output_path"] = str(video_path)
    state["output_qa"] = video_qa
    state["all_steps_complete"] = True

    write_json(work_dir / "pipeline_state.json", state)
    print(f"{'='*60}")
    print(f"PIPELINE COMPLETE in {state['duration_seconds']:.1f}s")
    print(f"Output: {video_path}")
    print(f"Size: {video_qa['file_size_bytes']:,} bytes")
    print(f"Duration: {video_qa['duration_seconds']:.2f}s")
    print(f"QA: {'PASS' if video_qa['all_checks_pass'] else 'CHECK NEEDED'}")
    print(f"State: {work_dir / 'pipeline_state.json'}")
    print(f"{'='*60}")
    from providers.costs import print_summary
    state["spend"] = print_summary(content_id)
    write_json(work_dir / "pipeline_state.json", state)

    return state


def main():
    parser = argparse.ArgumentParser(description="Unified video production pipeline")
    parser.add_argument("--config", required=True, help="Path to config JSON")
    parser.add_argument("--skip-runway", action="store_true", help="Use existing clips")
    parser.add_argument("--skip-captions", action="store_true", help="Use existing captions")
    parser.add_argument("--upload", action="store_true", help="Upload the finished video to YouTube as private")
    args = parser.parse_args()
    run_pipeline(args.config, args.skip_runway, args.skip_captions, args.upload)


if __name__ == "__main__":
    main()
