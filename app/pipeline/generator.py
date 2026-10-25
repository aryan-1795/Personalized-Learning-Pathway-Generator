"""Grounded generation, semantic validation, bounded repair, and fallback."""

from __future__ import annotations

import hashlib
import heapq
import json
import time
from collections import OrderedDict

from pydantic import ValidationError

from app.knowledge.loader import Resource, load_resources, load_topic_graph
from app.llm.prompts import render_prompt
from app.llm.providers import LLMProvider
from app.pipeline.context import build_context, sanitize_goal
from app.pipeline.schemas import (
    Checkpoint,
    GenerationMetadata,
    Pathway,
    PathwayInput,
    PathwayResource,
    PathwayResult,
    Phase,
    TopicStep,
)

PROMPT_VERSION = "pathway_v2"
CACHE_LIMIT = 128


def validate_pathway(
    pathway: Pathway,
    mastery: dict[str, float],
    budget_hours: float,
) -> list[str]:
    """Return semantic errors for an LLM-caller's candidate pathway; empty means valid."""
    graph = load_topic_graph(pathway.subject)
    by_id = graph.by_id()
    resources = load_resources()
    resource_lookup: dict[tuple[str, str, str], Resource] = {
        (resource.topic_id, resource.url, resource.title): resource for resource in resources
    }
    errors: list[str] = []
    flattened = [step for phase in pathway.phases for step in phase.steps]
    topic_ids = [step.topic_id for step in flattened]
    duplicates = sorted(topic_id for topic_id in set(topic_ids) if topic_ids.count(topic_id) > 1)
    if duplicates:
        errors.append(f"duplicate topics: {duplicates}")
    unknown = sorted(set(topic_ids) - by_id.keys())
    if unknown:
        errors.append(f"unknown topic IDs: {unknown}")
    position = {topic_id: index for index, topic_id in enumerate(topic_ids)}
    for step in flattened:
        if step.topic_id not in by_id:
            continue
        topic = by_id[step.topic_id]
        if mastery.get(step.topic_id, 0.5) > 0.85 and not step.review:
            errors.append(f"mastered topic {step.topic_id} must be omitted or marked review")
        for prerequisite in topic.prerequisites:
            if prerequisite in position and position[prerequisite] >= position[step.topic_id]:
                errors.append(f"prerequisite {prerequisite} must precede {step.topic_id}")
            elif prerequisite not in position and mastery.get(prerequisite, 0.5) <= 0.85:
                errors.append(f"missing unmastered prerequisite {prerequisite} for {step.topic_id}")
        for resource in step.resources:
            key = (step.topic_id, resource.url, resource.title)
            if key not in resource_lookup:
                errors.append(f"resource {resource.url} is not cataloged for {step.topic_id}")
            elif resource_lookup[key].type != resource.type:
                errors.append(f"resource type mismatch for {resource.url}")
    summed_hours = sum(step.hours for step in flattened)
    if summed_hours > budget_hours + 1e-6:
        errors.append(f"planned hours {summed_hours:g} exceed budget {budget_hours:g}")
    if abs(summed_hours - pathway.total_hours) > 0.01:
        errors.append(
            f"total_hours {pathway.total_hours:g} does not equal step hours {summed_hours:g}"
        )
    if pathway.total_hours > budget_hours + 1e-6:
        errors.append(f"pathway total {pathway.total_hours:g} exceeds budget {budget_hours:g}")
    return errors


def _cache_key(request: PathwayInput, provider: LLMProvider, prompt_version: str) -> str:
    payload = {
        "subject": request.subject,
        "mastery": dict(sorted(request.mastery.items())),
        "goal": request.goal,
        "budget_hours": request.budget_hours,
        "prompt_version": prompt_version,
        "model": provider.model_name,
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def _fallback_pathway(request: PathwayInput) -> Pathway:
    """Build a deterministic prerequisite-first pathway weighted by mastery gaps."""
    graph = load_topic_graph(request.subject)
    by_id = graph.by_id()
    resources_by_topic: dict[str, list[Resource]] = {}
    for resource in load_resources():
        if resource.verified:
            resources_by_topic.setdefault(resource.topic_id, []).append(resource)

    selected = {
        topic.id
        for topic in graph.topics
        if request.mastery.get(topic.id, 0.5) <= 0.85
    }
    pending = list(selected)
    while pending:
        topic = by_id[pending.pop()]
        for prerequisite in topic.prerequisites:
            if request.mastery.get(prerequisite, 0.5) <= 0.85 and prerequisite not in selected:
                selected.add(prerequisite)
                pending.append(prerequisite)

    indegree = {
        topic_id: sum(prerequisite in selected for prerequisite in by_id[topic_id].prerequisites)
        for topic_id in selected
    }
    dependents: dict[str, list[str]] = {topic_id: [] for topic_id in selected}
    for topic_id in selected:
        for prerequisite in by_id[topic_id].prerequisites:
            if prerequisite in selected:
                dependents[prerequisite].append(topic_id)

    def priority(topic_id: str) -> tuple[float, str]:
        topic = by_id[topic_id]
        gap = 1 - request.mastery.get(topic_id, 0.5)
        goal_words = set(request.goal.lower().split())
        overlap = len(goal_words & set(topic.name.lower().split()))
        score = (gap * topic.difficulty + overlap * 0.25) / topic.estimated_hours
        return (-score, topic_id)

    ready = [(priority(topic_id), topic_id) for topic_id, degree in indegree.items() if degree == 0]
    heapq.heapify(ready)
    ordered: list[str] = []
    while ready:
        _, topic_id = heapq.heappop(ready)
        ordered.append(topic_id)
        for child in dependents[topic_id]:
            indegree[child] -= 1
            if indegree[child] == 0:
                heapq.heappush(ready, (priority(child), child))

    steps: list[TopicStep] = []
    included: set[str] = set()
    remaining = request.budget_hours
    for topic_id in ordered:
        topic = by_id[topic_id]
        prerequisites_ready = all(
            request.mastery.get(prerequisite, 0.5) > 0.85 or prerequisite in included
            for prerequisite in topic.prerequisites
        )
        if not prerequisites_ready or topic.estimated_hours > remaining:
            continue
        resources = [
            PathwayResource(title=item.title, url=item.url, type=item.type)
            for item in resources_by_topic.get(topic_id, [])[:1]
        ]
        steps.append(
            TopicStep(
                topic_id=topic_id,
                rationale=f"This topic addresses a current mastery gap in {topic.name}.",
                hours=topic.estimated_hours,
                practice_task=f"Complete a focused exercise applying {topic.name}.",
                resources=resources,
            )
        )
        included.add(topic_id)
        remaining -= topic.estimated_hours

    phases: list[Phase] = []
    for offset in range(0, len(steps), 4):
        phase_steps = steps[offset : offset + 4]
        phases.append(
            Phase(
                title=f"Phase {len(phases) + 1}: Foundations and practice",
                steps=phase_steps,
                checkpoint=Checkpoint(
                    title="Checkpoint",
                criteria=(
                    "Explain and practice "
                    + ", ".join(by_id[step.topic_id].name for step in phase_steps)
                    + "."
                ),
                ),
            )
        )
    return Pathway(
        subject=request.subject,
        goal=sanitize_goal(request.goal),
        phases=phases,
        total_hours=round(sum(step.hours for step in steps), 2),
    )


class PathwayGenerator:
    """Generate, validate, repair, cache, or safely fall back for a pathway."""

    def __init__(
        self,
        provider: LLMProvider,
        max_retries: int = 2,
        prompt_version: str = PROMPT_VERSION,
        context_char_budget: int = 8000,
    ) -> None:
        if not 0 <= max_retries <= 2:
            raise ValueError("max_retries must be between 0 and 2")
        self.provider = provider
        self.max_retries = max_retries
        self.prompt_version = prompt_version
        self.context_char_budget = context_char_budget
        self._cache: OrderedDict[str, PathwayResult] = OrderedDict()

    def generate_pathway(self, request: PathwayInput) -> PathwayResult:
        """Generate a validated pathway from a typed request, with deterministic fallback."""
        key = _cache_key(request, self.provider, self.prompt_version)
        if key in self._cache:
            cached = self._cache.pop(key)
            self._cache[key] = cached
            return cached.model_copy(
                deep=True,
                update={
                    "metadata": cached.metadata.model_copy(deep=True, update={"cache_hit": True})
                },
            )

        started = time.perf_counter()
        context = build_context(
            request.subject,
            request.goal,
            request.mastery,
            request.budget_hours,
            max_chars=self.context_char_budget,
        )
        base_prompt = render_prompt(self.prompt_version, context.text, sanitize_goal(request.goal))
        validation_errors: list[str] = []
        first_try_schema_valid = False
        first_try_semantic_valid = False
        first_try_validation_errors: list[str] = []
        source = "fallback"
        result_pathway: Pathway | None = None
        retries_used = 0

        for attempt in range(self.max_retries + 1):
            prompt = base_prompt
            if validation_errors:
                prompt += (
                    "\n\n# Repair request\nFix these specific errors in the previous JSON output:\n"
                    + "\n".join(f"- {error}" for error in validation_errors)
                    + "\nReturn the complete corrected JSON object only."
                )
            try:
                output = self.provider.generate(
                    [{"role": "user", "content": prompt}],
                    Pathway,
                    max_new_tokens=1600,
                    do_sample=False,
                )
            except Exception as exc:
                validation_errors.append(f"provider error: {type(exc).__name__}: {exc}")
                if attempt == 0:
                    first_try_validation_errors = list(validation_errors)
                break
            try:
                candidate = Pathway.model_validate_json(output)
            except ValidationError as exc:
                validation_errors = [
                    "schema/JSON validation failed: "
                    f"{exc.errors(include_url=False)}"
                ]
                if attempt == 0:
                    first_try_validation_errors = list(validation_errors)
                retries_used = min(attempt + 1, self.max_retries)
                continue
            if attempt == 0:
                first_try_schema_valid = True
            if candidate.subject != request.subject:
                errors = ["pathway subject does not match request subject"]
            else:
                errors = validate_pathway(candidate, request.mastery, request.budget_hours)
            if attempt == 0:
                first_try_validation_errors = list(errors)
                first_try_semantic_valid = not errors
            if errors:
                validation_errors = errors
                retries_used = min(attempt + 1, self.max_retries)
                continue
            result_pathway = candidate
            source = "llm_ok" if attempt == 0 else "llm_repaired"
            retries_used = attempt
            break

        if result_pathway is None:
            result_pathway = _fallback_pathway(request)
            fallback_errors = validate_pathway(
                result_pathway, request.mastery, request.budget_hours
            )
            if fallback_errors:
                raise RuntimeError(f"Deterministic fallback failed validation: {fallback_errors}")
            source = "fallback"

        elapsed = (time.perf_counter() - started) * 1000
        result = PathwayResult(
            pathway=result_pathway,
            metadata=GenerationMetadata(
                source=source,
                prompt_version=self.prompt_version,
                model=self.provider.model_name,
                latency_ms=round(elapsed, 3),
                retries=retries_used,
                validation_errors=validation_errors,
                first_try_schema_valid=first_try_schema_valid,
                first_try_semantic_valid=first_try_semantic_valid,
                first_try_validation_errors=first_try_validation_errors,
            ),
        )
        self._cache[key] = result
        if len(self._cache) > CACHE_LIMIT:
            self._cache.popitem(last=False)
        return result


def generate_pathway(
    request: PathwayInput,
    provider: LLMProvider,
    prompt_version: str = PROMPT_VERSION,
) -> PathwayResult:
    """Generate a grounded, validated pathway for an LLM caller's typed request."""
    generator = PathwayGenerator(provider=provider, prompt_version=prompt_version)
    return generator.generate_pathway(request)
