# Cliplytics → Somehow True bridge

Cliplytics (a separate local project) scrapes viral TikTok/YouTube finance clips and writes analysis plus remix scripts. This repo’s pipeline still starts from `CONTENT.csv` and `produce_video.py --config`. Nothing in Cliplytics is cloned here; this importer only **reads** its JSON and appends review-queue rows.

Default Cliplytics root on the machine that owns both projects:

```
C:\Users\Mauri\Documents\Python Projects\Cliplytics
```

## What gets imported

| Cliplytics artifact | Path | Used as |
| --- | --- | --- |
| VideoResult array (or single object) | `results/*.json` | topic/hook/core_fact from analysis + caption; script only if the JSON already has hook/beats/cta |
| Script sidecar | `tiktok_ready/<slug>.json` | preferred: topic, spoken script (hook + beats + CTA), b-roll queries |
| Remix markdown | `results/remix_*.md` | ignored (JSON only) |

`--source auto` (default) keeps a `tiktok_ready` sidecar when the same source URL / Cliplytics id also appears in `results/`. Use `--source results` or `--source tiktok_ready` to force one layout.

## Field mapping

Somehow True `CONTENT.csv` columns are unchanged. Viral text is copied, not rewritten into new factual claims.

| CONTENT.csv | Cliplytics source |
| --- | --- |
| `id` | New `CLX-001`, `CLX-002`, … (does not consume `FCT-*` from `daily_pipeline.next_content_id`) |
| `topic` | `script.topic`, else `analysis.summary`, else caption |
| `category` | first `analysis.topics` item; else `finance` when hashtags/caption look financial; else `viral_import` |
| `hook` | `script.hook.text`, else first caption line |
| `core_fact` | Cliplytics summary + key takeaways + **source URL / Cliplytics id**, labelled unverified |
| `script` | hook + beats + CTA texts when present; otherwise empty so `daily_pipeline` can script later |
| `fingerprint` | SHA-256 of the canonical source URL, or `cliplytics:<id>` when there is no URL |
| `status` | `Needs research` (same safe queue status as `enqueue_idea`) |
| `fact_check_verdict` | `Needs review` |

Duplicates are skipped when fingerprint, source URL, or `Cliplytics id:` already exists in `CONTENT.csv`.

## Usage (Windows)

From this repo, with Python on `PATH`:

```bat
python import_cliplytics.py --help

rem Dry-run the default Cliplytics folder (tiktok_ready first, then leftover results)
python import_cliplytics.py --dry-run

rem Import from the Cliplytics root
python import_cliplytics.py --cliplytics-dir "C:\Users\Mauri\Documents\Python Projects\Cliplytics"

rem Only results JSON, cap at 5 new rows
python import_cliplytics.py --cliplytics-dir "C:\Users\Mauri\Documents\Python Projects\Cliplytics" --source results --limit 5

rem One sidecar + a produce_video draft config
python import_cliplytics.py --input "C:\Users\Mauri\Documents\Python Projects\Cliplytics\tiktok_ready\compound-interest-trap.json" --write-config

rem A whole results folder
python import_cliplytics.py --input "C:\Users\Mauri\Documents\Python Projects\Cliplytics\results" --source results --dry-run
```

`--write-config` writes `pipeline_output/imports/<CLX-id>/config.json` in the same shape as `config.example.json` / `daily_pipeline.generate_config`. `narration_path` is left empty: run research + TTS (or `daily_pipeline.py --content CLX-001`) before `produce_video.py --config ...`. Imported rows are **not** auto-produced.

## Studio one-click

On the Idea tab, **Make video from Cliplytics** imports the next unused topic (highest-engagement `tiktok_ready` sidecar first) and starts `daily_pipeline.py --content CLX-…`. Astra writes a sourced script; the viral remix is kept in `core_fact` as unverified context, not as narration.

**Queue topic only** imports the same row without producing.

The UI reads `CLIPLYTICS_DIR` when set, otherwise:

```
C:\Users\Mauri\Documents\Python Projects\Cliplytics
```

## Expected Cliplytics JSON

`results/*.json` — array of VideoResult objects:

```json
{
  "id": "...",
  "url": "https://www.tiktok.com/@.../video/...",
  "platform": "tiktok",
  "metadata": {
    "id": "...",
    "platform": "tiktok",
    "url": "...",
    "author": "...",
    "caption": "...",
    "hashtags": ["..."],
    "likes": 0,
    "views": 0,
    "comments": 0,
    "shares": 0,
    "duration_s": 0.0,
    "posted_at": "..."
  },
  "video_path": "...",
  "transcript": "...",
  "analysis": {
    "summary": "...",
    "topics": [],
    "sentiment": "...",
    "key_takeaways": [],
    "target_audience": "...",
    "virality_factors": []
  },
  "script": {},
  "error": null
}
```

`tiktok_ready/<slug>.json`:

```json
{
  "slug": "...",
  "source_reference": { "id": "...", "url": "...", "author": "...", "views": 0, "likes": 0 },
  "script": {
    "topic": "...",
    "hook": { "text": "...", "broll_query": "..." },
    "beats": [{ "text": "...", "broll_query": "..." }],
    "cta": { "text": "...", "broll_query": "..." },
    "tiktok_caption": "...",
    "hashtags": ["..."]
  },
  "voiceover": { "voice": "...", "duration_s": 0 },
  "created_at": "..."
}
```

Rows with a non-null `error`, no source URL/id, or no usable topic/hook/caption/summary are skipped.

## Tests

```bat
python -m unittest tests.test_cliplytics_bridge
```

Fixtures live under `tests/fixtures/cliplytics/` and do not hit the network.
