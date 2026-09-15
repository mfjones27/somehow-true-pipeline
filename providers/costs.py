"""Per-run API spend log. Runway is billed in credits at $0.01 each."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from providers.env import ROOT

LEDGER = ROOT / "pipeline_output" / "costs.jsonl"

RUNWAY_CREDITS_PER_SEC = {
    "gen4.5": 12,
    "gen4_turbo": 5,
    "seedance2_5": 68,
    "seedance2": 36,
}
RUNWAY_MIN_CREDITS = {"seedance2_5": 80}
USD_PER_RUNWAY_CREDIT = 0.01
OPENAI_USD_PER_M = {"input": 10.0, "output": 50.0}
ELEVENLABS_USD_PER_1K = 0.30


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def record(event: dict) -> dict:
    LEDGER.parent.mkdir(parents=True, exist_ok=True)
    event = {"at": _now(), **event}
    with LEDGER.open("a", encoding="utf-8") as f:
        f.write(json.dumps(event) + "\n")
    return event


def openai_usage(content_id: str, usage, model: str) -> dict:
    if usage is None:
        return record({"provider": "openai", "content_id": content_id, "model": model, "usd": 0})
    inp = int(getattr(usage, "input_tokens", 0) or 0)
    out = int(getattr(usage, "output_tokens", 0) or 0)
    usd = (inp / 1_000_000) * OPENAI_USD_PER_M["input"] + (out / 1_000_000) * OPENAI_USD_PER_M["output"]
    return record({
        "provider": "openai",
        "content_id": content_id,
        "model": model,
        "input_tokens": inp,
        "output_tokens": out,
        "usd": round(usd, 4),
    })


def elevenlabs_usage(content_id: str, chars: int, model: str) -> dict:
    usd = (chars / 1000) * ELEVENLABS_USD_PER_1K
    return record({
        "provider": "elevenlabs",
        "content_id": content_id,
        "model": model,
        "characters": chars,
        "usd": round(usd, 4),
    })


def _credits_from_estimate(estimated_cost, seconds: int, model: str) -> float:
    rate = RUNWAY_CREDITS_PER_SEC.get(model, 68)
    fallback = max(RUNWAY_MIN_CREDITS.get(model, 0), seconds * rate)
    if estimated_cost is None:
        return fallback
    if isinstance(estimated_cost, (int, float, str)):
        try:
            return float(estimated_cost)
        except ValueError:
            return fallback
    if isinstance(estimated_cost, dict):
        for key in ("credits", "estimatedCost", "cost", "amount"):
            if key in estimated_cost and estimated_cost[key] is not None:
                try:
                    return float(estimated_cost[key])
                except (TypeError, ValueError):
                    continue
    return fallback


def runway_clip(content_id: str, model: str, seconds: int, estimated_cost=None) -> dict:
    credits = _credits_from_estimate(estimated_cost, seconds, model)
    usd = float(credits) * USD_PER_RUNWAY_CREDIT
    return record({
        "provider": "runway",
        "content_id": content_id,
        "model": model,
        "seconds": seconds,
        "credits": credits,
        "usd": round(usd, 4),
    })


def summarize(content_id: str | None = None) -> dict:
    rows = []
    if LEDGER.exists():
        for line in LEDGER.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            if content_id and row.get("content_id") != content_id:
                continue
            rows.append(row)
    by_provider: dict[str, dict] = {}
    for row in rows:
        bucket = by_provider.setdefault(row["provider"], {"usd": 0.0, "credits": 0.0, "calls": 0})
        bucket["usd"] += float(row.get("usd") or 0)
        bucket["credits"] += float(row.get("credits") or 0)
        bucket["calls"] += 1
    total = {
        "content_id": content_id,
        "usd": round(sum(v["usd"] for v in by_provider.values()), 4),
        "runway_credits": round(by_provider.get("runway", {}).get("credits", 0), 2),
        "by_provider": {
            name: {
                "usd": round(val["usd"], 4),
                "credits": round(val["credits"], 2),
                "calls": val["calls"],
            }
            for name, val in by_provider.items()
        },
    }
    return total


def print_summary(content_id: str | None = None) -> dict:
    total = summarize(content_id)
    print("\nAPI SPEND")
    for name, val in total["by_provider"].items():
        extra = f", {val['credits']} credits" if val["credits"] else ""
        print(f"  {name}: ${val['usd']:.4f}{extra} ({val['calls']} calls)")
    print(f"  total: ${total['usd']:.4f}  runway credits: {total['runway_credits']}")
    return total
