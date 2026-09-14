# Somehow True Pipeline

Video production prototype for the Somehow True YouTube channel. **Deploy in idle mode only:** generation and publishing are not activation-ready. Deploying the API is not approval to produce or publish content.

## Architecture

```
Approved script + supplied narration → Runway clips → Whisper captions → ffmpeg assembly
                                                                      → upload metadata only
```

| Component | Tool | Cost |
|-----------|------|------|
| Visuals | Runway Gen-4.5 API | ~500 credits (5 clips) |
| Captions | faster-whisper | Free (local) |
| Music | scipy + numpy (procedural) | Free (local) |
| Assembly | ffmpeg (Lanczos upscale + burn) | Free (local) |
| Upload | Metadata preparation only; uploader not implemented | Not validated |
| **Historical estimate per video** | | **~500-1,500 credits; not current pricing or authorization** |

## Quick Start (Local, Idle API)

```bash
# Install dependencies
pip install -r requirements.txt

# System: ffmpeg, fonts-lato (or fonts-dejavu as fallback)
# Ubuntu: sudo apt install ffmpeg fonts-lato fonts-dejavu

# Supply a unique random API_TOKEN through your secret manager/environment.
# Do not commit the token, provider credentials, or .env files.
export PIPELINE_ENABLED=false
python app.py
```

`python app.py` starts the API only. It does not import the media pipeline,
contact providers, generate narration, load models, produce video, or upload.
Without `API_TOKEN`, only `GET /health` can be accessed.
Do not run either pipeline CLI or configure a cron job during deployment.

## Railway Deployment

### Prerequisites

1. A [Railway](https://railway.app) account
2. A [GitHub](https://github.com) account
3. A unique high-entropy `API_TOKEN` stored as a Railway secret variable

No Runway, YouTube, Drive, Notion or TTS credentials are needed for idle deployment.

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

3. Use the repository `Dockerfile` and `railway.toml`. Both start `python app.py`,
   which binds `0.0.0.0` using Railway's `PORT` (default `8000` locally).

4. **Set environment variables** in Railway:
   ```
   PIPELINE_ENABLED=false
   API_TOKEN=<unique-random-secret>
   ```

5. **Deploy** — Railway builds the Docker image (installs ffmpeg + Python deps) and starts the idle FastAPI server. Build-time package downloads are expected; server startup performs no provider/model/generation calls.
6. Verify `GET /health` returns `200`. Do not enable production as a deployment test.

Only the value `true` (case-insensitive, ignoring surrounding spaces) enables
production routes; missing, false, and unknown values remain disabled. This switch
is an operational lock, **not** a content approval or publishing-policy engine.
All non-health requests require `Authorization: Bearer <API_TOKEN>`. Missing,
blank, or incorrect credentials return `401`, including when the server token is
unset. Authenticated `/produce` requests return `503` in idle mode before request
body validation, job creation, background scheduling, or subprocess execution.
Interactive docs and the OpenAPI endpoint are disabled.

### API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/health` | Public liveness only (not provider/pipeline readiness) |
| POST | `/produce` | Authenticated; blocked with `503` in idle mode |
| POST | `/produce/daily` | Authenticated; blocked with `503` in idle mode |
| GET | `/queue` | Authenticated; runs the local read-only queue-list command |
| GET | `/jobs/{job_id}` | Authenticated; checks in-memory job status |

### Safe deployment verification

```bash
# Public liveness: expect 200.
curl -i https://your-app.up.railway.app/health

# Without authentication: expect 401.
curl -i https://your-app.up.railway.app/queue

# Only while PIPELINE_ENABLED=false: expect 503, no job or media work.
curl -i -X POST https://your-app.up.railway.app/produce/daily \
  -H "Authorization: Bearer $API_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{}'
```

### Offline safety tests
```bash
python -m unittest discover -s tests -v
```

These tests use in-memory HTTP requests and the standard library, with no extra
test-client dependency. They reject subprocess/network/file-write/background-task
side effects and cover public health, authentication, disabled production, disabled
docs, startup and port handling. They do not execute the media pipeline.

## Known integration limits — blockers before activation

- **Runway authentication is not wired.** `produce_video.py` sends an API version
  header but no bearer credential and does not read `RUNWAY_API_KEY`.
  `space_next/runway_tasks.py` assumes runtime-proxy authentication and invokes
  `curl`, which the Dockerfile does not install. That sandbox helper is not a
  portable Railway integration. No sandbox-only executable was found in the two
  main pipeline scripts: their executable dependencies are Python, ffmpeg and
  ffprobe; the external authentication/connector assumptions are the gap.
- **Narration is not generated automatically.** `daily_pipeline.py` requires an
  existing WAV or stops with code `2`; installed `gTTS`/`edge-tts` packages are not
  a wired TTS provider. Legacy fallback can select pilot narration for unrelated
  content. Example clips/narration/captions are not bundled in this deployment.
- **Whisper is not offline on first use.** Caption generation may download a model.
  Validate capacity, model storage, licensing and budgets separately. Runtime
  requirements retain broad minimum versions; this patch is not a dependency
  lock, security audit or reproducible-build guarantee.
- **No implemented uploads or tracking sync.** Drive, YouTube and Notion routines
  prepare local payloads rather than perform authenticated operations. Agent
  connectors do not automatically transfer into a standalone Railway container.
  A YouTube API key alone cannot upload: insert operations need OAuth authorization
  for the correct account ([YouTube API authentication requirements](https://developers.google.com/youtube/v3/docs),
  [OAuth guide](https://developers.google.com/youtube/v3/guides/authentication)).
  `daily_pipeline.py --upload` is not a supported argument.
- **Required approvals are not implemented.** The prototype does not enforce
  evidence, history, rights, budget, originality, disclosure/audience settings,
  exact-package approval or release review. Its legacy payload instructions say
  `privacyStatus='public'`; those instructions are not authorization and must not
  be acted on. Keep `final_publish_allowed=false`; production authorization and
  publication approval are separate. Required policy files must be synced/read
  before future channel work; a local CSV is not canonical Notion CONTENT_PIPELINE.
- **Active API needs further engineering.** Client-supplied config/content paths
  are not restricted to a safe directory; synchronous subprocesses can block
  requests, jobs are volatile, timeouts/concurrency/rate limits are incomplete,
  and local files are not durable without storage configuration. The content-ID
  path can run the daily renderer and then render again. No success response
  proves editorial QA, completed provider work, remote visibility, or publication.
- **The switch guards HTTP production only.** Direct CLI execution, shell access
  and alternative entrypoints bypass it. Do not enable cron or run pipeline CLI
  commands. Resolve these blockers, implement fail-closed approval controls, and
  obtain explicit authorization before changing `PIPELINE_ENABLED` to `true`.

## Cliplytics import

Cliplytics is a separate local scraper/remix tool. This repo does not clone it. To turn its `results/*.json` or `tiktok_ready/<slug>.json` files into `CONTENT.csv` rows (`CLX-*`, status `Needs research`):

```bat
python import_cliplytics.py --cliplytics-dir "C:\Users\Mauri\Documents\Python Projects\Cliplytics"
python import_cliplytics.py --input "C:\Users\Mauri\Documents\Python Projects\Cliplytics\tiktok_ready\example.json" --write-config --dry-run
```

See [docs/CLIPLYTICS_BRIDGE.md](docs/CLIPLYTICS_BRIDGE.md) for field mapping, schemas, and duplicate handling. Imported claims stay cited as Cliplytics/viral source text and still need independent research before production.

## Project Structure

```
somehow-true-pipeline/
├── app.py                  # FastAPI server (Railway entry point)
├── import_cliplytics.py     # Cliplytics JSON → CONTENT.csv (CLX-* rows)
├── produce_video.py         # Unified pipeline: Runway + captions + assembly + QA
├── daily_pipeline.py        # Content selection + scene prompt generation
├── config.example.json      # Config template (FCT-011 Baarle)
├── CONTENT.csv              # 20-row content queue (5 with scripts)
├── docs/
│   └── CLIPLYTICS_BRIDGE.md  # Cliplytics import usage and schemas
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
