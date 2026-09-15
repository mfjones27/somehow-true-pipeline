"""GPT-6 Astra research via the OpenAI Responses API with web search."""
from __future__ import annotations

import json
import os
import re
from typing import Any

from openai import OpenAI

from providers.costs import openai_usage
from providers.env import load_env
from providers.runway import (
    HARD_BANS,
    RUNWAY_MAX_DURATION,
    RUNWAY_MIN_DURATION,
    STYLE_LOCK,
    prepare_prompt,
    weak_prompts,
)

load_env()

MODEL = os.environ.get("OPENAI_MODEL", "gpt-6-astra")

SCENE_PROMPT = f"""You are directing Seedance 2.5 text-to-video clips for a 9:16 YouTube Short.

Each scene_prompt is one shot: a single dense paragraph, 800 to 2500 characters, that a camera can film without guessing.
Write it like a DP shot card, not a vibe. Include ALL of:
- Shot size and lens (e.g. 35mm medium close-up, macro, wide)
- Camera move and speed that lasts the full duration (dolly, pan, crane, locked-off, push-in)
- The exact subject, setting, era, materials, and weather for THIS narration beat
- One continuous action with a beginning, middle, and end inside the clip
- Lighting: source, direction, time of day, color, shadows
- Composition: subject in the upper two-thirds; bottom third empty for captions
- Style lock: {STYLE_LOCK}
- Hard bans: {HARD_BANS}

Map scene 1 to the hook sentence. Each later scene covers the next spoken beat. Invent specific visible details that illustrate the fact — do not quote the narration, do not write "evoking", do not write stock-footage language ("cinematic shot of a town").
If you cannot see it on a monitor, rewrite it."""

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

BANNED_TROPES = """
Already-burned Shorts clichés — do not assign these, even with a new coat of paint:
tardigrades in space, wombat cube poop, the immortal jellyfish, mantis shrimp punch,
Lake Baikal holding a fifth of Earth's fresh water as the whole video, Nintendo hanafuda,
Point Roberts as the only exclave story, Baarle enclaves, Voyager light-day,
the marshmallow test, bananas are berries, koala fingerprints, a day on Venus,
the pitch-drop experiment, "water bears", "scientists were baffled".
If a 14-year-old saw it on TikTok in 2020, it is dead.
"""

LANES = [
    "obscure borders, exclaves, and legal geography that still exist on a map",
    "an animal mechanism from a journal paper, named species, named number, named cause",
    "a dated space-mission milestone or instrument still sending data it should not",
    "an engineering object that should have failed, stopped, or been impossible to build",
    "a 2018–2026 paper with a measurement that sounds like a reporting error",
    "a bureaucratic or legal accident with a named place and a date",
    "an official record (USGS, NOAA, Guinness, UNESCO, NASA) whose qualifier is weirder than the headline",
    "history that is still running: a machine, a law, a border, a debt, a colony of something",
]

HUNT_SYSTEM = f"""You are the assignment editor for Somehow True, a YouTube channel of true facts that sound invented.

Your job is to find a fact a sharp adult would pause, rewind, and text to a friend.
Not a Wikipedia lede. Not zoo trivia. Not "did you know". The test is: would this get views
from people who already think they have seen every weird fact on the internet?

Hunt like a journalist. Primary sources only. Keep searching until you have a named instance,
a concrete number, and a mechanism or cause. "It's weird" is not an assignment.
Prefer 2018–2026 papers, named missions, named places, court records, official histories.
If the popular version is overstated, keep it only when the real version is still astonishing.

{BANNED_TROPES}

Formats:
- deep_dive (default): one topic, one named instance, one number, one rewindable cause.
- listicle (occasional): Top 5 preferred, Top 7 maximum. Never Top 10 in a 45-second short.
  Each item is a named specific with a number or date, not a category. Rank by "that cannot be real."
  The list needs a unifying weirdness, not a theme-park roundup of famous facts.

topic is a one-line production assignment. For a list, start with "Top 5 …".
hook is the YouTube title: under 100 characters, the line someone would text a friend.
category is one of: Geography, Animals, Space, Weird science, History, Engineering.
angle explains why this cut stops the scroll, in one or two sentences.
core_fact is the sourced brief with URLs in parentheses.
format is deep_dive or listicle.
Return only the JSON object."""

SYSTEM = f"""You research one Somehow True YouTube Short built to stop the scroll.

This is not a children's trivia channel. Write like the fact is a scandal that happens to be true.
Hunt the most interesting TRUE cut, not the Wikipedia lede. Prefer a specific number, a nested
paradox, a scale shock, an official record, the only-known case, or a qualifier that makes the
viral version even stranger. Discard anything that only works by lying through omission.
Primary sources only.

{BANNED_TROPES}

Deep-dive script rules:
- Sentence one is the fact that should not be true. No preamble. No "did you know".
- Present tense, spoken out loud, 90 to 140 words.
- One concrete number in the first two sentences. The mechanism or cause is the rewind beat.
- End on the image, not a lesson. No jokes about the viewer. No on-screen directions.
- The script is what the voice says. Never put URLs, markdown, DOIs, filenames, or source citations in it. Sources go in core_fact and description only.

Listicle script rules (only when the topic is a Top N list):
- 120 to 170 words. Top 5 unless the topic already says otherwise. Never pad to 10.
- Line one names the unifying impossibility. Then the items, each one sentence, each with a
  name and a number or date. Last line is the pattern that ties them, not a moral.
- No "number one will shock you". The ranking is by strangeness, spoken as facts.
- Same as deep dives: no URLs, markdown, or source citations in the spoken script.

Hook is the YouTube title: one sentence, under 100 characters, the line someone would text a friend.
core_fact is the sourced brief with URLs in parentheses.
description is the YouTube description with a Sources section and this closer:
Somehow True: facts that sound made up, checked before we tell them.
Visuals are AI-generated illustrations. Narration is synthetic. Music is original computer-generated.
scene_prompts are Seedance 2.5 text-to-video prompts, one per shot.
{SCENE_PROMPT}
scene_durations are integers from {RUNWAY_MIN_DURATION} to {RUNWAY_MAX_DURATION} seconds and must match scene_prompts.
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
    prompts = [prepare_prompt(str(p)) for p in data.get("scene_prompts", []) if str(p).strip()]
    durations = [
        int(d) for d in data.get("scene_durations", [])
        if RUNWAY_MIN_DURATION <= int(d) <= RUNWAY_MAX_DURATION
    ]
    if len(prompts) < scene_count:
        raise RuntimeError(f"Astra returned {len(prompts)} scene prompts, need {scene_count}")
    data["scene_prompts"] = prompts[:scene_count]
    if short:
        durations = [5] * scene_count
    elif len(durations) < len(data["scene_prompts"]):
        durations = (durations + [5] * scene_count)[:scene_count]
    data["scene_durations"] = durations[: len(data["scene_prompts"])]
    from providers.elevenlabs_tts import spoken_script
    data["script"] = spoken_script(str(data.get("script", "")))
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
        "format": {"type": "string"},
        "angle": {"type": "string"},
        "core_fact": {"type": "string"},
    },
    "required": ["topic", "hook", "category", "format", "angle", "core_fact"],
}

LISTICLE_RE = re.compile(r"\b(top\s*\d+|listicle|list of)\b", re.I)


def detect_format(topic: str = "", hook: str = "", seed: str = "") -> str:
    blob = f"{topic} {hook} {seed}"
    return "listicle" if LISTICLE_RE.search(blob) else "deep_dive"


def hunt_viral_idea(
    seed: str = "",
    *,
    avoid: list[str] | None = None,
    queue_size: int = 0,
) -> dict[str, Any]:
    """Find the most scroll-stopping true fact in a neighborhood, or pick one from scratch."""
    seed = seed.strip()
    avoid = [a.strip() for a in (avoid or []) if a.strip()]
    fmt = detect_format(seed=seed)
    if not seed:
        fmt = "listicle" if queue_size % 5 == 4 else "deep_dive"
    lane = LANES[queue_size % len(LANES)]
    prompt = (
        f"Lane for this assignment: {lane}\n"
        f"Required format: {fmt}\n"
        "Search until you have a primary source. Keep the most viral TRUE angle.\n"
        "If the first hit is a famous fact, keep searching. Famous is not the same as good.\n"
    )
    if seed:
        prompt += f"The human thought of: {seed}\nSharpen that into the wildest verified cut. Stay in format {fmt}.\n"
    else:
        prompt += (
            "The human asked you to surprise them. Find something they have not seen.\n"
            "Pull your weight. This video has to earn views.\n"
        )
        if fmt == "listicle":
            prompt += "Make it a Top 5 of named, sourced impossibilities with one spine holding them together.\n"
        else:
            prompt += "Go deep on ONE named instance. The mechanism is the video.\n"
    if avoid:
        prompt += "Do not repeat these topics or hooks:\n- " + "\n- ".join(avoid[:40]) + "\n"
    client = _client()
    response = client.responses.create(
        model=MODEL,
        tools=[{"type": "web_search"}],
        tool_choice="required",
        instructions=HUNT_SYSTEM,
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
    data["format"] = "listicle" if str(data.get("format", fmt)).strip().lower() == "listicle" else "deep_dive"
    data["angle"] = str(data.get("angle", "")).strip()
    data["core_fact"] = str(data.get("core_fact", "")).strip()
    if not data["topic"]:
        raise RuntimeError("Astra did not return a topic")
    if data["format"] == "listicle" and not LISTICLE_RE.search(data["topic"]):
        rest = data["topic"][:1].lower() + data["topic"][1:] if data["topic"] else data["topic"]
        data["topic"] = f"Top 5 {rest}"
    return data


def research_topic(topic: str, core_fact: str = "", *, short: bool = False, format: str = "") -> dict[str, Any]:
    """Research one topic. short=True is a cheap 2-shot smoke, not a full short."""
    scene_count = 2 if short else 6
    fmt = format or detect_format(topic)
    if short:
        words = "22 to 28"
    elif fmt == "listicle":
        words = "120 to 170"
    else:
        words = "90 to 140"
    prompt = (
        f"Topic: {topic}\n"
        f"Format: {fmt}\n"
        f"Write a {words} word narration and exactly {scene_count} Runway scene prompts.\n"
        "Open on the detail that would make someone stop scrolling. Verify it.\n"
        "If this fact is famous, find the lesser-known number or cause that makes it stranger.\n"
    )
    if short:
        prompt += "Each scene duration must be 5 seconds so the video is 10 seconds total.\n"
    if fmt == "listicle":
        prompt += "This is a list short. Named items, one spine, no filler famous-facts padding.\n"
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
    data = _normalize(_parse_json(response.output_text), scene_count, short=short)
    data["scene_prompts"] = polish_scene_prompts(
        data["scene_prompts"],
        data["script"],
        topic,
        "research",
        data["scene_durations"],
    )
    return data


PROMPT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "scene_prompts": {"type": "array", "items": {"type": "string"}},
        "scene_durations": {"type": "array", "items": {"type": "integer"}},
    },
    "required": ["scene_prompts", "scene_durations"],
}


def polish_scene_prompts(
    prompts: list[str],
    script: str,
    topic: str,
    content_id: str,
    durations: list[int] | None = None,
) -> list[str]:
    """Rewrite thin prompts with Astra. Does not call Runway."""
    prompts = [prepare_prompt(p) for p in prompts]
    flagged = weak_prompts(prompts)
    if not flagged:
        return prompts
    print(f"  Astra rewriting {len(flagged)} thin Runway prompt(s) before generation")
    rewritten = _rewrite_scene_prompts(prompts, script, topic, content_id, durations or [])
    still = weak_prompts(rewritten)
    if still:
        details = "; ".join(f"scene {i + 1}: {', '.join(issues)}" for i, issues in still)
        raise RuntimeError(
            f"Runway prompts are still too thin after rewrite ({details}). "
            "Not spending video credits on a bad prompt."
        )
    return rewritten


def _rewrite_scene_prompts(
    prompts: list[str],
    script: str,
    topic: str,
    content_id: str,
    durations: list[int],
) -> list[str]:
    issues = weak_prompts(prompts)
    notes = "\n".join(
        f"Scene {i + 1} problems: {', '.join(problem)}" for i, problem in issues
    )
    beats = "\n".join(
        f"Scene {i + 1} ({(durations[i] if i < len(durations) else 8)}s) current prompt:\n{prompt}"
        for i, prompt in enumerate(prompts)
    )
    client = _client()
    response = client.responses.create(
        model=MODEL,
        instructions=(
            "Rewrite these Seedance 2.5 text-to-video prompts. Keep the same scene count and order. "
            f"{SCENE_PROMPT} Return only JSON."
        ),
        input=(
            f"Topic: {topic}\nNarration:\n{script}\n\n{notes}\n\n{beats}\n"
            "Rewrite every scene. Make each prompt specific enough to film."
        ),
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
    rewritten = [prepare_prompt(str(p)) for p in data.get("scene_prompts", []) if str(p).strip()]
    if len(rewritten) < len(prompts):
        raise RuntimeError(
            f"Astra rewrite returned {len(rewritten)} prompts, need {len(prompts)}"
        )
    return rewritten[: len(prompts)]


def runway_prompts_for_script(script: str, topic: str = "", content_id: str = "research") -> dict[str, Any]:
    """Astra writes Runway prompts only. No web search. Script is already approved."""
    durations = [5, 8, 8, 8, 8, 8]
    client = _client()
    response = client.responses.create(
        model=MODEL,
        instructions=(
            "Write exactly 6 Seedance 2.5 text-to-video prompts that match this narration. "
            f"{SCENE_PROMPT} "
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
    prompts = [prepare_prompt(str(p)) for p in data.get("scene_prompts", []) if str(p).strip()]
    if len(prompts) < 6:
        raise RuntimeError(f"Astra returned {len(prompts)} scene prompts, need 6")
    prompts = polish_scene_prompts(prompts[:6], script, topic, content_id, durations)
    return {
        "scene_prompts": prompts,
        "scene_durations": durations,
    }
