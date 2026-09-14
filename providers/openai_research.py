"""GPT-6 Astra research via the OpenAI Responses API with web search."""
from __future__ import annotations

import json
import os
import re
from typing import Any

from openai import OpenAI

from providers.costs import openai_usage
from providers.env import load_env

load_env()

MODEL = os.environ.get("OPENAI_MODEL", "gpt-6-astra")

SCENE_PROMPT = (
    "Portrait 9:16 cinematic AI illustration, no text, logos, watermarks, or real faces. "
    "Keep the lower third visually calm for captions. Warm film grade, 35mm, shallow depth of field."
)

RESEARCH_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "hook": {"type": "string"},
        "core_fact": {"type": "string"},
        "script": {"type": "string"},
        "description": {"type": "string"},
        "tags": {"type": "array", "items": {"type": "string"}},
        "sources": {"type": "array", "items": {"type": "string"}},
        "scene_prompts": {"type": "array", "items": {"type": "string"}},
        "scene_durations": {"type": "array", "items": {"type": "integer"}},
    },
    "required": [
        "hook", "core_fact", "script", "description", "tags",
        "sources", "scene_prompts", "scene_durations",
    ],
}

SYSTEM = f"""You research one Somehow True YouTube Short built to stop the scroll.

Hunt for the most interesting TRUE cut of the topic, not the Wikipedia lede.
Prefer: a specific number, a nested paradox, a scale shock, an official record,
the only-known case, or a qualifier that makes the viral version even stranger.
Discard anything that only works by lying through omission. Primary sources only.

Script rules:
- Sentence one is the fact that should not be true. No preamble. No "did you know".
- Present tense, spoken out loud, 90 to 140 words for a full short.
- One concrete number early. The mechanism or cause is the rewind beat.
- End on the image, not a lesson. No jokes about the viewer. No on-screen directions.
- If a popular version of the claim is overstated, the qualification is the twist.

Hook is the YouTube title: one sentence, under 100 characters, the line someone would text a friend.
core_fact is the sourced brief with URLs in parentheses.
description is the YouTube description with a Sources section and this closer:
Somehow True: facts that sound made up, checked before we tell them.
Visuals are AI-generated illustrations. Narration is synthetic. Music is original computer-generated.
scene_prompts are Runway Gen-4.5 text-to-video prompts, one per shot. Each prompt must include:
{SCENE_PROMPT}
Make each shot one unforgettable image that matches that narration beat. No stock-footage language.
scene_durations are integers from 2 to 10 seconds and must match scene_prompts.
Return only the JSON object."""


def _client() -> OpenAI:
    key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not key:
        raise RuntimeError("OPENAI_API_KEY is missing")
    return OpenAI(api_key=key)


def _parse_json(text: str) -> dict[str, Any]:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    return json.loads(text)


def _normalize(data: dict[str, Any], scene_count: int, short: bool = False) -> dict[str, Any]:
    data["tags"] = [str(t) for t in data.get("tags", [])][:10]
    data["sources"] = [str(s) for s in data.get("sources", []) if str(s).startswith("http")][:8]
    prompts = [str(p).strip()[:950] for p in data.get("scene_prompts", []) if str(p).strip()]
    durations = [int(d) for d in data.get("scene_durations", []) if 2 <= int(d) <= 10]
    if len(prompts) < scene_count:
        raise RuntimeError(f"Astra returned {len(prompts)} scene prompts, need {scene_count}")
    data["scene_prompts"] = prompts[:scene_count]
    if short:
        durations = [5] * scene_count
    elif len(durations) < len(data["scene_prompts"]):
        durations = (durations + [5] * scene_count)[:scene_count]
    data["scene_durations"] = durations[: len(data["scene_prompts"])]
    if not data.get("script", "").strip():
        raise RuntimeError("Astra returned an empty script")
    from providers.youtube_upload import youtube_title
    data["hook"] = youtube_title(str(data.get("hook", "")).strip())
    return data


ANGLE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "topic": {"type": "string"},
        "hook": {"type": "string"},
        "category": {"type": "string"},
        "angle": {"type": "string"},
        "core_fact": {"type": "string"},
    },
    "required": ["topic", "hook", "category", "angle", "core_fact"],
}


def hunt_viral_idea(seed: str = "", *, avoid: list[str] | None = None) -> dict[str, Any]:
    """Find the most scroll-stopping true fact in a neighborhood, or pick one from scratch."""
    avoid = [a.strip() for a in (avoid or []) if a.strip()]
    prompt = (
        "Find one Somehow True short: a fact that sounds invented and is still true.\n"
        "Search until you have a primary source. Keep the most viral TRUE angle.\n"
        "topic is a one-line production assignment. hook is under 100 characters.\n"
        "category is one of: Geography, Animals, Space, Weird science, History, Engineering.\n"
        "angle explains why this cut stops the scroll. core_fact includes source URLs.\n"
    )
    if seed.strip():
        prompt += f"The human thought of: {seed.strip()}\nSharpen that into the wildest verified cut.\n"
    else:
        prompt += (
            "The human asked you to surprise them. Pick a new fact from geography, animals, "
            "space, or weird science that would make a stranger rewind a Short.\n"
        )
    if avoid:
        prompt += "Do not repeat these topics:\n- " + "\n- ".join(avoid[:24]) + "\n"
    client = _client()
    response = client.responses.create(
        model=MODEL,
        tools=[{"type": "web_search"}],
        tool_choice="required",
        instructions=SYSTEM,
        input=prompt,
        text={
            "format": {
                "type": "json_schema",
                "name": "somehow_true_angle",
                "strict": True,
                "schema": ANGLE_SCHEMA,
            }
        },
    )
    openai_usage("hunt", response.usage, MODEL)
    data = _parse_json(response.output_text)
    from providers.youtube_upload import youtube_title
    data["hook"] = youtube_title(str(data.get("hook", "")).strip())
    data["topic"] = str(data.get("topic", "")).strip()
    data["category"] = str(data.get("category", "Idea")).strip() or "Idea"
    data["angle"] = str(data.get("angle", "")).strip()
    data["core_fact"] = str(data.get("core_fact", "")).strip()
    if not data["topic"]:
        raise RuntimeError("Astra did not return a topic")
    return data


def research_topic(topic: str, core_fact: str = "", *, short: bool = False) -> dict[str, Any]:
    """Research one topic. short=True is a cheap 2-shot smoke, not a full short."""
    scene_count = 2 if short else 6
    words = "22 to 28" if short else "90 to 140"
    prompt = (
        f"Topic: {topic}\n"
        f"Write a {words} word narration and exactly {scene_count} Runway scene prompts.\n"
        "Open on the detail that would make someone stop scrolling. Verify it.\n"
    )
    if short:
        prompt += "Each scene duration must be 5 seconds so the video is 10 seconds total.\n"
    if core_fact.strip():
        prompt += f"Existing notes (verify, do not invent past these):\n{core_fact}\n"
    client = _client()
    response = client.responses.create(
        model=MODEL,
        tools=[{"type": "web_search"}],
        tool_choice="required",
        instructions=SYSTEM,
        input=prompt,
        text={
            "format": {
                "type": "json_schema",
                "name": "somehow_true_research",
                "strict": True,
                "schema": RESEARCH_SCHEMA,
            }
        },
    )
    openai_usage("research", response.usage, MODEL)
    return _normalize(_parse_json(response.output_text), scene_count, short=short)


PROMPT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "scene_prompts": {"type": "array", "items": {"type": "string"}},
        "scene_durations": {"type": "array", "items": {"type": "integer"}},
    },
    "required": ["scene_prompts", "scene_durations"],
}


def runway_prompts_for_script(script: str, topic: str = "", content_id: str = "research") -> dict[str, Any]:
    """Astra writes Runway prompts only. No web search. Script is already approved."""
    durations = [5, 8, 8, 8, 8, 8]
    client = _client()
    response = client.responses.create(
        model=MODEL,
        instructions=(
            "Write exactly 6 Runway Gen-4.5 text-to-video prompts that match this narration. "
            f"{SCENE_PROMPT} No documentary stock-footage language. "
            "scene_durations must be 5,8,8,8,8,8."
        ),
        input=f"Topic: {topic}\nNarration:\n{script}\n",
        text={
            "format": {
                "type": "json_schema",
                "name": "runway_prompts",
                "strict": True,
                "schema": PROMPT_SCHEMA,
            }
        },
    )
    openai_usage(content_id, response.usage, MODEL)
    data = _parse_json(response.output_text)
    prompts = [str(p).strip()[:950] for p in data.get("scene_prompts", []) if str(p).strip()]
    if len(prompts) < 6:
        raise RuntimeError(f"Astra returned {len(prompts)} scene prompts, need 6")
    return {
        "scene_prompts": prompts[:6],
        "scene_durations": durations,
    }
