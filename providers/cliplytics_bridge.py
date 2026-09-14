"""Map Cliplytics remix/result JSON into Somehow True CONTENT.csv rows.

Cliplytics is a separate local producer. This module only reads its JSON
artifacts — it does not clone or invoke Cliplytics.

Expected Cliplytics layouts (defaults for the Windows machine that owns both
projects):

  C:\\Users\\Mauri\\Documents\\Python Projects\\Cliplytics\\
    results/*.json          array (or single object) of VideoResult
    tiktok_ready/<slug>.json generated script sidecar

Viral imports are labelled as Cliplytics-sourced and are not treated as
independently verified facts. Do not invent claims beyond what the JSON
already contains.
"""
from __future__ import annotations

import csv
import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlparse, urlunparse

CONTENT_COLUMNS = [
    "id",
    "topic",
    "category",
    "fingerprint",
    "hook",
    "core_fact",
    "script",
    "script_version",
    "editorial_score",
    "status",
    "fact_check_verdict",
    "production_approval",
    "publication_approval",
    "video_uri",
    "video_sha256",
    "duration_seconds",
    "created_at",
    "updated_at",
]

DEFAULT_CLIPLYTICS_DIR = Path(r"C:\Users\Mauri\Documents\Python Projects\Cliplytics")
ID_PREFIX = "CLX"
IMPORT_STATUS = "Needs research"
FACT_CHECK_VERDICT = "Needs review"
DEFAULT_CATEGORY = "viral_import"
TOPIC_MAX = 120
HOOK_MAX = 280
FINANCE_HINTS = (
    "finance",
    "money",
    "investing",
    "investor",
    "stock",
    "stocks",
    "crypto",
    "bitcoin",
    "trading",
    "budget",
    "wealth",
    "401k",
    "etf",
    "nasdaq",
    "wallstreet",
    "wall street",
    "interest",
    "savings",
    "debt",
    "credit",
    "inflation",
)
SCENE_DURATIONS = [5, 8, 8, 8, 8, 8]
BRAND = "SOMEHOW TRUE"
YOUTUBE_CHANNEL_ID = "UCZqmUx29Va8Zud78Fj_0Geg"
CLIPLYTICS_ID_RE = re.compile(r"^Cliplytics id:\s*(.+)\s*$", re.M)
SOURCE_URL_RE = re.compile(r"^Source URL:\s*(\S+)\s*$", re.M)

SKIP_ERROR = "error"
SKIP_EMPTY = "not viable"
SKIP_DUPLICATE = "duplicate"
SKIP_SCHEMA = "unrecognized schema"


@dataclass
class CliplyticsItem:
    source_kind: str
    source_path: Path
    cliplytics_id: str
    url: str = ""
    author: str = ""
    views: int | None = None
    likes: int | None = None
    caption: str = ""
    hashtags: list[str] = field(default_factory=list)
    topic: str = ""
    hook: str = ""
    hook_broll: str = ""
    beats: list[tuple[str, str]] = field(default_factory=list)
    cta: str = ""
    cta_broll: str = ""
    summary: str = ""
    key_takeaways: list[str] = field(default_factory=list)
    analysis_topics: list[str] = field(default_factory=list)
    duration_seconds: str = ""
    error: str | None = None

    @property
    def source_key(self) -> str:
        return canonical_source_key(self.url, self.cliplytics_id)

    @property
    def fingerprint(self) -> str:
        key = self.source_key
        if not key:
            return ""
        return hashlib.sha256(key.encode("utf-8")).hexdigest()


@dataclass
class SkipRecord:
    reason: str
    path: Path
    detail: str = ""


@dataclass
class ImportResult:
    imported: list[dict[str, str]]
    skipped: list[SkipRecord]
    configs: list[Path]
    dry_run: bool
    csv_path: Path


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def canonical_source_key(url: str, cliplytics_id: str = "") -> str:
    raw = (url or "").strip()
    if raw:
        parsed = urlparse(raw)
        if parsed.scheme and parsed.netloc:
            path = parsed.path.rstrip("/")
            return urlunparse(
                (parsed.scheme.lower(), parsed.netloc.lower(), path, "", parsed.query, "")
            )
        return raw.rstrip("/")
    cid = (cliplytics_id or "").strip()
    if cid:
        return f"cliplytics:{cid}"
    return ""


def _as_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return str(value)
    return ""


def _as_str_list(value: Any) -> list[str]:
    if not value:
        return []
    if isinstance(value, str):
        return [value.strip()] if value.strip() else []
    if isinstance(value, list):
        out = []
        for item in value:
            text = _as_text(item)
            if text:
                out.append(text)
        return out
    return []


def _text_and_broll(node: Any) -> tuple[str, str]:
    if node is None:
        return "", ""
    if isinstance(node, str):
        return node.strip(), ""
    if isinstance(node, dict):
        text = _as_text(node.get("text") or node.get("script") or node.get("caption"))
        broll = _as_text(node.get("broll_query") or node.get("broll") or node.get("visual"))
        return text, broll
    return "", ""


def _truncate(text: str, limit: int) -> str:
    text = re.sub(r"\s+", " ", (text or "").strip())
    if len(text) <= limit:
        return text
    cut = text[: limit + 1]
    if " " in cut:
        cut = cut.rsplit(" ", 1)[0]
    return cut.rstrip(".,;: ") 


def _first_line(text: str) -> str:
    for line in (text or "").splitlines():
        if line.strip():
            return line.strip()
    return ""


def _duration_field(value: Any) -> str:
    if value is None or value == "":
        return ""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return ""
    if number <= 0:
        return ""
    if number.is_integer():
        return str(int(number))
    return f"{number:.2f}".rstrip("0").rstrip(".")


def is_tiktok_ready(data: Any) -> bool:
    if not isinstance(data, dict):
        return False
    script = data.get("script")
    if not isinstance(script, dict):
        return False
    if data.get("slug") or data.get("source_reference"):
        return True
    return any(key in script for key in ("hook", "beats", "cta", "topic"))


def is_video_result(data: Any) -> bool:
    if not isinstance(data, dict):
        return False
    if data.get("error") and not (data.get("id") or data.get("url") or data.get("metadata")):
        return True
    if isinstance(data.get("metadata"), dict) or isinstance(data.get("analysis"), dict):
        return True
    return bool(data.get("platform") and (data.get("id") or data.get("url")))


def parse_tiktok_ready(data: dict[str, Any], path: Path) -> CliplyticsItem:
    source = data.get("source_reference") if isinstance(data.get("source_reference"), dict) else {}
    script = data.get("script") if isinstance(data.get("script"), dict) else {}
    voiceover = data.get("voiceover") if isinstance(data.get("voiceover"), dict) else {}
    hook, hook_broll = _text_and_broll(script.get("hook"))
    beats = [_text_and_broll(beat) for beat in (script.get("beats") or [])]
    beats = [(text, broll) for text, broll in beats if text or broll]
    cta, cta_broll = _text_and_broll(script.get("cta"))
    cliplytics_id = _as_text(source.get("id") or data.get("slug") or path.stem)
    return CliplyticsItem(
        source_kind="tiktok_ready",
        source_path=path,
        cliplytics_id=cliplytics_id,
        url=_as_text(source.get("url")),
        author=_as_text(source.get("author")),
        views=source.get("views") if isinstance(source.get("views"), (int, float)) else None,
        likes=source.get("likes") if isinstance(source.get("likes"), (int, float)) else None,
        caption=_as_text(script.get("tiktok_caption")),
        hashtags=_as_str_list(script.get("hashtags")),
        topic=_as_text(script.get("topic")),
        hook=hook,
        hook_broll=hook_broll,
        beats=beats,
        cta=cta,
        cta_broll=cta_broll,
        duration_seconds=_duration_field(voiceover.get("duration_s")),
    )


def parse_video_result(data: dict[str, Any], path: Path) -> CliplyticsItem:
    metadata = data.get("metadata") if isinstance(data.get("metadata"), dict) else {}
    analysis = data.get("analysis") if isinstance(data.get("analysis"), dict) else {}
    script = data.get("script") if isinstance(data.get("script"), dict) else {}
    hook, hook_broll = _text_and_broll(script.get("hook"))
    beats = [_text_and_broll(beat) for beat in (script.get("beats") or [])]
    beats = [(text, broll) for text, broll in beats if text or broll]
    cta, cta_broll = _text_and_broll(script.get("cta"))
    error = data.get("error")
    error_text = _as_text(error) if error else None
    cliplytics_id = _as_text(
        data.get("id") or metadata.get("id") or script.get("slug") or path.stem
    )
    hashtags = _as_str_list(script.get("hashtags")) or _as_str_list(metadata.get("hashtags"))
    duration_value = metadata.get("duration_s")
    voiceover = data.get("voiceover")
    if not duration_value and isinstance(voiceover, dict):
        duration_value = voiceover.get("duration_s")
    return CliplyticsItem(
        source_kind="results",
        source_path=path,
        cliplytics_id=cliplytics_id,
        url=_as_text(data.get("url") or metadata.get("url")),
        author=_as_text(metadata.get("author")),
        views=metadata.get("views") if isinstance(metadata.get("views"), (int, float)) else None,
        likes=metadata.get("likes") if isinstance(metadata.get("likes"), (int, float)) else None,
        caption=_as_text(metadata.get("caption") or script.get("tiktok_caption")),
        hashtags=hashtags,
        topic=_as_text(script.get("topic")),
        hook=hook,
        hook_broll=hook_broll,
        beats=beats,
        cta=cta,
        cta_broll=cta_broll,
        summary=_as_text(analysis.get("summary")),
        key_takeaways=_as_str_list(analysis.get("key_takeaways")),
        analysis_topics=_as_str_list(analysis.get("topics")),
        duration_seconds=_duration_field(duration_value),
        error=error_text,
    )


def parse_payload(data: Any, path: Path, source: str = "auto") -> list[CliplyticsItem]:
    if source == "tiktok_ready":
        if isinstance(data, dict) and is_tiktok_ready(data):
            return [parse_tiktok_ready(data, path)]
        return []
    if source == "results":
        rows = data if isinstance(data, list) else [data]
        items = []
        for row in rows:
            if isinstance(row, dict) and is_video_result(row):
                items.append(parse_video_result(row, path))
        return items
    if isinstance(data, list):
        items = []
        for row in data:
            if isinstance(row, dict) and is_video_result(row):
                items.append(parse_video_result(row, path))
            elif isinstance(row, dict) and is_tiktok_ready(row):
                items.append(parse_tiktok_ready(row, path))
        return items
    if isinstance(data, dict) and is_tiktok_ready(data):
        return [parse_tiktok_ready(data, path)]
    if isinstance(data, dict) and is_video_result(data):
        return [parse_video_result(data, path)]
    return []


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _json_files(directory: Path) -> list[Path]:
    if not directory.is_dir():
        return []
    files = []
    for path in sorted(directory.glob("*.json")):
        if path.name.startswith("remix_"):
            continue
        files.append(path)
    return files


def discover_paths(cliplytics_dir: Path | None, input_path: Path | None, source: str) -> list[tuple[Path, str]]:
    """Return (path, parse_source) pairs in import order."""
    if input_path is not None:
        path = input_path.expanduser()
        if path.is_file():
            kind = source if source != "auto" else "auto"
            return [(path, kind)]
        if path.is_dir():
            name = path.name.lower()
            if source == "auto":
                if name == "tiktok_ready":
                    return [(p, "tiktok_ready") for p in _json_files(path)]
                if name == "results":
                    return [(p, "results") for p in _json_files(path)]
            kind = source if source != "auto" else "auto"
            return [(p, kind) for p in _json_files(path)]
        raise FileNotFoundError(f"Input path not found: {path}")

    if cliplytics_dir is None:
        raise FileNotFoundError("Provide --cliplytics-dir or --input")

    root = cliplytics_dir.expanduser()
    if not root.exists():
        raise FileNotFoundError(f"Cliplytics directory not found: {root}")

    ready_dir = root / "tiktok_ready"
    results_dir = root / "results"
    ready = [(p, "tiktok_ready") for p in _json_files(ready_dir)]
    results = [(p, "results") for p in _json_files(results_dir)]

    if source == "tiktok_ready":
        return ready
    if source == "results":
        return results
    # auto: prefer sidecars, then results JSON that do not duplicate a sidecar
    return ready + results


def load_items(paths: Iterable[tuple[Path, str]]) -> tuple[list[CliplyticsItem], list[SkipRecord]]:
    items: list[CliplyticsItem] = []
    skipped: list[SkipRecord] = []
    for path, kind in paths:
        try:
            data = load_json(path)
        except (OSError, json.JSONDecodeError) as exc:
            skipped.append(SkipRecord(SKIP_SCHEMA, path, str(exc)))
            continue
        parsed = parse_payload(data, path, kind)
        if not parsed:
            skipped.append(SkipRecord(SKIP_SCHEMA, path, "no VideoResult or tiktok_ready sidecar"))
            continue
        items.extend(parsed)
    return items, skipped


def prefer_sidecars(items: list[CliplyticsItem]) -> tuple[list[CliplyticsItem], list[SkipRecord]]:
    """Keep tiktok_ready when the same source also appears in results JSON."""
    chosen: list[CliplyticsItem] = []
    skipped: list[SkipRecord] = []
    seen: dict[str, CliplyticsItem] = {}
    # Sidecars first so results lose the collision.
    ordered = sorted(items, key=lambda item: (0 if item.source_kind == "tiktok_ready" else 1, str(item.source_path)))
    for item in ordered:
        key = item.source_key
        if key and key in seen:
            skipped.append(
                SkipRecord(
                    SKIP_DUPLICATE,
                    item.source_path,
                    f"same source as {seen[key].source_path.name} ({key})",
                )
            )
            continue
        if key:
            seen[key] = item
        chosen.append(item)
    # Restore sidecar-then-results order without re-sorting filenames across kinds
    chosen.sort(key=lambda item: (0 if item.source_kind == "tiktok_ready" else 1, str(item.source_path)))
    return chosen, skipped


def item_is_viable(item: CliplyticsItem) -> str | None:
    if item.error:
        return f"{SKIP_ERROR}: {item.error}"
    if not item.source_key:
        return SKIP_EMPTY
    if not (item.topic or item.hook or item.caption or item.summary or item.beats or item.cta):
        return SKIP_EMPTY
    return None


def infer_category(item: CliplyticsItem) -> str:
    if item.analysis_topics:
        first = _truncate(item.analysis_topics[0], 80)
        if first:
            return first
    blob = " ".join(
        [item.topic, item.caption, item.summary, item.hook]
        + [tag.lstrip("#") for tag in item.hashtags]
    ).lower()
    if any(hint in blob for hint in FINANCE_HINTS):
        return "finance"
    return DEFAULT_CATEGORY


def infer_topic(item: CliplyticsItem) -> str:
    if item.topic:
        return _truncate(item.topic, TOPIC_MAX)
    if item.summary:
        return _truncate(item.summary, TOPIC_MAX)
    if item.caption:
        return _truncate(_first_line(item.caption), TOPIC_MAX)
    if item.hook:
        return _truncate(item.hook, TOPIC_MAX)
    return _truncate(item.cliplytics_id or item.source_path.stem, TOPIC_MAX)


def infer_hook(item: CliplyticsItem) -> str:
    if item.hook:
        return _truncate(item.hook, HOOK_MAX)
    if item.caption:
        return _truncate(_first_line(item.caption), HOOK_MAX)
    if item.summary:
        return _truncate(item.summary, HOOK_MAX)
    return _truncate(item.topic, HOOK_MAX)


def join_script(item: CliplyticsItem) -> str:
    parts: list[str] = []
    if item.hook:
        parts.append(item.hook)
    for text, _broll in item.beats:
        if text:
            parts.append(text)
    if item.cta:
        parts.append(item.cta)
    return "\n\n".join(parts)


def build_core_fact(item: CliplyticsItem) -> str:
    lines = [
        "Cliplytics viral import — text below is copied from Cliplytics analysis or the source video. It is not independently verified. Do not treat these as established facts.",
        f"Cliplytics id: {item.cliplytics_id}",
    ]
    if item.url:
        lines.append(f"Source URL: {item.url}")
    if item.author:
        lines.append(f"Author: {item.author}")
    stats = []
    if item.views is not None:
        stats.append(f"views={item.views}")
    if item.likes is not None:
        stats.append(f"likes={item.likes}")
    if stats:
        lines.append("Engagement (Cliplytics metadata): " + ", ".join(stats))
    lines.append(f"Import kind: {item.source_kind}")
    if item.summary:
        lines.extend(["", "Cliplytics analysis summary (unverified):", item.summary])
    if item.key_takeaways:
        lines.extend(["", "Key takeaways reported by Cliplytics (unverified):"])
        for takeaway in item.key_takeaways:
            lines.append(f"- {takeaway}")
    if item.caption and item.caption != item.summary:
        lines.extend(["", "Source caption (unverified):", item.caption])
    return "\n".join(lines).strip() + "\n"


def next_cliplytics_id(rows: Iterable[dict[str, str]], used: set[str] | None = None) -> str:
    nums: list[int] = []
    for row in rows:
        match = re.match(rf"{ID_PREFIX}-(\d+)$", row.get("id", ""))
        if match:
            nums.append(int(match.group(1)))
    if used:
        for cid in used:
            match = re.match(rf"{ID_PREFIX}-(\d+)$", cid)
            if match:
                nums.append(int(match.group(1)))
    return f"{ID_PREFIX}-{max(nums, default=0) + 1:03d}"


def empty_row() -> dict[str, str]:
    return {key: "" for key in CONTENT_COLUMNS}


def item_to_row(item: CliplyticsItem, content_id: str, now: str | None = None) -> dict[str, str]:
    stamp = now or utc_now()
    script = join_script(item)
    row = empty_row()
    row.update(
        {
            "id": content_id,
            "topic": infer_topic(item),
            "category": infer_category(item),
            "fingerprint": item.fingerprint,
            "hook": infer_hook(item),
            "core_fact": build_core_fact(item),
            "script": script,
            "script_version": "1" if script else "0",
            "editorial_score": "0",
            "status": IMPORT_STATUS,
            "fact_check_verdict": FACT_CHECK_VERDICT,
            "duration_seconds": item.duration_seconds,
            "created_at": stamp,
            "updated_at": stamp,
        }
    )
    return row


def index_existing(rows: Iterable[dict[str, str]]) -> tuple[set[str], set[str], set[str]]:
    fingerprints: set[str] = set()
    urls: set[str] = set()
    cliplytics_ids: set[str] = set()
    for row in rows:
        fp = (row.get("fingerprint") or "").strip()
        if fp:
            fingerprints.add(fp)
        core = row.get("core_fact") or ""
        for match in CLIPLYTICS_ID_RE.finditer(core):
            cliplytics_ids.add(match.group(1).strip())
        for match in SOURCE_URL_RE.finditer(core):
            urls.add(canonical_source_key(match.group(1)))
        for found in re.findall(r"https?://[^\s\)\]]+", core):
            urls.add(canonical_source_key(found))
    return fingerprints, urls, cliplytics_ids


def duplicate_reason(item: CliplyticsItem, fingerprints: set[str], urls: set[str], cliplytics_ids: set[str]) -> str | None:
    if item.fingerprint and item.fingerprint in fingerprints:
        return f"{SKIP_DUPLICATE}: fingerprint {item.fingerprint}"
    key = item.source_key
    if key and key in urls:
        return f"{SKIP_DUPLICATE}: source URL {item.url or key}"
    if item.cliplytics_id and item.cliplytics_id in cliplytics_ids:
        return f"{SKIP_DUPLICATE}: Cliplytics id {item.cliplytics_id}"
    return None


def load_content_rows(csv_path: Path) -> list[dict[str, str]]:
    if not csv_path.exists():
        return []
    with csv_path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        return [dict(row) for row in reader]


def save_content_rows(csv_path: Path, rows: list[dict[str, str]]) -> None:
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=CONTENT_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def cinematic_prompt(broll_query: str, segment_text: str = "") -> str:
    visual = (broll_query or "").strip() or (
        "cinematic abstract scene with rich textures and warm dramatic lighting"
    )
    evocation = f" The scene should evoke: {segment_text[:120]}." if segment_text.strip() else ""
    prompt = (
        f"Portrait 9:16 cinematic shot: {visual}.{evocation} "
        "Warm cinematic color grade, film grain, 35mm lens, shallow depth of field. "
        "No text, logos, watermarks, or on-screen graphics. "
        "Keep the lower third of the frame visually calm and uncluttered for caption overlay. "
        "AI-generated illustration, not documentary footage."
    )
    return prompt[:950]


def scene_prompts_for(item: CliplyticsItem, topic: str, script: str) -> list[str]:
    shots: list[tuple[str, str]] = []
    if item.hook or item.hook_broll:
        shots.append((item.hook_broll, item.hook))
    for text, broll in item.beats:
        shots.append((broll, text))
    if item.cta or item.cta_broll:
        shots.append((item.cta_broll, item.cta))
    shots = [(broll, text) for broll, text in shots if broll or text]
    if not shots:
        sentences = [part.strip() for part in re.split(r"(?<=[.!?])\s+", script.strip()) if part.strip()]
        if not sentences:
            sentences = [topic]
        for sentence in sentences[:6]:
            shots.append(("", sentence))
    if len(shots) > 6:
        shots = shots[:6]
    return [cinematic_prompt(broll, text) for broll, text in shots]


def config_title(hook: str, topic: str) -> str:
    title = re.sub(r"\s+", " ", (hook or topic or "").strip()).rstrip(".")
    if len(title) <= 100:
        return title
    words = title.split()
    kept: list[str] = []
    for word in words:
        trial = " ".join(kept + [word])
        if len(trial) > 100:
            break
        kept.append(word)
    return " ".join(kept).rstrip(".,;:")


def build_produce_config(row: dict[str, str], item: CliplyticsItem) -> dict[str, Any]:
    cid = row["id"]
    script = row.get("script") or ""
    topic = row.get("topic") or ""
    hook = row.get("hook") or topic
    sources = [item.url] if item.url else []
    tags = [tag.lstrip("#") for tag in item.hashtags if tag.strip()]
    tags.extend(["Somehow True", "Shorts", row.get("category") or DEFAULT_CATEGORY, "Cliplytics"])
    tags = list(dict.fromkeys(tag for tag in tags if tag))
    prompts = scene_prompts_for(item, topic, script)
    durations = SCENE_DURATIONS[: len(prompts)] or [5]
    if len(durations) < len(prompts):
        durations.extend([8] * (len(prompts) - len(durations)))
    description_lines = [
        hook,
        "",
        "Imported from Cliplytics as a viral-source draft. Claims are unverified.",
        "Somehow True: facts that sound made up, checked before we tell them.",
        "",
    ]
    if sources:
        description_lines.append("Sources:")
        description_lines.extend(sources)
        description_lines.append("")
    description_lines.append(
        "Visuals are AI-generated illustrations. Narration is synthetic. Music is original computer-generated."
    )
    description_lines.append("")
    description_lines.append("#Shorts #SomehowTrue #CliplyticsImport")
    return {
        "content_id": cid,
        "title": config_title(hook, topic),
        "description": "\n".join(description_lines),
        "tags": tags[:10],
        "script": script,
        "sources": sources,
        "clips_dir": None,
        "captions_dir": None,
        "intro_clip": None,
        "narration_path": None,
        "scene_prompts": prompts,
        "scene_durations": durations,
        "brand": BRAND,
        "output_name": f"somehow-true-{cid.lower()}.mp4",
        "youtube_channel_id": YOUTUBE_CHANNEL_ID,
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
        "cliplytics": {
            "id": item.cliplytics_id,
            "url": item.url,
            "kind": item.source_kind,
            "source_path": str(item.source_path),
        },
    }


def write_produce_config(row: dict[str, str], item: CliplyticsItem, imports_root: Path) -> Path:
    cid = row["id"]
    folder = imports_root / cid
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "config.json"
    path.write_text(json.dumps(build_produce_config(row, item), indent=2) + "\n", encoding="utf-8")
    return path


def import_items(
    items: list[CliplyticsItem],
    csv_path: Path,
    *,
    limit: int | None = None,
    dry_run: bool = False,
    write_config: bool = False,
    imports_root: Path | None = None,
    now: str | None = None,
) -> ImportResult:
    rows = load_content_rows(csv_path)
    fingerprints, urls, cliplytics_ids = index_existing(rows)
    skipped: list[SkipRecord] = []
    imported: list[dict[str, str]] = []
    configs: list[Path] = []
    stamp = now or utc_now()
    accepted = 0

    for item in items:
        reason = item_is_viable(item)
        if reason:
            skipped.append(SkipRecord(reason.split(":", 1)[0], item.source_path, reason))
            continue
        dup = duplicate_reason(item, fingerprints, urls, cliplytics_ids)
        if dup:
            skipped.append(SkipRecord(SKIP_DUPLICATE, item.source_path, dup))
            continue
        if limit is not None and accepted >= limit:
            skipped.append(SkipRecord("limit", item.source_path, f"beyond --limit {limit}"))
            continue
        content_id = next_cliplytics_id(rows + imported)
        row = item_to_row(item, content_id, stamp)
        imported.append(row)
        accepted += 1
        fingerprints.add(item.fingerprint)
        if item.source_key:
            urls.add(item.source_key)
        if item.cliplytics_id:
            cliplytics_ids.add(item.cliplytics_id)
        if write_config and not dry_run:
            if imports_root is None:
                raise ValueError("imports_root is required when write_config is true")
            configs.append(write_produce_config(row, item, imports_root))

    if imported and not dry_run:
        save_content_rows(csv_path, rows + imported)

    return ImportResult(
        imported=imported,
        skipped=skipped,
        configs=configs,
        dry_run=dry_run,
        csv_path=csv_path,
    )


def format_summary(result: ImportResult) -> str:
    lines = [
        "Cliplytics → Somehow True",
        f"  csv: {result.csv_path}",
        f"  dry-run: {'yes' if result.dry_run else 'no'}",
        f"  imported: {len(result.imported)}",
    ]
    for row in result.imported:
        lines.append(f"    {row['id']:<10} {row['topic'][:60]}")
    lines.append(f"  skipped: {len(result.skipped)}")
    for skip in result.skipped:
        detail = f" — {skip.detail}" if skip.detail else ""
        lines.append(f"    {skip.reason:<12} {skip.path.name}{detail}")
    if result.configs:
        lines.append("  configs:")
        for path in result.configs:
            lines.append(f"    {path}")
    elif result.imported and result.dry_run:
        lines.append("  configs: not written (dry-run)")
    return "\n".join(lines)
