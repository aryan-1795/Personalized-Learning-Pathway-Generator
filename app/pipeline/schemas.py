"""Canonical structured output contracts for generated learning roadmaps."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.knowledge.loader import Subject


class PathwayResource(BaseModel):
    """A resource copied from the reviewed catalog."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    title: str = Field(min_length=1)
    url: str = Field(pattern=r"^https://")
    type: str = Field(min_length=1)


class Checkpoint(BaseModel):
    """A phase completion check with a learner-observable outcome."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    title: str = Field(min_length=1)
    criteria: str = Field(min_length=1)


class TopicStep(BaseModel):
    """One grounded topic with rationale, effort, practice, and resources."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    topic_id: str = Field(min_length=1)
    rationale: str = Field(min_length=1)
    hours: float = Field(gt=0)
    practice_task: str = Field(min_length=1)
    resources: list[PathwayResource] = Field(default_factory=list)
    review: bool = False


class Phase(BaseModel):
    """A named group of ordered topic steps and a completion checkpoint."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    title: str = Field(min_length=1)
    steps: list[TopicStep] = Field(min_length=1)
    checkpoint: Checkpoint


class Pathway(BaseModel):
    """A complete ordered roadmap for one learner goal and subject."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    subject: Subject
    goal: str = Field(min_length=1, max_length=500)
    phases: list[Phase]
    total_hours: float = Field(ge=0)


class GenerationMetadata(BaseModel):
    """Provenance and validation data for a generated pathway."""

    source: Literal["llm_ok", "llm_repaired", "fallback"]
    prompt_version: str
    model: str
    latency_ms: float = Field(ge=0)
    retries: int = Field(ge=0)
    validation_errors: list[str] = Field(default_factory=list)
    cache_hit: bool = False
    first_try_schema_valid: bool = False
    first_try_semantic_valid: bool = False
    first_try_validation_errors: list[str] = Field(default_factory=list)


class PathwayResult(BaseModel):
    """Pathway plus source and validation metadata returned by the service."""

    pathway: Pathway
    metadata: GenerationMetadata


class PathwayInput(BaseModel):
    """Validated generation request shared by API and agent-facing functions."""

    model_config = ConfigDict(extra="forbid")

    subject: Subject
    goal: str = Field(min_length=1, max_length=500)
    mastery: dict[str, float] = Field(default_factory=dict)
    budget_hours: float = Field(gt=0, le=1000)

    @field_validator("goal")
    @classmethod
    def normalize_goal(cls, value: str) -> str:
        return " ".join(value.split())

    @field_validator("mastery")
    @classmethod
    def validate_mastery(cls, value: dict[str, float]) -> dict[str, float]:
        if any(not 0 <= score <= 1 for score in value.values()):
            raise ValueError("mastery values must be between 0 and 1")
        return value
