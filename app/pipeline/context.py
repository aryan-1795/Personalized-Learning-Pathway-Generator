"""Compact, deterministic prompt context assembly within a character budget."""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass

from app.knowledge.loader import Resource, Subject, Topic, load_resources, load_topic_graph

WORD = re.compile(r"[a-z0-9]+")


@dataclass(frozen=True)
class PromptContext:
    """Serialized allowlisted context and the selected records it contains."""

    text: str
    topic_ids: frozenset[str]
    resource_urls: frozenset[str]
    estimated_tokens: int
    truncated: bool


def sanitize_goal(goal: str, max_length: int = 500) -> str:
    """Normalize free text, remove control characters, and enforce a hard bound."""
    normalized = " ".join("".join(c if c.isprintable() else " " for c in goal).split())
    return normalized[:max_length]


def _score_topic(topic: Topic, goal_words: set[str], mastery: dict[str, float]) -> float:
    text = f"{topic.name} {topic.description} {' '.join(topic.tags)}".lower()
    topic_words = set(WORD.findall(text))
    overlap = len(topic_words & goal_words)
    weakness = 1 - mastery.get(topic.id, 0.5)
    return overlap * 2 + weakness


def _dependency_closure(selected: set[str], topics: dict[str, Topic]) -> set[str]:
    closure = set(selected)
    pending = list(selected)
    while pending:
        topic = topics[pending.pop()]
        for prerequisite in topic.prerequisites:
            if prerequisite not in closure:
                closure.add(prerequisite)
                pending.append(prerequisite)
    return closure


def build_context(
    subject: Subject,
    goal: str,
    mastery: dict[str, float],
    budget_hours: float,
    max_chars: int = 8000,
) -> PromptContext:
    """Select relevant weak topics plus prerequisites and catalog links under budget."""
    graph = load_topic_graph(subject)
    by_id = graph.by_id()
    unknown_mastery_ids = set(mastery) - by_id.keys()
    if unknown_mastery_ids:
        raise ValueError(f"Mastery contains unknown topic IDs: {sorted(unknown_mastery_ids)}")
    clean_goal = sanitize_goal(goal)
    goal_words = set(WORD.findall(clean_goal.lower()))
    ranked = sorted(
        graph.topics,
        key=lambda topic: (-_score_topic(topic, goal_words, mastery), topic.id),
    )
    selected: set[str] = set()
    resources_by_topic: dict[str, list[Resource]] = {}
    for resource in load_resources():
        if resource.topic_id in by_id:
            resources_by_topic.setdefault(resource.topic_id, []).append(resource)

    def encode(topic_ids: set[str]) -> tuple[str, set[str]]:
        ids_in_graph_order = [topic.id for topic in graph.topics if topic.id in topic_ids]
        resource_records = [
            resource.model_dump()
            for topic_id in ids_in_graph_order
            for resource in resources_by_topic.get(topic_id, [])
        ]
        payload = {
            "subject": subject,
            "budget_hours": budget_hours,
            "goal": clean_goal,
            "mastery": {topic_id: mastery.get(topic_id, 0.5) for topic_id in ids_in_graph_order},
            "topics": [
                {
                    **by_id[topic_id].model_dump(),
                    "mastery": mastery.get(topic_id, 0.5),
                }
                for topic_id in ids_in_graph_order
            ],
            "resources": resource_records,
        }
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":")), {
            record["url"] for record in resource_records
        }

    truncated = False
    for topic in ranked:
        candidate = _dependency_closure(selected | {topic.id}, by_id)
        candidate_text, _ = encode(candidate)
        if len(candidate_text) <= max_chars:
            selected = candidate
        else:
            truncated = True
    if not selected and ranked:
        first = ranked[0]
        closure = _dependency_closure({first.id}, by_id)
        selected = closure
    text, urls = encode(selected)
    if len(text) > max_chars:
        # Preserve a valid compact context even when the caller sets an impractically small limit.
        payload = json.loads(text)
        payload["resources"] = []
        payload["topics"] = payload["topics"][:1]
        first_topic_id = payload["topics"][0]["id"]
        payload["mastery"] = {
            key: value
            for key, value in payload["mastery"].items()
            if key == first_topic_id
        }
        text = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        urls = set()
        selected = {payload["topics"][0]["id"]}
        truncated = True
    return PromptContext(
        text=text,
        topic_ids=frozenset(selected),
        resource_urls=frozenset(urls),
        estimated_tokens=math.ceil(len(text) / 4),
        truncated=truncated,
    )
