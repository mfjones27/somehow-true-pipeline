"""Live remaining balances for the APIs this studio actually spends."""
from __future__ import annotations

import os
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import requests

from providers.env import load_env

load_env()

RUNWAY_LOW_CREDITS = 4000
ELEVEN_LOW_CHARS = 8000
CACHE_SECONDS = 45
_CACHE: dict[str, Any] = {"at": 0.0, "data": None}


def fetch_balances(*, force: bool = False) -> dict[str, Any]:
    now = time.time()
    if not force and _CACHE["data"] and now - _CACHE["at"] < CACHE_SECONDS:
        return _CACHE["data"]
    with ThreadPoolExecutor(max_workers=3) as pool:
        runway = pool.submit(_runway)
        eleven = pool.submit(_elevenlabs)
        openai = pool.submit(_openai)
        providers = [runway.result(), eleven.result(), openai.result()]
    warnings = [row["warning"] for row in providers if row.get("warning")]
    data = {
        "providers": providers,
        "warnings": warnings,
        "low": any(row.get("low") for row in providers),
    }
    _CACHE["at"] = now
    _CACHE["data"] = data
    return data


def _runway() -> dict[str, Any]:
    row = {
        "id": "runway",
        "label": "Runway",
        "unit": "credits",
        "remaining": None,
        "display": "not configured",
        "low": False,
        "warning": "",
        "ok": False,
    }
    key = os.environ.get("RUNWAY_API_KEY", "").strip()
    if not key:
        row["display"] = "missing API key"
        return row
    try:
        resp = requests.get(
            "https://api.dev.runwayml.com/v1/organization",
            headers={
                "Authorization": f"Bearer {key}",
                "X-Runway-Version": "2024-11-06",
            },
            timeout=8,
        )
        resp.raise_for_status()
        payload = resp.json() or {}
        if "creditBalance" not in payload:
            raise ValueError("Runway organization response had no creditBalance")
        remaining = int(payload.get("creditBalance") or 0)
        row.update(
            remaining=remaining,
            display=f"{remaining:,} credits",
            ok=True,
            low=remaining < RUNWAY_LOW_CREDITS,
        )
        if row["low"]:
            row["warning"] = (
                f"Runway is low: {remaining:,} credits left "
                f"(a Seedance 1080p short can take ~3,000+)."
            )
    except Exception as exc:
        row["display"] = "could not read"
        row["warning"] = f"Runway balance check failed: {exc}"[:180]
    return row


def _elevenlabs() -> dict[str, Any]:
    row = {
        "id": "elevenlabs",
        "label": "ElevenLabs",
        "unit": "characters",
        "remaining": None,
        "display": "not configured",
        "low": False,
        "warning": "",
        "ok": False,
    }
    key = os.environ.get("ELEVENLABS_API_KEY", "").strip()
    if not key:
        row["display"] = "missing API key"
        return row
    try:
        resp = requests.get(
            "https://api.elevenlabs.io/v1/user/subscription",
            headers={"xi-api-key": key},
            timeout=8,
        )
        resp.raise_for_status()
        data = resp.json() or {}
        if "character_count" not in data and "character_limit" not in data:
            raise ValueError("ElevenLabs subscription response was missing character usage")
        used = int(data.get("character_count") or 0)
        limit = int(data.get("character_limit") or 0)
        remaining = max(0, limit - used)
        row.update(
            remaining=remaining,
            used=used,
            limit=limit,
            display=f"{remaining:,} characters",
            ok=True,
            low=remaining < ELEVEN_LOW_CHARS,
        )
        if row["low"]:
            row["warning"] = (
                f"ElevenLabs is low: {remaining:,} characters left this period."
            )
    except Exception as exc:
        row["display"] = "could not read"
        row["warning"] = f"ElevenLabs balance check failed: {exc}"[:180]
    return row


def _openai() -> dict[str, Any]:
    row = {
        "id": "openai",
        "label": "OpenAI",
        "unit": "usd",
        "remaining": None,
        "display": "not configured",
        "low": False,
        "warning": "",
        "ok": False,
    }
    key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not key:
        row["display"] = "missing API key"
        return row
    from providers.costs import summarize
    spent = float(summarize().get("by_provider", {}).get("openai", {}).get("usd") or 0)
    row["spent"] = spent
    row["display"] = f"${spent:.2f} logged here"
    row["ok"] = True
    row["hint"] = "OpenAI does not expose remaining prepaid credits on a normal API key."
    return row
