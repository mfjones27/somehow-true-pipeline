"""Strict, explicitly timed manifests; no inferred timing or factual assertions."""

import math
import re
import unicodedata
from typing import Annotated, Literal

from pydantic import (
    BaseModel, ConfigDict, Field, ValidationInfo, field_validator, model_validator,
)

Identifier = Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")]
Time = Annotated[float, Field(ge=0, le=60, allow_inf_nan=False, strict=True)]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


def readable_text(value: str) -> str:
    if not value.strip() or value != value.strip():
        raise ValueError("Text must be nonempty with no leading/trailing whitespace")
    if any(unicodedata.category(c).startswith("C") or c in "\r\n\t" for c in value):
        raise ValueError("Control characters, newlines, and invisible controls are forbidden")
    return value


class Segment(StrictModel):
    start: Time
    end: Time

    @model_validator(mode="after")
    def ordered(self):
        if self.end - self.start < 0.1:
            raise ValueError("Each segment must last at least 0.1 seconds")
        return self


class Scene(Segment):
    text: Annotated[str, Field(min_length=1, max_length=90)]
    narration_transcript: Annotated[str, Field(min_length=1, max_length=2500)]
    visual_style: Literal[
        "orbit", "wave", "network", "pulse", "nested-enclaves", "border-house"
    ]

    @field_validator("text", "narration_transcript")
    @classmethod
    def text_is_readable(cls, value):
        return readable_text(value)


class Caption(Segment):
    text: Annotated[str, Field(min_length=1, max_length=110)]

    @field_validator("text")
    @classmethod
    def text_is_readable(cls, value):
        return readable_text(value)


class Manifest(StrictModel):
    content_id: Identifier
    script_version: Identifier
    duration: Time
    narration_audio: Annotated[str, Field(min_length=5, max_length=200)]
    scenes: Annotated[list[Scene], Field(min_length=1, max_length=20)]
    captions: Annotated[list[Caption], Field(min_length=1, max_length=120)]
    output_name: Annotated[
        str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}\.mp4$")
    ] = "final.mp4"

    @field_validator("narration_audio")
    @classmethod
    def safe_asset_name(cls, value):
        # Asset-root-relative POSIX names only: no URLs, drives, escapes or dot paths.
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_./-]*\.wav", value):
            raise ValueError("Use an asset-relative PCM .wav path with safe characters")
        if any(part in ("", ".", "..") for part in value.split("/")):
            raise ValueError("Empty and dot path components are forbidden")
        return value

    @model_validator(mode="after")
    def timeline(self, info: ValidationInfo):
        short_test = bool((info.context or {}).get("allow_short_test", False))
        minimum = 1 if short_test else 25
        if not math.isfinite(self.duration) or not minimum <= self.duration <= 60:
            raise ValueError(f"Duration must be {minimum}–60 seconds")
        previous = 0.0
        for scene in self.scenes:
            if abs(scene.start - previous) > 1e-6:
                raise ValueError("Scenes must be ordered, contiguous, and begin at zero")
            if scene.end > self.duration:
                raise ValueError("Scene exceeds duration")
            previous = scene.end
        if abs(previous - self.duration) > 1e-6:
            raise ValueError("Scenes must cover the entire duration")
        previous = 0.0
        for caption in self.captions:
            if caption.start < previous or caption.end > self.duration:
                raise ValueError("Captions must be ordered, nonoverlapping, and within duration")
            previous = caption.end
        return self


def parse_manifest(data: dict, *, allow_short_test: bool = False) -> Manifest:
    """The short-test flag is a Python-only opt-in; not a manifest/API/CLI option."""
    return Manifest.model_validate(data, context={"allow_short_test": allow_short_test})
