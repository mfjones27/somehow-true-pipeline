# Somehow True Pipeline

Automated video production pipeline for the Somehow True YouTube channel. Generates cinematic short-form videos from scripted narration using Runway AI visuals, automated captions, and procedural music — all in one pass.

## Architecture

```
Script → TTS narration → Runway clips → Whisper captions → ffmpeg assembly → YouTube upload
```

| Component | Tool | Cost |
|-----------|------|------|
| Visuals | Runway Gen-4.5 API | ~500 credits (5 clips) |
| Captions | faster-whisper | Free (local) |
| Music | scipy + numpy (procedural) | Free (local) |
| Assembly | ffmpeg (Lanczos upscale + burn) | Free (local) |
| Upload | YouTube Data API | Free |
| **Total per video** | | **~500-1,500 credits** |

## Quick Start (Local)

```bash
# Install dependencies
pip install -r requirements.txt

# System: ffmpeg, fonts-lato (or fonts-dejavu as fallback)
# Ubuntu: sudo apt install ffmpeg fonts-lato fonts-dejavu

# Run with existing assets (test mode)
python produce_video.py --config config.example.json --skip-runway --skip-captions

# Run full pipeline
python produce_video.py --config config.json

# Run daily automation
python daily_pipeline.py
```

## Railway Deployment

### Prerequisites

1. A [Railway](https://railway.app) account
2. A [GitHub](https://github.com) account
3. Runway API key (for video generation)

### Deploy Steps

1. **Push this repo to GitHub**
   ```bash
   git remote add origin https://github.com/YOUR_USERNAME/somehow-true-pipeline.git
   git push -u origin main
   ```

2. **Create a new Railway project**
   - Go to [railway.app/new](https://railway.app/new)
   - Select "Deploy from GitHub repo"
   - Choose your `somehow-true-pipeline` repo

3. **Railway auto-detects** the `Dockerfile` and `railway.toml` — no manual config needed.

4. **Set environment variables** in Railway:
   ```
   RUNWAY_API_KEY=your_key_here
   YOUTUBE_API_KEY=your_key_here   # optional, for uploads
   ```

5. **Deploy** — Railway builds the Docker image (installs ffmpeg + Python deps) and starts the FastAPI server.

### API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/health` | Health check (Railway uses this) |
| POST | `/produce` | Run pipeline from config or content ID |
| POST | `/produce/daily` | Pick next content, generate video |
| GET | `/queue` | Show content queue status |
| GET | `/jobs/{job_id}` | Check background job status |

### Example: Trigger a video via API

```bash
# Test render (no Runway, no captions — uses existing clips)
curl -X POST https://your-app.up.railway.app/produce \
  -H "Content-Type: application/json" \
  -d '{"content_id": "FCT-011", "skip_runway": true, "skip_captions": true}'

# Full production
curl -X POST https://your-app.up.railway.app/produce/daily \
  -H "Content-Type: application/json" \
  -d '{}'
```

### Cron Deployment (Daily Auto-Post)

Railway supports cron deployments. To run the pipeline daily:

1. In Railway, go to your service → **Settings** → **Cron Jobs**
2. Add a cron schedule: `0 10 * * *` (10:00 AM UTC daily)
3. Command: `python daily_pipeline.py`

Or use Railway's built-in scheduler with the command:
```bash
python daily_pipeline.py --upload
```

## Project Structure

```
somehow-true-pipeline/
├── app.py                  # FastAPI server (Railway entry point)
├── produce_video.py         # Unified pipeline: Runway + captions + assembly + QA
├── daily_pipeline.py        # Content selection + scene prompt generation
├── config.example.json      # Config template (FCT-011 Baarle)
├── CONTENT.csv              # 20-row content queue (5 with scripts)
├── requirements.txt         # Python dependencies
├── Dockerfile               # Railway/Docker build (ffmpeg + Python)
├── railway.toml             # Railway deployment config
├── full_pilot/
│   ├── assemble.py           # Video assembly (music, ducking, upscale, captions)
│   └── ASSEMBLY_HANDOFF.txt  # Assembly instructions
├── space_next/
│   └── runway_tasks.py       # Runway API client (create/status/download)
├── video_factory/
│   ├── README.md             # Local rendering engine docs
│   ├── video_factory/        # Python package (Pillow + ffmpeg renderer)
│   └── examples/             # Template configs
└── PIPELINE_OPTIMIZATION.md  # Credit optimization breakdown
```

## Caption Style

- **Font:** Lato Bold (falls back to DejaVu Sans Bold)
- **Style:** Borderless with drop shadow (modern trend)
  - Outline: 0 (no border)
  - Shadow: 3.5 (subtle drop shadow for readability)
  - Font size: 72px
- **Active word highlight:** Lime green (#C5E287)
- **Format:** ASS subtitles burned into video + SRT for native platform captions

## Scene Prompt Generation

Scene prompts are generated from the script content, not generic templates:
1. Script is split into 6 segments matching scene durations
2. Visual cues are extracted from each segment via keyword matching
3. Camera movements vary across scenes (dolly, pan, crane, push-in, pull-back)
4. Each prompt includes the narration context so Runway generates matching visuals

## Credits

Built for the [Somehow True](https://www.youtube.com/@SomehowTrueMedia) YouTube channel.
