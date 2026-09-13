#!/usr/bin/env python3
"""Approved-footage assembly. No paid generation, speed changes, uploads or publishing.

Examples:
  python assemble.py --prepare
  python assemble.py --render --footage-approved
  python assemble.py --qa

The render gate is intentional: a human/parent must inspect the six source clips.
720x1280 sources are upscaled, not described as native 1080p.
"""
from __future__ import annotations

import argparse
from fractions import Fraction
import hashlib
import json
import math
from pathlib import Path
import re
import subprocess

import numpy as np
from scipy import signal
from scipy.io import wavfile
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent
FACTORY = ROOT.parent
NARRATION = (
    ROOT / "narration.wav" if (ROOT / "narration.wav").exists()
    else FACTORY / "video_factory/assets/pilot/narration.wav"
)
INTRO = (
    ROOT / "scene01.mp4" if (ROOT / "scene01.mp4").exists()
    else FACTORY / "runway-test-raw.mp4"
)
CLIPS = [INTRO] + [
    ROOT / f"scene{i:02d}.mp4" for i in range(2, 7)
]
CAPTIONS = ROOT / "captions/captions.ass"
OUT = ROOT / "somehow-true-baarle-full.mp4"
WORK = ROOT / "assembly_work"
QA = ROOT / "qa"
SR = 48000
NOMINAL_DURATION = 1129 / 24
FONT = "/usr/share/fonts/truetype/lato/Lato-Bold.ttf"


def write(path, content):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def write_json(path, data):
    write(path, json.dumps(data, indent=2) + "\n")


def run(args, log=None):
    result = subprocess.run(
        [str(a) for a in args], stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, text=True,
    )
    if log:
        write(log, result.stderr)
    if result.returncode:
        raise RuntimeError(
            f"Command failed ({result.returncode}): {args}\n{result.stderr[-6000:]}"
        )
    return result


def ffmpeg(args, log=None):
    return run([
        "ffmpeg", "-hide_banner", "-y", "-threads", "2",
        "-filter_threads", "2", "-filter_complex_threads", "2", *args
    ], log)


def probe(path):
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


def preflight():
    missing = [str(p) for p in [*CLIPS, NARRATION, CAPTIONS] if not p.exists()]
    if missing:
        raise RuntimeError("Assembly assets not ready:\n" + "\n".join(missing))
    entries, cursor = [], 0.0
    for i, path in enumerate(CLIPS):
        data = probe(path)
        v = next(s for s in data["streams"] if s["codec_type"] == "video")
        if (v["width"], v["height"]) != (720, 1280):
            raise RuntimeError(f"Unexpected dimensions in {path}: inspect before assembly")
        if Fraction(v["avg_frame_rate"]) != 24:
            raise RuntimeError(f"Unexpected frame rate in {path}; no retiming allowed")
        if abs(float(v.get("start_time", 0))) > 1 / 48000:
            raise RuntimeError(f"Nonzero source timestamp in {path}; inspect, do not retime")
        duration = float(v["duration"])
        expected = [121 / 24, 8, 8, 8, 8, 10][i]
        if abs(duration - expected) > 1 / 24 + .002:
            raise RuntimeError(f"{path.name}: unexpected duration {duration}")
        frames = int(v.get("nb_frames", round(duration * 24)))
        if abs(frames / 24 - duration) > .002:
            raise RuntimeError(f"{path.name}: duration/frame-count mismatch")
        entries.append({
            "path": str(path), "sha256": sha256(path),
            "duration_seconds": duration, "frames": frames,
            "start_seconds": cursor, "end_seconds": cursor + frames / 24,
            "source_dimensions": [720, 1280], "fps": 24,
        })
        cursor += frames / 24
    ass = CAPTIONS.read_text()
    if not re.search(r"PlayResX:\s*1080", ass) or not re.search(r"PlayResY:\s*1920", ass):
        raise RuntimeError("Captions must be authored at 1080x1920")
    narration_duration = float(probe(NARRATION)["format"]["duration"])
    if narration_duration > cursor:
        raise RuntimeError("Narration longer than footage: do not truncate speech")
    manifest = {
        "clips": entries, "duration_seconds": cursor,
        "expected_frame_count": sum(e["frames"] for e in entries),
        "narration_duration_seconds": narration_duration,
        "narration_sha256": sha256(NARRATION),
        "captions_sha256": sha256(CAPTIONS),
        "output_dimensions": [1080, 1920],
        "upscale": "Lanczos 720x1280 to 1080x1920; not native 1080p",
        "editing": "Full source clips, original speed, hard cuts; original full speech",
        "generated_clip_audio": "Discarded; original narration and procedural music only",
    }
    write_json(ROOT / "assembly_manifest.json", manifest)
    return manifest


def midi(note):
    return 440 * 2 ** ((note - 69) / 12)


def add_note(bed, start, duration, note, level, pan, rng, pluck=False):
    """Soft detuned harmonic instrument; no external samples or model calls."""
    a = round(start * SR)
    b = min(len(bed), a + round(duration * SR))
    if b <= a:
        return
    t = np.arange(b - a, dtype=np.float64) / SR
    f = midi(note)
    tone = np.zeros(len(t))
    # A small ensemble rather than a bare sine/test tone.
    for cents, weight in [(-5.5, .22), (0, .56), (4.5, .22)]:
        frequency = f * 2 ** (cents / 1200)
        for harmonic in range(1, 7 if pluck else 6):
            phase = rng.uniform(0, 2 * np.pi)
            amplitude = weight / harmonic ** (1.9 if pluck else 2.35)
            decay = np.exp(-t * harmonic * .40) if pluck else 1
            tone += amplitude * decay * np.sin(
                2 * np.pi * frequency * harmonic * t
                + .002 * np.sin(2 * np.pi * .37 * t) + phase
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
    # Open voicings: Dm(add9), Bbmaj7, F(add9), Csus2, Dm(add9).
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
        (31.7, 67, -.2), (35.7, 62, .3), (40.2, 64, -.25),
        (43.0, 62, .15),
    ]:
        add_note(bed, start, 3.6, note, .095, pan, rng, pluck=True)
    # Gentle short cross-channel room reflections, no reverb sample.
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


def loudness(path, log_name):
    r = ffmpeg([
        "-i", path, "-vn", "-af",
        "loudnorm=I=-16:TP=-1.5:LRA=11:print_format=json",
        "-f", "null", "-"
    ], QA / log_name)
    blocks = re.findall(r'\{\s*"input_i".*?\}', r.stderr, re.S)
    if not blocks:
        raise RuntimeError("Could not parse loudness meter output")
    return json.loads(blocks[-1])


def prepare_audio(duration=NOMINAL_DURATION):
    WORK.mkdir(exist_ok=True)
    QA.mkdir(exist_ok=True)
    rate, voice = wavfile.read(NARRATION)
    if rate != SR:
        raise RuntimeError("Narration expected at 48kHz; no implicit sample conversion")
    if np.issubdtype(voice.dtype, np.integer):
        voice = voice.astype(np.float64) / (np.iinfo(voice.dtype).max + 1)
    else:
        voice = voice.astype(np.float64)
    if voice.ndim != 1:
        raise RuntimeError("Expected original mono narration")
    count = math.ceil(duration * SR)
    if len(voice) > count:
        raise RuntimeError("Audio duration cannot truncate narration")
    original_sample_count = len(voice)
    voice = np.pad(voice, (0, count - len(voice)))
    bed = make_music(duration)
    # Detect narration in 10ms blocks; 35ms attack, 450ms release.
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
    # Before ducking, music is 22dB below active voice RMS, capped at -32dBFS.
    bed_base = min(10 ** (-32 / 20), voice_active_rms * 10 ** (-22 / 20))
    unducked = bed * bed_base
    ducked = unducked * gain[:, None]
    mix = np.repeat(voice[:, None], 2, axis=1) + ducked
    wavfile.write(WORK / "original-warm-mystery-bed.wav", SR, unducked.astype(np.float32))
    wavfile.write(WORK / "ducked-music-bed.wav", SR, ducked.astype(np.float32))
    wavfile.write(WORK / "mix-before-normalization.wav", SR, mix.astype(np.float32))
    measured = loudness(WORK / "mix-before-normalization.wav", "premix-loudness.log")
    af = (
        "loudnorm=I=-16:TP=-1.5:LRA=11:"
        f"measured_I={measured['input_i']}:measured_TP={measured['input_tp']}:"
        f"measured_LRA={measured['input_lra']}:measured_thresh={measured['input_thresh']}:"
        f"offset={measured['target_offset']}:linear=true:print_format=json"
    )
    ffmpeg([
        "-i", WORK / "mix-before-normalization.wav", "-af", af,
        "-ar", str(SR), "-ac", "2", "-c:a", "pcm_s24le",
        WORK / "final-mix.wav"
    ], QA / "normalization.log")
    post = loudness(WORK / "final-mix.wav", "mix-loudness.log")
    normalization_log = (QA / "normalization.log").read_text()
    applied = json.loads(re.findall(r'\{\s*"input_i".*?\}', normalization_log, re.S)[-1])
    ffmpeg([
        "-i", WORK / "final-mix.wav", "-c:a", "aac", "-b:a", "192k",
        WORK / "audio-encode-test.m4a"
    ], QA / "audio-encode-test.log")
    encoded_meter = loudness(WORK / "audio-encode-test.m4a", "audio-encode-test-loudness.log")
    report = {
        "duration_seconds": duration, "sample_rate": SR,
        "original_narration_samples": original_sample_count,
        "narration_preservation": "All samples, original rate and timing; no speed edits",
        "music": {
            "method": "Original procedural harmonic ensemble and damped plucks; deterministic seed 20260912",
            "external_samples_or_paid_generation": False,
            "base_rms_dbfs": db(np.sqrt(np.mean(unducked ** 2))),
            "ducked_rms_dbfs": db(np.sqrt(np.mean(ducked ** 2))),
            "ducking_range_db": [-7, 0],
            "ending_fade_seconds": 2.5,
        },
        "premix_sample_peak_dbfs": db(np.max(np.abs(mix))),
        "normalized_mix_ebu_r128": post,
        "normalization_applied": applied,
        "aac_192k_preflight_ebu_r128": encoded_meter,
        "listening_review_performed": False,
        "listening_review_note": "Measured analysis only; human playback review required.",
    }
    write_json(QA / "audio-preparation.json", report)
    if not -16.8 <= float(post["input_i"]) <= -15.2:
        raise RuntimeError("Normalized mix loudness outside -16 +/-0.8 LUFS")
    if float(post["input_tp"]) > -1.1:
        raise RuntimeError("Normalized mix lacks sufficient true-peak headroom")
    if float(encoded_meter["input_tp"]) > -1.0:
        raise RuntimeError("AAC encoding test exceeds -1dBTP")
    print(json.dumps(report, indent=2))
    return report


def filter_path(path):
    return str(path).replace("\\", "\\\\").replace(":", "\\:").replace("'", "\\'")


def render(args):
    if not args.footage_approved:
        raise RuntimeError("Render blocked: inspect all footage, then pass --footage-approved")
    manifest = preflight()
    duration = manifest["duration_seconds"]
    prepare_audio(duration)
    inputs = []
    for clip in CLIPS:
        inputs += ["-i", str(clip)]
    inputs += ["-i", str(WORK / "final-mix.wav")]
    chain = (
        "".join(f"[{i}:v:0]" for i in range(6))
        + "concat=n=6:v=1:a=0,"
        + "scale=1080:1920:flags=lanczos,setsar=1,format=yuv420p"
    )
    if not args.no_brand:
        chain += (
            f",drawtext=fontfile='{FONT}':text='SOMEHOW TRUE':"
            "fontsize=24:fontcolor=white@0.70:x=58:y=130:"
            "shadowcolor=black@0.35:shadowx=0:shadowy=2"
        )
    # The optional number graphic is off by default; captions carry the story.
    if args.numeric_overlay:
        chain += (
            f",drawtext=fontfile='{FONT}':text='22 + 7 + 1 = 30':"
            "fontsize=47:fontcolor=0xf2e7ce:x=(w-tw)/2:y=440:"
            "shadowcolor=black@0.6:shadowx=0:shadowy=3:"
            "enable='between(t,29.5,34.5)'"
        )
    chain += f",ass=filename='{filter_path(CAPTIONS)}'[v]"
    ffmpeg([
        *inputs, "-filter_complex", chain, "-map", "[v]", "-map", "6:a:0",
        "-c:v", "libx264", "-threads:v", "2", "-preset", args.preset,
        "-crf", "18", "-pix_fmt", "yuv420p", "-fps_mode", "passthrough",
        "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
        "-movflags", "+faststart",
        "-metadata", "title=Somehow True — Baarle",
        "-metadata", "comment=AI-generated illustrative footage; 720x1280 source upscaled to 1080x1920. Original procedural music. No speed changes.",
        OUT,
    ], QA / "render.log")
    qa(manifest)


def qa(manifest=None):
    QA.mkdir(exist_ok=True)
    if not OUT.exists():
        raise RuntimeError("Final output does not exist")
    data = probe(OUT)
    write_json(QA / "final-ffprobe.json", data)
    meter = loudness(OUT, "final-loudness.log")
    ffmpeg([
        "-i", OUT, "-vn", "-af", "astats=metadata=0:reset=0",
        "-f", "null", "-"
    ], QA / "final-astats.log")
    decoded = run([
        "ffmpeg", "-v", "error", "-threads", "2", "-i", OUT,
        "-map", "0:v:0", "-f", "null", "-"
    ])
    manifest = manifest or json.loads((ROOT / "assembly_manifest.json").read_text())
    v = next(s for s in data["streams"] if s["codec_type"] == "video")
    ok = {
        "portrait_1080x1920": [v["width"], v["height"]] == [1080, 1920],
        "24fps": Fraction(v["avg_frame_rate"]) == 24,
        "all_source_frames": int(v["nb_frames"]) == manifest["expected_frame_count"],
        "loudness_near_minus16_lufs": -16.8 <= float(meter["input_i"]) <= -15.2,
        "true_peak_at_most_minus1_dbfs": float(meter["input_tp"]) <= -1.0,
        "full_decode_without_error": not decoded.stderr.strip(),
    }
    # Sample peak and clipped-sample count measured on actual AAC-decoded audio.
    raw = subprocess.run([
        "ffmpeg", "-v", "error", "-threads", "2", "-i", str(OUT),
        "-vn", "-f", "f32le", "-acodec", "pcm_f32le", "-"
    ], stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
    samples = np.frombuffer(raw.stdout, dtype="<f4")
    clipped = int(np.sum(np.abs(samples) >= 1))
    ok["no_clipped_decoded_samples"] = clipped == 0
    stats = {
        "checks": ok, "all_automated_checks_pass": all(ok.values()),
        "ebu_r128": meter, "sample_peak_dbfs": db(np.max(np.abs(samples))),
        "clipped_decoded_samples": clipped,
        "audio_rms_dbfs": db(np.sqrt(np.mean(samples.astype(np.float64) ** 2))),
        "review": "Automated metadata, frame count, decode and audio measurements. No listening review claimed.",
        "pending_manual_review": ["Footage factual appropriateness", "Caption timing/legibility", "Playback/music taste"],
    }
    write_json(QA / "final-audio-stats.json", stats)
    contact_sheet(manifest)
    print(json.dumps(stats, indent=2))
    if not all(ok.values()):
        raise RuntimeError("Final automated QA failed; inspect qa/final-audio-stats.json")


def contact_sheet(manifest):
    # Two readable samples per shot; second shot sample includes its latter half.
    times = []
    for shot, e in enumerate(manifest["clips"], 1):
        for fraction in (.23, .70):
            t = e["start_seconds"] + e["duration_seconds"] * fraction
            times.append((shot, t))
    w, h, header, footer = 270, 480, 72, 40
    sheet = Image.new("RGB", (w * 6, header + (h + footer) * 2), "#10151b")
    draw = ImageDraw.Draw(sheet)
    font = ImageFont.truetype(FONT, 22)
    small = ImageFont.truetype(FONT, 17)
    draw.text((20, 12), "SOMEHOW TRUE / BAARLE — FINAL FRAME QA", font=font, fill="#f2e7ce")
    draw.text((20, 42), "720p source → Lanczos 1080p output • original speed • hard cuts • captions burned", font=small, fill="#b5bdc8")
    for i, (shot, t) in enumerate(times):
        frame = QA / f"frame-{i+1:02d}-{t:06.2f}s.jpg"
        ffmpeg([
            "-ss", f"{t:.6f}", "-i", OUT, "-frames:v", "1",
            "-vf", "scale=270:480:flags=lanczos", "-threads:v", "2",
            "-q:v", "2", frame
        ])
        # Row 1: early sample in each shot; row 2: later sample.
        col, row = (i // 2), (i % 2)
        x, y = col * w, header + row * (h + footer)
        with Image.open(frame) as image:
            sheet.paste(image, (x, y))
        draw.text((x + 12, y + h + 10), f"SHOT {shot:02d}  /  {t:05.2f}s", font=small, fill="#e3e7eb")
    sheet.save(QA / "final-contact-sheet.jpg", quality=93)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--prepare", action="store_true", help="Generate original bed and normalized audio only")
    modes.add_argument("--render", action="store_true", help="Render after explicit footage inspection")
    modes.add_argument("--qa", action="store_true", help="Measure existing final and regenerate contact sheet")
    modes.add_argument("--check", action="store_true", help="Validate ready assets without rendering")
    parser.add_argument("--footage-approved", action="store_true")
    parser.add_argument("--no-brand", action="store_true")
    parser.add_argument("--numeric-overlay", action="store_true")
    parser.add_argument("--preset", choices=["fast", "medium"], default="fast")
    args = parser.parse_args()
    if args.prepare:
        prepare_audio()
    elif args.render:
        render(args)
    elif args.qa:
        qa()
    else:
        print(json.dumps(preflight(), indent=2))


if __name__ == "__main__":
    main()
