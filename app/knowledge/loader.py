"""Validated loading and lookup for the curated topic graphs and resource catalog."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

DATA_DIR = Path(__file__).resolve().parent
Subject = Literal["python", "dsa", "machine_learning", "web_development"]


class Topic(BaseModel):
    """A curated learning objective and its prerequisite edges."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(min_length=1, pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
    name: str = Field(min_length=1)
    description: str = Field(min_length=1)
    prerequisites: list[str] = Field(default_factory=list)
    difficulty: int = Field(ge=1, le=5)
    estimated_hours: float = Field(gt=0)
    tags: list[str] = Field(default_factory=list)

    @field_validator("prerequisites")
    @classmethod
    def unique_prerequisites(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("prerequisites must be unique")
        return value


class TopicGraph(BaseModel):
    """A subject's directed acyclic graph of validated topics."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    subject: Subject
    topics: list[Topic] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_graph(self) -> TopicGraph:
        by_id = {topic.id: topic for topic in self.topics}
        if len(by_id) != len(self.topics):
            raise ValueError("topic IDs must be unique")
        for topic in self.topics:
            missing = set(topic.prerequisites) - by_id.keys()
            if missing:
                raise ValueError(f"{topic.id} has unknown prerequisites: {sorted(missing)}")
            if topic.id in topic.prerequisites:
                raise ValueError(f"{topic.id} cannot depend on itself")
        self._assert_acyclic(by_id)
        return self

    @staticmethod
    def _assert_acyclic(by_id: dict[str, Topic]) -> None:
        visiting: set[str] = set()
        visited: set[str] = set()

        def visit(topic_id: str) -> None:
            if topic_id in visiting:
                raise ValueError(f"prerequisite cycle includes {topic_id}")
            if topic_id in visited:
                return
            visiting.add(topic_id)
            for prerequisite in by_id[topic_id].prerequisites:
                visit(prerequisite)
            visiting.remove(topic_id)
            visited.add(topic_id)

        for topic_id in by_id:
            visit(topic_id)

    def by_id(self) -> dict[str, Topic]:
        """Return topics indexed by their stable IDs."""
        return {topic.id: topic for topic in self.topics}


class Resource(BaseModel):
    """A catalog resource linked to a topic in its subject graph."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    title: str = Field(min_length=1)
    url: str = Field(pattern=r"^https://")
    type: str = Field(min_length=1)
    topic_id: str = Field(min_length=1)
    verified: bool


@lru_cache(maxsize=4)
def load_topic_graph(subject: Subject) -> TopicGraph:
    """Load and validate one bundled subject graph by its public subject key."""
    path = DATA_DIR / f"topics_{subject}.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Unable to load topic graph for {subject}: {exc}") from exc
    graph = TopicGraph.model_validate(payload)
    if len({t.id for t in graph.topics}) != len(graph.topics):
        raise ValueError(f"Topic IDs must be unique in {subject}")
    return graph


@lru_cache(maxsize=1)
def load_resources() -> tuple[Resource, ...]:
    """Load the resource allowlist and verify every link maps to a known topic."""
    path = DATA_DIR / "resources.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        resources = tuple(Resource.model_validate(item) for item in payload)
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Unable to load resource catalog: {exc}") from exc
    known_topic_ids = {
        topic.id
        for subject in Subject.__args__
        for topic in load_topic_graph(subject).topics
    }
    unknown = {resource.topic_id for resource in resources} - known_topic_ids
    if unknown:
        raise ValueError(f"Resources refer to unknown topics: {sorted(unknown)}")
    return resources


def get_topic_graph(subject: Subject) -> TopicGraph:
    """Return the curated topic graph for an LLM caller's chosen subject."""
    return load_topic_graph(subject)


def resources_for_topic(topic_id: str) -> tuple[Resource, ...]:
    """Return only catalog-allowlisted resources associated with a topic ID."""
    return tuple(resource for resource in load_resources() if resource.topic_id == topic_id)
