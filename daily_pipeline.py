#!/usr/bin/env python3
"""Daily automated pipeline — research, narrate, render, upload private.

Usage:
  python daily_pipeline.py                    # next unproduced row
  python daily_pipeline.py --content FCT-005  # specific content
  python daily_pipeline.py --list             # show queue status
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from providers.env import load_env
from providers.costs import print_summary
from providers.elevenlabs_tts import spoken_script, synthesize
from providers.openai_research import detect_format, hunt_viral_idea, research_topic, runway_prompts_for_script
from providers.youtube_upload import credentials_ready, youtube_title

load_env()

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

# 45-second short: six clips, no leftover 10s tail
SCENE_DURATIONS = [5, 8, 8, 8, 8, 8]


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


def save_content_queue(rows):
    if not rows:
        return
    fieldnames = list(rows[0].keys())
    with open(CONTENT_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def update_content_row(cid, **fields):
    rows = load_content_queue()
    updated = None
    for row in rows:
        if row["id"] == cid:
            row.update({k: "" if v is None else str(v) for k, v in fields.items()})
            row["updated_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
            updated = row
            break
    if updated is None:
        raise RuntimeError(f"Content {cid} not found in CONTENT.csv")
    save_content_queue(rows)
    return updated


def pick_next_content():
    """Pick the first unproduced row. Script can be filled by Astra on this run."""
    rows = load_content_queue()
    log = load_produced_log()
    produced = set(log.get("produced", []))

    for row in rows:
        cid = row["id"]
        if cid in produced:
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


def load_research(cid):
    path = ROOT / "pipeline_output" / cid / "research.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {}


def generate_config(content_row, narration_path=None, researched=None):
    """Generate a full pipeline config from a content row."""
    cid = content_row["id"]
    topic = content_row["topic"]
    script = spoken_script(content_row["script"])
    core_fact = content_row.get("core_fact", "")
    researched = researched or load_research(cid)

    source_urls = researched.get("sources") or re.findall(r'https?://[^\s\)\]]+', core_fact)
    scene_prompts = researched.get("scene_prompts") or generate_scene_prompts(topic, script)
    scene_durations = researched.get("scene_durations") or SCENE_DURATIONS[: len(scene_prompts)]

    description = researched.get("description")
    if not description:
        description = f"{core_fact}\n\nSomehow True: facts that sound made up, checked before we tell them.\n"
        if source_urls:
            description += "\nSources:\n"
            for url in source_urls[:5]:
                description += f"{url}\n"
        description += "\nVisuals are AI-generated illustrations. Narration is synthetic. Music is original computer-generated.\n"
        description += f"\n#Shorts #{content_row.get('category', 'SomehowTrue').split('/')[0].strip()} #SomehowTrue"

    category = content_row.get("category", "").split("/")[0].strip()
    tags = list(researched.get("tags") or [])
    if not tags:
        tags = [word for word in re.findall(r'\b[A-Za-z]{3,}\b', topic)][:5]
        tags.extend(["Somehow True", "Shorts", category])
    tags = list(dict.fromkeys(tags))

    hook = content_row.get("hook", "").strip()
    title = youtube_title(hook if hook else topic)

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
        "scene_durations": scene_durations,
        "brand": "SOMEHOW TRUE",
        "output_name": f"somehow-true-{cid.lower()}.mp4",
        "youtube_channel_id": "UCZqmUx29Va8Zud78Fj_0Geg",
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

    config_dir = ROOT / "pipeline_output" / cid
    config_dir.mkdir(parents=True, exist_ok=True)

    researched = load_research(cid)
    if not content_row.get("script", "").strip():
        print(f"\nResearching {cid} with GPT-6 Astra + web search...")
        researched = research_topic(
            topic,
            content_row.get("core_fact", ""),
            format=detect_format(topic, content_row.get("hook", "")),
        )
        content_row = update_content_row(
            cid,
            hook=researched["hook"],
            core_fact=researched["core_fact"],
            script=researched["script"],
            script_version=str(int(content_row.get("script_version") or 0) + 1),
            status="Fact check",
        )
        (config_dir / "research.json").write_text(json.dumps(researched, indent=2) + "\n")
        print(f"Script and {len(researched['scene_prompts'])} Runway prompts saved for {cid}")
    elif not researched.get("scene_prompts"):
        print(f"\nAstra writing 6 Runway prompts for existing {cid} script...")
        prompts = runway_prompts_for_script(content_row["script"], topic, cid)
        researched = {**researched, **prompts, "script": content_row["script"]}
        (config_dir / "research.json").write_text(json.dumps(researched, indent=2) + "\n")
        print(f"{len(prompts['scene_prompts'])} Runway prompts saved")

    print("\nGenerating pipeline config...")
    config = generate_config(content_row, narration_path, researched)
    config_path = config_dir / "config.json"
    config_path.write_text(json.dumps(config, indent=2) + "\n")
    print(f"Config saved: {config_path}")

    if not narration_path:
        existing = config_dir / "narration.wav"
        if existing.exists():
            narration_path = existing

    if not narration_path or not Path(narration_path).exists():
        print(f"\nGenerating ElevenLabs narration for {cid}...")
        spoken = spoken_script(content_row["script"])
        if spoken != (content_row.get("script") or "").strip():
            content_row = update_content_row(cid, script=spoken)
        (config_dir / "script.txt").write_text(spoken, encoding="utf-8")
        narration_path = synthesize(spoken, config_dir / "narration.wav", cid)
        print(f"Narration saved: {narration_path}")

    config["narration_path"] = str(narration_path)
    config_path.write_text(json.dumps(config, indent=2) + "\n")

    print("\nRunning produce_video.py...")
    cmd = [sys.executable, str(ROOT / "produce_video.py"), "--config", str(config_path)]
    should_upload = credentials_ready()
    if should_upload:
        cmd.append("--upload")
    print(f"Command: {' '.join(cmd)}")
    result = subprocess.run(cmd)
    if result.returncode:
        print(f"Pipeline FAILED for {cid}")
        log = load_produced_log()
        log.setdefault("failed", []).append(cid)
        save_produced_log(log)
        return 1

    output_path = config_dir / config["output_name"]
    if not output_path.exists():
        print(f"ERROR: Output video not found at {output_path}")
        return 1

    print(f"\nVIDEO PRODUCED: {cid}")
    print(f"Output: {output_path}")
    print(f"Size: {output_path.stat().st_size:,} bytes")

    log = load_produced_log()
    log.setdefault("produced", []).append(cid)
    save_produced_log(log)

    youtube_url = ""
    duration_seconds = ""
    state_path = config_dir / "pipeline_state.json"
    if state_path.exists():
        state = json.loads(state_path.read_text())
        duration_seconds = str(state.get("output_qa", {}).get("duration_seconds", "") or "")
        for step in state.get("steps", []):
            if step.get("step") == "upload":
                youtube_url = step.get("youtube", {}).get("url", "")

    update_content_row(
        cid,
        status="rendered_needs_qa",
        video_uri=youtube_url or str(output_path),
        duration_seconds=duration_seconds,
    )
    if youtube_url:
        print(f"YouTube (private): {youtube_url}")
        print("Open Studio on your phone, confirm the AI label, then switch to public.")
    elif should_upload:
        print("Upload was requested but no YouTube URL was written.")
    else:
        print("YouTube OAuth not set. Video is local only.")

    print_summary(cid)
    return 0


def next_content_id(rows=None) -> str:
    rows = rows if rows is not None else load_content_queue()
    nums = []
    for row in rows:
        match = re.match(r"FCT-(\d+)$", row.get("id", ""))
        if match:
            nums.append(int(match.group(1)))
    return f"FCT-{max(nums, default=0) + 1:03d}"


def enqueue_idea(idea: str, category: str = "", *, surprise: bool = False) -> dict:
    """Astra sharpens a thought into a queue row. Script is written on produce."""
    idea = (idea or "").strip()
    if not surprise and len(idea) < 8:
        raise ValueError("Tell it a little more — a sentence is enough.")
    rows = load_content_queue()
    avoid: list[str] = []
    for row in rows[-30:]:
        if row.get("topic"):
            avoid.append(row["topic"])
        if row.get("hook"):
            avoid.append(row["hook"])
    angle = hunt_viral_idea(idea, avoid=avoid, queue_size=len(rows))
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    fieldnames = list(rows[0].keys()) if rows else [
        "id", "topic", "category", "fingerprint", "hook", "core_fact", "script",
        "script_version", "editorial_score", "status", "fact_check_verdict",
        "production_approval", "publication_approval", "video_uri", "video_sha256",
        "duration_seconds", "created_at", "updated_at",
    ]
    row = {key: "" for key in fieldnames}
    row.update({
        "id": next_content_id(rows),
        "topic": angle["topic"],
        "category": (category or angle["category"] or "Idea").strip(),
        "fingerprint": hashlib.sha256(angle["topic"].encode()).hexdigest(),
        "hook": angle["hook"],
        "core_fact": angle["core_fact"],
        "script_version": "0",
        "editorial_score": "0",
        "status": "Needs research",
        "created_at": now,
        "updated_at": now,
    })
    rows.append(row)
    save_content_queue(rows)
    return {**row, "angle": angle["angle"]}


def queue_snapshot() -> dict:
    rows = load_content_queue()
    log = load_produced_log()
    produced = set(log.get("produced", []))
    failed = set(log.get("failed", []))
    items = []
    for row in rows:
        cid = row["id"]
        items.append({
            "id": cid,
            "topic": row.get("topic", ""),
            "category": row.get("category", ""),
            "hook": row.get("hook", ""),
            "status": row.get("status", ""),
            "has_script": bool(row.get("script", "").strip()),
            "produced": cid in produced or bool(str(row.get("video_uri", "")).strip()),
            "failed": cid in failed,
            "video_uri": row.get("video_uri", ""),
        })
    ready = sum(1 for item in items if not item["produced"])
    return {
        "rows": items,
        "ready": ready,
        "produced": sum(1 for item in items if item["produced"]),
        "failed": len(failed),
        "total": len(items),
    }


def list_queue():
    """Show the content queue status."""
    snap = queue_snapshot()
    print("\nCONTENT QUEUE STATUS")
    print(f"{'='*80}")
    print(f"{'ID':<10} {'Status':<15} {'Script':<8} {'Produced':<10} {'Topic':<40}")
    print(f"{'-'*80}")
    for row in snap["rows"]:
        has_script = "YES" if row["has_script"] else "no"
        is_produced = "YES" if row["produced"] else "no"
        is_failed = " (FAILED)" if row["failed"] else ""
        print(f"{row['id']:<10} {row['status']:<15} {has_script:<8} {is_produced:<10} {row['topic'][:40]}{is_failed}")
    print(f"\n{snap['ready']} content rows not yet produced")
    print(f"{snap['produced']} already produced, {snap['failed']} failed")


def list_videos() -> list[dict]:
    from providers.youtube_upload import youtube_links

    csv_urls = {row["id"]: row.get("video_uri", "") for row in load_content_queue()}
    out = []
    base = ROOT / "pipeline_output"
    if not base.exists():
        return out
    for folder in sorted(base.iterdir(), reverse=True):
        if not folder.is_dir() or folder.name in {"scripts"}:
            continue
        cfg_path = folder / "config.json"
        if not cfg_path.exists():
            continue
        cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
        state = {}
        state_path = folder / "pipeline_state.json"
        if state_path.exists():
            state = json.loads(state_path.read_text(encoding="utf-8"))
        youtube = ""
        for step in state.get("steps", []):
            if step.get("step") == "upload":
                youtube = (step.get("youtube") or {}).get("url", "")
        cid = cfg.get("content_id", folder.name)
        links = youtube_links(youtube or csv_urls.get(cid, ""))
        mp4 = folder / cfg.get("output_name", f"somehow-true-{folder.name.lower()}.mp4")
        out.append({
            "id": cid,
            "title": cfg.get("title", folder.name),
            "youtube": links["studio"] or youtube,
            "watch": links["watch"],
            "studio": links["studio"],
            "local": str(mp4) if mp4.exists() else "",
            "duration_seconds": (state.get("output_qa") or {}).get("duration_seconds"),
            "complete": bool(state.get("all_steps_complete")),
        })
    return out


def main():
    parser = argparse.ArgumentParser(description="Daily automated video pipeline")
    parser.add_argument("--content", help="Specific content ID to produce")
    parser.add_argument("--idea", help="Sharpen a freeform idea with Astra, then produce")
    parser.add_argument("--surprise", action="store_true", help="Let Astra pick a viral fact, then produce")
    parser.add_argument("--narration", help="Path to narration WAV file")
    parser.add_argument("--list", action="store_true", help="Show queue status")
    args = parser.parse_args()

    if args.list:
        list_queue()
        return 0

    if args.idea or args.surprise:
        row = enqueue_idea(args.idea or "", surprise=args.surprise)
        print(f"Queued {row['id']}: {row.get('hook') or row['topic']}")
        print(f"Angle: {row.get('angle', '')}")
        return run_daily(row["id"], args.narration)

    return run_daily(args.content, args.narration)


if __name__ == "__main__":
    sys.exit(main())
