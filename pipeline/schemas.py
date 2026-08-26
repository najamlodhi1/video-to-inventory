from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field

# Field shapes here follow prompts/detect.md's output block verbatim — that prompt is the
# source of truth for stage 03, and supersedes the earlier detections.json sketch in
# schemas.md (fixtures, reflections, people_present, storage_unit fullness were added there).


class RoomGuess(str, Enum):
    living_room = "living_room"
    bedroom = "bedroom"
    kitchen = "kitchen"
    dining_room = "dining_room"
    bathroom = "bathroom"
    hallway = "hallway"
    landing = "landing"
    stairs = "stairs"
    office = "office"
    garage = "garage"
    loft = "loft"
    garden = "garden"
    exterior = "exterior"
    communal = "communal"
    unknown = "unknown"


class QualityIssue(str, Enum):
    dark = "dark"
    motion_blur = "motion_blur"
    obstructed = "obstructed"
    too_close = "too_close"
    vertical_crop = "vertical_crop"
    mirror_reflection = "mirror_reflection"
    overexposed = "overexposed"


class Fullness(str, Enum):
    empty = "empty"
    part_full = "part_full"
    full = "full"
    unknown = "unknown"


class Item(BaseModel):
    label: str
    catalogue_hint: Optional[str] = None
    position: str = ""
    confidence: float = Field(ge=0, le=1)
    notes: str = ""


class StorageUnit(BaseModel):
    label: str
    catalogue_hint: Optional[str] = None
    doors_open: bool
    fullness: Fullness


class Fixture(BaseModel):
    label: str
    catalogue_hint: Optional[str] = None
    notes: str = ""


class Reflection(BaseModel):
    label: str
    catalogue_hint: Optional[str] = None
    confidence: float = Field(ge=0, le=1)
    notes: str = ""


class AccessFeature(BaseModel):
    type: str
    detail: str = ""


class FrameDetection(BaseModel):
    frame_index: int
    room_guess: RoomGuess
    room_transition: bool
    people_present: bool
    items: list[Item] = Field(default_factory=list)
    storage_units: list[StorageUnit] = Field(default_factory=list)
    fixtures: list[Fixture] = Field(default_factory=list)
    reflections: list[Reflection] = Field(default_factory=list)
    access_features: list[AccessFeature] = Field(default_factory=list)
    quality_issues: list[QualityIssue] = Field(default_factory=list)


class BatchDetectionResponse(BaseModel):
    """Exact shape the model must return for one batch — no prompt_version, no wrapping."""

    frames: list[FrameDetection]


class DetectionsFile(BaseModel):
    """Shape of detections.json, the merged output of stage 03 across all batches."""

    prompt_version: str
    frames: list[FrameDetection]
