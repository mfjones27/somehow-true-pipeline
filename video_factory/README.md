# Local Video Factory

A working **local-only prototype**, not an integrated content operation or a publishing system.
It takes an explicit manifest plus pre-existing narration and renders original Pillow
motion graphics through `/usr/bin/ffmpeg`. No external accounts, media services, network
assets, downloaded footage, AI generation, or paid tools are used by the renderer.

## What it does

- 1080 × 1920, 30 fps H.264 (`yuv420p`) MP4 with 48 kHz AAC audio.
- 25–60 second videos; default template is 45 seconds.
- Dark navy, lime, and white editorial graphics. Large scene titles, explicit timed
  captions, scene numbering, whole-video progress, and six original animated
  styles: `orbit`, `wave`, `network`, `pulse`, `nested-enclaves`, `border-house`.
- Titles and captions are constrained to the requested **x=100–900, y=200–1550**
  safe region. Long text is reflowed down to a minimum 64 px title / 44 px caption;
  text that still cannot fit is rejected instead of clipped.
- Local CLI, synchronous `POST /render`, `GET /health`, and `GET /jobs/{job_id}`.
- Persistent manifests, narration snapshots, encoder logs, a preview frame, technical
  metadata, and output per random job ID.
- Output status is **`rendered_needs_qa`**, never “ready to publish.” Technical checks
  cover stream format and duration, not editorial quality.

## Requirements and setup

Python 3.11+ on Linux, FFmpeg/ffprobe with `libx264` and AAC, and DejaVu Sans fonts.
Fixed local dependencies: `/usr/bin/ffmpeg`, `/usr/bin/ffprobe`,
`/usr/share/fonts/truetype/dejavu/DejaVuSans{,-Bold}.ttf`.

For a normal local environment (package installation requires access to your package
index, or previously downloaded wheels; **the application itself makes no network calls**):

```bash
cd /home/user/workspace/content_factory/video_factory
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e '.[test]'
python -m pytest -q -s
```

This sandbox already has the application dependencies under its default `python`,
and pytest under the system Python package directory. It was tested **without
installing or downloading anything** using this offline runner:

```bash
cd /home/user/workspace/content_factory/video_factory
python tools/run_tests_offline.py -q -s
```

The runner appends the existing system package directory *after* application
dependencies; do not prepend it with `PYTHONPATH` or dependency versions can conflict.

## Prepare a real pilot

1. Independently verify every claim and obtain script approval outside this prototype.
2. Obtain a narration recording you are authorized to use. This prototype does not
   synthesize speech. Use uncompressed **mono or stereo, 16/24/32-bit PCM WAV,
   22.05–96 kHz**, at most 64 MiB. Float WAV and compressed formats are not supported.
3. Put it under `assets/`, for example `assets/pilot/narration.wav`.
4. Copy `examples/pilot.template.json` to `pilot.json` and replace **every**
   placeholder. The template is not a factual script or usable finished video.
5. Set `duration` to the WAV duration (difference must be ≤0.05 s). Adjust scene
   boundaries to cover the whole duration. Add the actual narration transcript for
   each scene. Add accurately timed caption segments supplied by a human or a
   separate timing workflow.
6. Render and inspect the entire video and audio before any approval or publication.

```bash
cd /home/user/workspace/content_factory/video_factory
mkdir -p assets/pilot
# Copy your authorized PCM narration to assets/pilot/narration.wav.
cp examples/pilot.template.json pilot.json
# Edit pilot.json: all placeholder text and timing must be replaced.
python -m video_factory render pilot.json
```

The final output is `jobs/<random-job-id>/<output_name>` (default `final.mp4`).
Failures exit nonzero. No overwrite occurs; a `(content_id, script_version)` pair is
**single-attempt**, including failed attempts. Repeated submission returns HTTP 409
or a CLI error referencing the existing job. Fix the input and increment
`script_version` before retrying. Different versions get separate job directories.

### Manifest contract

See `examples/pilot.template.json` for the complete shape:

- `content_id`, `script_version`: 1–64 ASCII letters/digits/underscores/hyphens,
  beginning with a letter or digit.
- `duration`: finite number, 25–60 seconds.
- `narration_audio`: a **relative path under `assets/`**, lowercase `.wav`;
  paths, URLs, shell arguments, and roots cannot be supplied separately.
- `output_name`: a safe basename ending `.mp4`, never a path.
- `scenes`: 1–20 objects with `start`, `end`, `text`, `narration_transcript`,
  `visual_style`. Ordered, contiguous, begin at zero, end at duration.
- `captions`: 1–120 explicit `{start, end, text}` objects, ordered and nonoverlapping.
  Caption gaps are allowed and displayed as silence/no caption. The program does
  not determine whether those gaps match the audio.
- Every scene/caption lasts at least 0.1 s and is within the declared duration.
- Unknown fields, duplicate JSON keys, nonfinite numbers, string/bool timestamps,
  empty text, control characters, and unsupported style names are rejected.

Transcripts are stored for traceability. **No forced alignment, word-level timing,
speech recognition, transcript-to-audio verification, or transcript-to-caption
consistency check is performed.** Captions display exactly at the supplied times.
The graphics are conceptual, explicitly labeled abstract/not-to-scale, not measured
scientific diagrams or evidence. The current font/layout is designed for English and
Latin-script text; complex-script shaping and complete Unicode font coverage are
not promised. Audio is preserved without loudness normalization, music or ducking;
up to 0.05 s of boundary padding/trimming accommodates small duration differences.

### Schematic styles for a future Baarle draft

Set a scene's `visual_style` to either of the following; all other manifest fields,
25–60 second limits, explicit caption timing, and PCM WAV requirements are unchanged:

```json
{"visual_style": "nested-enclaves"}
```

- `nested-enclaves`: a large Dutch field, one Belgian rectangle inside it, and one
  smaller Dutch rectangle inside that. The labels are **Dutch / Belgian / Dutch**.
  Lime identifies Dutch areas; a distinct amber identifies Belgian areas. Staged
  underlines reveal the nesting order. The geometry is invented, not a factual map.
- `border-house`: one invented pitched-roof house straddles a dashed line, with
  side labels **Netherlands / Belgium**. Lime and amber distinguish the two fields;
  the fixed border dashes reveal top-to-bottom, not as a moving boundary.

Both display **SCHEMATIC NOT A MAP** under the graphic. Neither asserts geographic
accuracy, relative area, actual house layout, an address rule, or a count of enclaves.
They depict a relationship, not 22 geographic shapes. Do not treat them as a
count visualization; a count-based title needs a separately appropriate visual
and editorial review. All country names are direct labels, so meaning does not
depend on color alone.

The normal fixed header remains **THINGS THAT SOUND FAKE**; it does not say
"FACT CHECK" or imply verification. Only the explicit short technical-test path
shows **TECHNICAL TEST / SYNTHETIC AUDIO**. There is currently no manifest brand-label
override. A future factual draft still needs an independently verified approved
script/narration and full preview QA; these styles do not constitute approval.

## Run the API (loopback only)

```bash
cd /home/user/workspace/content_factory/video_factory
python -m video_factory serve --port 8765
```

In a second terminal:

```bash
curl --fail-with-body http://127.0.0.1:8765/health
curl --fail-with-body --max-time 660 \
  -H 'Content-Type: application/json' \
  --data-binary @pilot.json http://127.0.0.1:8765/render
curl --fail-with-body http://127.0.0.1:8765/jobs/REPLACE_WITH_JOB_ID
```

`POST /render` is synchronous: it returns 201 only after output passes technical
checks and the job is persisted. It can take several minutes; one render at a time.
There is **no queued/202 state** and no arbitrary job ID input. Polling a job is
primarily for inspecting persisted results or a known interrupted job; the ID is
not returned before a synchronous request completes. A disconnected client may
leave its accepted render running; inspect `jobs/` before retrying.

HTTP errors: 400 invalid JSON/audio, 403 nonlocal/browser-origin request, 404 unknown
job, 409 duplicate content/version, 413 large body, 415 non-JSON request, 422 invalid
manifest, 429 render busy, 500 encoding/storage failure, 507 local capacity limit.
Health means the local API responds; it is not a guarantee of available disk,
valid input, editorial approval, or a production-ready integration.

## Security and resource boundaries

- CLI server binds **only `127.0.0.1`**, uses one worker and disables proxy headers.
  Do not change the binding, reverse-proxy, tunnel, or expose it publicly.
- Middleware requires a loopback client and a local Host header and rejects
  browser Origin/fetch-site and forwarding headers. No CORS, browser UI, docs UI,
  public file serving, upload endpoint, or deployment is included.
- This is **not authenticated multi-user hosting** or a security sandbox against a
  malicious local user. Local processes can use the API. Trusted users must control
  the project root, runtime binaries, fonts, and job directory.
- Input assets are opened by directory-relative file descriptors with
  `O_NOFOLLOW`; symlinks, traversal, absolute paths, devices, FIFOs, and oversized
  files are rejected. Audio is copied to a private job snapshot and validated as
  uncompressed WAV before ffmpeg receives it.
- All subprocesses receive fixed argument lists, **never a shell**. Input format
  is forced; ffmpeg input protocols are limited to local files and the frame pipe.
  No manifest field can inject options, executables, filters, or output paths.
- Nonblocking cross-process file lock serializes API and CLI renders sharing the
  same root. Busy requests fail rather than queue. Encoding uses two threads,
  at most 1,800 frames, at most 600 s, and at most approximately 128 MiB output.
- Limits: 128 KiB request/CLI manifest, 64 MiB WAV, 100 retained jobs,
  2 GiB job storage with 256 MiB reserved per attempt, and 512 MiB free-disk minimum.
  These are prototype bounds, not OS-enforced quotas. Pillow keeps bounded scene
  backgrounds in memory. The supplied server limits simultaneous connections to 8.
- State writes are atomic. Stale `rendering` jobs become `failed` once queried or
  another render starts and the lock is unheld. A crash can leave partial files;
  these are not reported as successful. Encoder logs remain local.
- No automatic cleanup. Manually archive the **whole job directory** after inspecting
  it when limits are reached. Removing a job also removes its duplicate-key history.

## Tests and retained technical evidence

`pytest` validates timelines, finite numbers, safe paths, symlinks/FIFOs, duration
and size limits, malformed PCM, JSON duplicates, content/version duplicates,
cross-instance locking, stale-state recovery, API boundaries and errors.
The integration test renders **one 3-second, 90-frame clip with a synthetic
220 Hz tone** and verifies H.264/AAC, 1080×1920, 30 fps and duration using ffprobe.
It is visibly labeled **TECHNICAL TEST / SYNTHETIC AUDIO**. It is **not the user's
finished factual video**, contains no real narration, and proves technical
plumbing only—not full-length performance or editorial quality.

Tests retain evidence in `test_artifacts/<test-run-id>/`:

```text
assets/synthetic-tone.wav
jobs/<job-id>/technical-test.mp4
jobs/<job-id>/preview.png
jobs/<job-id>/manifest.json
jobs/<job-id>/job.json
jobs/<job-id>/ffmpeg.log
ffprobe.json
test_result.json
```

The bypass for the 25-second minimum is a deliberately explicit Python-only
`JobStore.render(data, allow_short_test=True)` testing argument. **There is no API
field, environment switch, or CLI flag for this bypass.**

## Intentionally not connected

No TTS integration; no AI images/video; no licensed-asset library; no factual/source
checks; no editorial or publishing approvals; no YouTube/TikTok/Instagram publishing;
no analytics; no Drive/Notion storage connection; no authentication, production
hosting, scheduler, distributed queue, arbitrary scene images, or public deployment.
There are no external-account authorizations. The user's next input is a verified,
approved pilot manifest and matching authorized narration. Publication remains
separate and approval-gated.
