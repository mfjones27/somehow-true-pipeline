#!/usr/bin/env python3
"""Full short-video test: Astra → ElevenLabs → Runway → assemble → YouTube private."""
from __future__ import annotations

import json
from pathlib import Path

from providers.env import load_env
from providers.elevenlabs_tts import synthesize
from providers.openai_research import research_topic
from produce_video import run_pipeline

load_env()

ROOT = Path(__file__).resolve().parent
WORK = ROOT / "pipeline_output" / "SMOKE"
TOPIC = "There is a jellyfish that can age backwards into its juvenile form"


def main() -> int:
    WORK.mkdir(parents=True, exist_ok=True)
    research_path = WORK / "research.json"
    if research_path.exists():
        print("Reusing Astra research from the last run...")
        researched = json.loads(research_path.read_text(encoding="utf-8"))
    else:
        print("Astra researching a 10-second short...")
        researched = research_topic(TOPIC, short=True)
        research_path.write_text(json.dumps(researched, indent=2) + "\n", encoding="utf-8")
    print(f"Hook: {researched['hook']}")
    print(f"Script ({len(researched['script'].split())} words): {researched['script']}")
    for i, (prompt, dur) in enumerate(zip(researched["scene_prompts"], researched["scene_durations"]), 1):
        print(f"Runway scene {i} ({dur}s): {prompt[:160]}...")

    print("\nElevenLabs narration...")
    wav = synthesize(researched["script"], WORK / "narration.wav")
    print(f"Narration: {wav}")

    config = {
        "content_id": "SMOKE",
        "title": researched["hook"],
        "description": researched["description"],
        "tags": researched["tags"][:10],
        "script": researched["script"],
        "sources": researched["sources"],
        "clips_dir": None,
        "captions_dir": None,
        "intro_clip": None,
        "narration_path": str(wav),
        "scene_prompts": researched["scene_prompts"],
        "scene_durations": researched["scene_durations"],
        "brand": "SOMEHOW TRUE",
        "output_name": "somehow-true-smoke.mp4",
        "youtube_channel_id": "UCZqmUx29Va8Zud78Fj_0Geg",
        "runway_model": "seedance2_5",
        "runway_ratio": "1080:1920",
        "caption_font_size": 66,
        "caption_style": {
            "text_color": "&H00FFFFFF",
            "active_word_color": "&H87E2C5",
            "outline_color": "&H0018100D",
            "pos_x": 540,
            "pos_y": 1400,
            "max_width_px": 900,
        },
    }
    config_path = WORK / "config.json"
    config_path.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")

    print("\nRunning full produce + YouTube private upload...")
    skip_runway = any((WORK / "clips").glob("scene*.mp4"))
    skip_captions = (WORK / "captions" / "captions.ass").exists()
    state = run_pipeline(
        str(config_path),
        skip_runway=skip_runway,
        skip_captions=skip_captions,
        upload=True,
    )
    youtube = next((s.get("youtube") for s in state.get("steps", []) if s.get("step") == "upload"), {})
    print(f"Video: {state.get('output_path')}")
    if youtube:
        print(f"YouTube (private): {youtube.get('url')}")
        print("Open Studio on your phone, confirm the AI label, then switch to public.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
