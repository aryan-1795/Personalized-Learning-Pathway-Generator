"""Pydantic request contracts for the Flask REST API."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from app.knowledge.loader import Subject


class AssessmentStartRequest(BaseModel):
    """Request to start an adaptive quiz for a supported subject."""

    model_config = ConfigDict(extra="forbid")

    subject: Subject


class AssessmentAnswerRequest(BaseModel):
    """Answer to the active question in a server-owned assessment session."""

    model_config = ConfigDict(extra="forbid")

    session_id: str = Field(min_length=1, max_length=64)
    question_id: str = Field(min_length=1, max_length=128)
    selected_index: int = Field(ge=0, le=20)
