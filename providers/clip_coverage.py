"""Plan Runway scene lengths so clips cover the full narration."""
from __future__ import annotations

import math

from providers.runway import (
    RUNWAY_MAX_DURATION,
    RUNWAY_MIN_DURATION,
    clip_prompt,
)

COVERAGE_SLACK_SECONDS = 0.25
HOLD_SUFFIX = (
    " Continue the same locked-off shot with the same subject, lighting, and camera; "
    "no new objects, no text, no logos, no faces. Almost still, slow drift only."
)


def hold_prompt(prompt: str) -> str:
    base = " ".join((prompt or "").split()).rstrip(".")
    if not base:
        raise RuntimeError("Cannot build a fill clip without a scene prompt")
    return clip_prompt(f"{base}.{HOLD_SUFFIX}")


def fill_clip_durations(gap: float) -> list[int]:
    """Integer Runway lengths that cover a remaining gap."""
    if gap <= 0:
        return []
    remaining = math.ceil(gap - 1e-9)
    chunks: list[int] = []
    while remaining > 0:
        if remaining > RUNWAY_MAX_DURATION:
            chunks.append(RUNWAY_MAX_DURATION)
            remaining -= RUNWAY_MAX_DURATION
        else:
            chunks.append(max(RUNWAY_MIN_DURATION, remaining))
            remaining = 0
    return chunks


def plan_scene_coverage(
    prompts: list[str],
    durations: list[int],
    needed_seconds: float,
) -> tuple[list[str], list[int]]:
    """Grow existing scenes toward max length, then append hold clips until coverage is enough."""
    prompts = [clip_prompt(str(p).strip()) for p in prompts if str(p).strip()]
    durations = [int(d) for d in durations]
    if not prompts:
        raise RuntimeError("No scene prompts to cover narration")
    if len(durations) < len(prompts):
        durations = (durations + [5] * len(prompts))[: len(prompts)]
    else:
        durations = durations[: len(prompts)]
    durations = [
        max(RUNWAY_MIN_DURATION, min(RUNWAY_MAX_DURATION, d)) for d in durations
    ]

    for i in range(len(durations) - 1, -1, -1):
        shortfall = needed_seconds - sum(durations)
        if shortfall <= COVERAGE_SLACK_SECONDS:
            break
        room = RUNWAY_MAX_DURATION - durations[i]
        if room <= 0:
            continue
        durations[i] += min(room, max(1, math.ceil(shortfall)))

    gap = needed_seconds - sum(durations)
    if gap > COVERAGE_SLACK_SECONDS:
        last = prompts[-1]
        for extra in fill_clip_durations(gap):
            prompts.append(hold_prompt(last))
            durations.append(extra)
    return prompts, durations
