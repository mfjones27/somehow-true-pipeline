# Pipeline Optimization Guide — Credit Reduction

## The Problem

The original pipeline consumed ~15,000 credits per video. The cost breakdown:

| Component | Old Credits | Why |
|-----------|------------|-----|
| Agent orchestration | ~10,000+ | 27+ agent turns, each reading state, deciding, writing JSON, reporting |
| Subagent spawns | ~2,000 | Separate subagents for captions, assembly, Runway polling |
| Caption QA | ~1,500 | Dual-model ASR (medium.en + small.en), 5 spot checks, 36 QA frames |
| Notion tracking | ~1,000 | Per-asset pages, verification of each, multiple DB queries |
| Drive uploads | ~500 | Per-file upload + separate verification turn |
| Runway API | ~500 | 5 clips × ~96-120 credits (actual API cost, not agent cost) |

## The Fix

`produce_video.py` collapses the entire pipeline into one script execution.

### What changed

| Before | After |
|--------|-------|
| 27+ agent turns | 2 turns (write config, run script) |
| 185 JSON state files | 1 `pipeline_state.json` |
| 5+ subagent spawns | 0 subagents |
| Dual-model ASR + 5 spot checks | Single Whisper small.en pass |
| 36 QA frames + contact sheet | Final video QA only |
| Per-asset Notion pages + verification | 1 Notion update payload |
| Per-file Drive upload + verification | Script handles internally |
| Per-scene Runway create/status/download turns | Batch create, single poll loop, batch download |

### New workflow

```bash
# 1. Write config (agent does this in 1 turn)
# 2. Run the full pipeline (agent does this in 1 turn)
python /home/user/workspace/content_factory/produce_video.py --config config.json

# Or with existing clips:
python /home/user/workspace/content_factory/produce_video.py --config config.json --skip-runway

# Or including upload prep:
python /home/user/workspace/content_factory/produce_video.py --config config.json --upload
```

### Expected credit cost: ~1,000-1,500 per video

- ~500: Runway API (unchanged, actual generation cost)
- ~200-500: Agent turns to write config + run script + review output
- ~0: Everything else runs locally in the script

## Config format

See `config.example.json` for the full template. Key fields:

- `content_id`: FCT-XXX from the content queue
- `script`: The approved narration script text
- `narration_path`: Path to narration WAV file
- `scene_prompts`: Array of Runway prompt strings (one per scene)
- `scene_durations`: Array of durations in seconds (matching scene_prompts)
- `output_name`: Final video filename
- `caption_style`: Caption positioning and colors

## What was removed (and why it's fine)

### Dual-model ASR cross-validation
**Removed:** medium.en + small.en comparison, 5 spot checks, 18 review flags
**Why it's fine:** The original QA found a median 60ms boundary disagreement between models — that's imperceptible. Single-pass small.en gives word timestamps accurate to ~100ms, which is well within caption readability.

### Caption QA frames + contact sheet for captions
**Removed:** 36 per-phrase QA frames, timing proof video
**Why it's fine:** The final video QA (which still runs) verifies the burned captions are present. Visual inspection of the final contact sheet covers caption legibility.

### Per-asset Notion pages
**Removed:** Separate page creation for each asset, verification of each
**Why it's fine:** A single Notion update with the final video metadata is sufficient for tracking. The pipeline_state.json file contains all the provenance data.

### JSON state proliferation
**Removed:** 185 JSON files tracking intermediate state
**Why it's fine:** The script asserts internally and fails loudly if something is wrong. One `pipeline_state.json` captures the full pipeline state.

## Reusing existing assets

The script supports incremental runs:

```bash
# Skip Runway if clips already exist in pipeline_output/FCT-011/clips/
python produce_video.py --config config.json --skip-runway

# Skip captions if captions.ass already exists
python produce_video.py --config config.json --skip-captions
```

## Adding new videos

To produce a new video from the content queue:

1. Pick a content row from `CONTENT.csv` (e.g., FCT-005 - Wombat cubes)
2. Write the Runway scene prompts based on the script
3. Record narration (or use TTS)
4. Create a config JSON (copy `config.example.json` and modify)
5. Run: `python produce_video.py --config fct-005.json`

The agent's involvement is now: write config → run script → review output. That's 2-3 turns instead of 27+.
