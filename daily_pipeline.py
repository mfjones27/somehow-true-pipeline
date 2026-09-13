#!/usr/bin/env python3
"""Daily automated pipeline — picks content, generates video, prepares uploads.

Designed to be called by a scheduled task (cron). The agent's role:
1. Run this script to pick content + generate config + run the pipeline
2. Call Drive connector to upload the final video
3. Call YouTube connector to upload + publish as public
4. Call Notion connector to update tracking

Usage:
  python daily_pipeline.py                    # pick next ready content
  python daily_pipeline.py --content FCT-005  # specific content
  python daily_pipeline.py --list             # show queue status

Content selection: picks the first row from CONTENT.csv that has a script
but hasn't been produced yet (no video_uri in the CSV).
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CONTENT_CSV = ROOT / "CONTENT.csv"
PRODUCED_LOG = ROOT / "pipeline_output" / "produced.json"
SCRIPTS_DIR = ROOT / "pipeline_output" / "scripts"

# Visual element keywords that map script content to visual descriptions
# Order matters: more specific cues first, general geography last
VISUAL_CUES = [
    # Specific structures first (before geography catches "building")
    (["house", "home", "door", "doorframe", "room"],
     "architectural close-up of a building facade or doorway with warm interior lighting"),
    (["building", "buildings"],
     "cinematic shot of old brick buildings with warm window light and textured facades"),
    # Space / astronomy
    (["star", "space", "cosmos", "galaxy", "nebula", "planet", "orbit", "spacecraft", "probe", "moon", "sun"],
     "deep space scene with stars and a distant glowing celestial body, cosmic scale"),
    (["launch", "rocket", "nasa"],
     "cinematic rocket launch or spacecraft against a dawn sky"),
    # Animals / nature
    (["animal", "bird", "fish", "insect", "shrimp", "wombat", "jellyfish", "mole", "godwit"],
     "macro wildlife shot of a small creature in its natural habitat, shallow depth of field"),
    (["ocean", "sea", "water", "wave", "coral", "reef"],
     "underwater or coastal scene with moving water and marine atmosphere"),
    (["forest", "tree", "jungle", "rainforest", "leaf", "plant"],
     "lush forest canopy scene with dappled sunlight through leaves"),
    (["desert", "sand", "dust", "dry"],
     "vast desert landscape with wind-blown sand and hazy horizon"),
    # Science / lab
    (["experiment", "laboratory", "lab", "scientist", "research", "study", "test"],
     "atmospheric laboratory interior with scientific equipment and warm focused lighting"),
    (["drop", "liquid", "pitch", "viscous", "molasses"],
     "extreme close-up of a single drop of dark viscous liquid slowly forming and falling"),
    # Engineering / structures
    (["bridge", "tower", "skyscraper", "structure", "construction", "steel", "weld"],
     "dramatic low-angle shot of a large architectural structure or bridge with engineering details"),
    (["manhattan", "urban", "skyline"],
     "cinematic cityscape with tall buildings and atmospheric light"),
    # History
    (["ancient", "century", "medieval", "historical", "vintage"],
     "period atmosphere with aged textures, warm sepia tones, and historical ambiance"),
    (["flood", "disaster", "burst", "tank"],
     "dramatic scene of dark liquid rushing through an old city street"),
    # Business / invention
    (["invent", "patent", "company", "business", "factory", "product", "card", "wrap", "bubble"],
     "close-up of hands working with a material or product in a warm workshop setting"),
    (["computer", "machine", "technology", "electronic", "device"],
     "retro-computing aesthetic with warm CRT glow and electronic components"),
    # People / behavior
    (["people", "person", "crowd", "human", "bystander", "pedestrian", "children", "child"],
     "cinematic shot of people in a public space, blurred motion, warm street lighting"),
    (["conflict", "fight", "argument", "aggressive"],
     "tense urban scene with motion blur suggesting conflict, dramatic shadows"),
    # Abstract
    (["abstract", "concept", "idea", "theory", "invisible", "microscopic"],
     "abstract macro photography with rich textures and dramatic lighting suggesting hidden worlds"),
    # Geography / borders — general, checked last so specific cues win first
    (["map", "puzzle", "patch", "nested", "surrounded"],
     "overhead shot of a mosaic-like pattern of different colored territories fitting together like puzzle pieces"),
    (["street", "road", "path", "lane", "cobblestone", "pavement"],
     "ground-level shot of a textured cobblestone or brick street stretching into the distance"),
    (["town", "city", "village", "square"],
     "wide shot of a charming old European town with brick buildings and narrow streets"),
    (["border", "enclave", "territory", "country", "countries", "nation", "dutch", "belgian", "netherlands", "belgium", "land"],
     "aerial view of a landscape with visible boundary lines cutting through fields and buildings"),
]

# Camera movement variety — each scene gets a different motion
CAMERA_MOVEMENTS = [
    "smooth slow camera dolly forward, revealing scale",
    "gentle camera pan right across the scene",
    "slow camera crane movement rising upward",
    "static camera with subtle subject motion in frame",
    "camera slowly pushes in toward a detail",
    "slow camera pull back revealing the wider context",
]

# Scene durations matching the original pipeline
SCENE_DURATIONS = [5, 8, 8, 8, 8, 10]


def load_content_queue():
    """Load all content rows from CONTENT.csv."""
    rows = []
    with open(CONTENT_CSV, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(row)
    return rows


def load_produced_log():
    """Load the log of already-produced content IDs."""
    if PRODUCED_LOG.exists():
        return json.loads(PRODUCED_LOG.read_text())
    return {"produced": [], "failed": []}


def save_produced_log(log):
    PRODUCED_LOG.parent.mkdir(parents=True, exist_ok=True)
    PRODUCED_LOG.write_text(json.dumps(log, indent=2) + "\n")


def pick_next_content():
    """Pick the first content row that has a script but hasn't been produced."""
    rows = load_content_queue()
    log = load_produced_log()
    produced = set(log.get("produced", []))

    for row in rows:
        cid = row["id"]
        if cid in produced:
            continue
        if not row.get("script", "").strip():
            continue
        if row.get("video_uri", "").strip():
            continue
        return row

    return None


def extract_visual_cue(text):
    """Extract a specific visual description from a script segment based on keywords.
    Returns the first (most specific) match from the ordered cue list."""
    text_lower = text.lower()
    for trigger_words, visual_desc in VISUAL_CUES:
        if any(re.search(r'\b' + re.escape(word) + r'\b', text_lower) for word in trigger_words):
            return visual_desc
    # Fallback: look for concrete nouns
    words = re.findall(r'\b[A-Z][a-z]{3,}\b', text)
    if words:
        return f"cinematic shot evoking the concept of {words[0].lower()}, warm natural lighting"
    return "cinematic abstract scene with rich textures and warm dramatic lighting"


def generate_scene_prompts(topic, script):
    """Generate 6 Runway scene prompts that visually match what's being said.

    Splits the script into 6 segments, extracts specific visual cues from each,
    and generates cinematic prompts with varied camera movements.
    """
    sentences = re.split(r'(?<=[.!?])\s+', script.strip())
    n = len(sentences)
    segments = []
    for i in range(6):
        start = int(i * n / 6)
        end = int((i + 1) * n / 6)
        segment = " ".join(sentences[start:end]) if start < end else sentences[min(start, n-1)]
        segments.append(segment)

    prompts = []
    for i, segment in enumerate(segments):
        visual = extract_visual_cue(segment)
        camera = CAMERA_MOVEMENTS[i % len(CAMERA_MOVEMENTS)]

        prompt = (
            f"Portrait 9:16 cinematic shot: {visual}. "
            f"The scene should evoke: {segment[:120]}. "
            f"{camera}. "
            "Warm cinematic color grade, film grain, 35mm lens, shallow depth of field. "
            "No text, logos, watermarks, or on-screen graphics. "
            "Keep the lower third of the frame visually calm and uncluttered for caption overlay. "
            "AI-generated illustration, not documentary footage."
        )

        if len(prompt.encode("utf-16-le")) // 2 > 950:
            prompt = prompt[:950]
        prompts.append(prompt)

    return prompts


def generate_config(content_row, narration_path=None):
    """Generate a full pipeline config from a content row."""
    cid = content_row["id"]
    topic = content_row["topic"]
    script = content_row["script"]
    core_fact = content_row.get("core_fact", "")

    # Parse sources from core_fact (URLs in parentheses)
    source_urls = re.findall(r'https?://[^\)]+]', core_fact)

    # Generate scene prompts
    scene_prompts = generate_scene_prompts(topic, script)

    # Build description
    description = f"{core_fact}\n\nSomehow True: facts that sound made up, checked before we tell them.\n"
    if source_urls:
        description += "\nSources:\n"
        for url in source_urls[:5]:
            description += f"{url}\n"
    description += "\nVisuals are AI-generated illustrations. Narration is synthetic. Music is original computer-generated.\n"
    description += f"\n#Shorts #{content_row.get('category', 'SomehowTrue').split('/')[0].strip()} #SomehowTrue"

    # Tags from topic and category
    category = content_row.get("category", "").split("/")[0].strip()
    tags = [word for word in re.findall(r'\b[A-Za-z]{3,}\b', topic)][:5]
    tags.extend(["Somehow True", "Shorts", category])
    tags = list(dict.fromkeys(tags))  # dedupe preserving order

    # Title: use the hook if available, otherwise topic
    hook = content_row.get("hook", "").strip()
    title = hook if hook else topic
    # Clean up title for YouTube
    title = re.sub(r'\s+', ' ', title).strip()
    if len(title) > 100:
        title = title[:97] + "..."

    config = {
        "content_id": cid,
        "title": title,
        "description": description,
        "tags": tags[:10],
        "script": script,
        "sources": source_urls,
        "clips_dir": None,  # will be generated by pipeline
        "captions_dir": None,
        "intro_clip": None,
        "narration_path": str(narration_path) if narration_path else None,
        "scene_prompts": scene_prompts,
        "scene_durations": SCENE_DURATIONS,
        "brand": "SOMEHOW TRUE",
        "output_name": f"somehow-true-{cid.lower()}.mp4",
        "youtube_channel_id": "UC7FJMzijz0T-SIll_8SYtaw",
        "runway_model": "gen4.5",
        "runway_ratio": "720:1280",
        "caption_font": "/usr/share/fonts/truetype/lato/Lato-Bold.ttf",
        "caption_font_size": 66,
        "caption_style": {
            "text_color": "&H00FFFFFF",
            "active_word_color": "&H87E2C5&",
            "outline_color": "&H0018100D",
            "pos_x": 485,
            "pos_y": 1400,
            "max_width_px": 780,
        },
    }

    return config


def run_daily(content_id=None, narration_path=None):
    """Main entry point for the daily pipeline."""
    print(f"\n{'='*60}")
    print("DAILY AUTOMATED PIPELINE")
    print(f"{'='*60}\n")

    # Step 0: Pick content
    if content_id:
        rows = load_content_queue()
        content_row = next((r for r in rows if r["id"] == content_id), None)
        if not content_row:
            print(f"ERROR: Content {content_id} not found in CONTENT.csv")
            return 1
    else:
        content_row = pick_next_content()

    if not content_row:
        print("No content ready for production. All rows with scripts have been produced.")
        print("To continue: add scripts to rows in CONTENT.csv, or research new topics.")
        return 1

    cid = content_row["id"]
    topic = content_row["topic"]
    print(f"Selected: {cid} — {topic[:60]}...")

    if not content_row.get("script", "").strip():
        print(f"ERROR: {cid} has no script. Skipping.")
        return 1

    # Step 1: Generate config
    print("\nGenerating pipeline config...")
    config = generate_config(content_row, narration_path)

    # Save config
    config_dir = ROOT / "pipeline_output" / cid
    config_dir.mkdir(parents=True, exist_ok=True)
    config_path = config_dir / "config.json"
    config_path.write_text(json.dumps(config, indent=2) + "\n")
    print(f"Config saved: {config_path}")

    # Step 2: Check narration
    if not narration_path:
        # Check for existing narration
        possible_paths = [
            ROOT / "video_factory" / "assets" / "pilot" / "narration.wav",
            ROOT / "pipeline_output" / cid / "narration.wav",
        ]
        for p in possible_paths:
            if p.exists():
                narration_path = p
                break

    if not narration_path or not Path(narration_path).exists():
        print(f"\n*** NARRATION NEEDED ***")
        print(f"The agent must generate TTS narration for {cid}.")
        print(f"Script: {content_row['script'][:200]}...")
        print(f"Save narration to: {config_dir / 'narration.wav'}")
        print(f"Then re-run this script with --narration {config_dir / 'narration.wav'}")
        # Save the script for TTS
        script_path = config_dir / "script.txt"
        script_path.write_text(content_row["script"])
        print(f"Script saved to: {script_path}")
        return 2  # Special exit code: needs narration

    config["narration_path"] = str(narration_path)
    config_path.write_text(json.dumps(config, indent=2) + "\n")

    # Step 3: Run the pipeline
    print(f"\nRunning produce_video.py...")
    cmd = [
        sys.executable, str(ROOT / "produce_video.py"),
        "--config", str(config_path),
    ]
    print(f"Command: {' '.join(cmd)}")
    result = subprocess.run(cmd)
    if result.returncode:
        print(f"Pipeline FAILED for {cid}")
        log = load_produced_log()
        log.setdefault("failed", []).append(cid)
        save_produced_log(log)
        return 1

    # Step 4: Check output
    output_path = config_dir / config["output_name"]
    if not output_path.exists():
        print(f"ERROR: Output video not found at {output_path}")
        return 1

    print(f"\n{'='*60}")
    print(f"VIDEO PRODUCED: {cid}")
    print(f"Output: {output_path}")
    print(f"Size: {output_path.stat().st_size:,} bytes")
    print(f"{'='*60}")

    # Step 5: Mark as produced
    log = load_produced_log()
    log.setdefault("produced", []).append(cid)
    save_produced_log(log)

    # Step 6: Prepare upload payloads for the agent
    upload_payload = {
        "content_id": cid,
        "video_path": str(output_path),
        "video_filename": output_path.name,
        "title": config["title"],
        "description": config["description"],
        "tags": config["tags"],
        "youtube_channel_id": config["youtube_channel_id"],
        "notion_page_id": None,  # Will be set by agent
        "drive_folder_id": None,  # Will be set by agent
        "instructions": [
            f"1. Upload {output_path.name} to Google Drive (05_Renders folder)",
            f"2. Upload video to YouTube with title='{config['title']}'",
            f"   description from config, tags={config['tags']}, privacyStatus='public'",
            f"3. Update Notion: mark {cid} as published with video URL",
        ],
    }
    upload_path = config_dir / "upload_payload.json"
    upload_path.write_text(json.dumps(upload_payload, indent=2) + "\n")
    print(f"\nUpload payload saved: {upload_path}")
    print(f"\nAGENT NEXT STEPS:")
    for step in upload_payload["instructions"]:
        print(f"  {step}")

    return 0


def list_queue():
    """Show the content queue status."""
    rows = load_content_queue()
    log = load_produced_log()
    produced = set(log.get("produced", []))
    failed = set(log.get("failed", []))

    print(f"\nCONTENT QUEUE STATUS")
    print(f"{'='*80}")
    print(f"{'ID':<10} {'Status':<15} {'Script':<8} {'Produced':<10} {'Topic':<40}")
    print(f"{'-'*80}")
    for row in rows:
        has_script = "YES" if row.get("script", "").strip() else "no"
        is_produced = "YES" if row["id"] in produced else "no"
        is_failed = " (FAILED)" if row["id"] in failed else ""
        print(f"{row['id']:<10} {row['status']:<15} {has_script:<8} {is_produced:<10} {row['topic'][:40]}{is_failed}")

    ready = sum(1 for r in rows if r.get("script", "").strip() and r["id"] not in produced)
    print(f"\n{ready} content rows ready for production (have script, not yet produced)")
    print(f"{len(produced)} already produced, {len(failed)} failed")


def main():
    parser = argparse.ArgumentParser(description="Daily automated video pipeline")
    parser.add_argument("--content", help="Specific content ID to produce")
    parser.add_argument("--narration", help="Path to narration WAV file")
    parser.add_argument("--list", action="store_true", help="Show queue status")
    args = parser.parse_args()

    if args.list:
        list_queue()
        return 0

    return run_daily(args.content, args.narration)


if __name__ == "__main__":
    sys.exit(main())
