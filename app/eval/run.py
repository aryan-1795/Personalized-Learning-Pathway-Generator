"""Fixed-profile evaluation runner for pathway prompt/model comparisons."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.knowledge.loader import load_resources, load_topic_graph
from app.llm.providers import HFLocalProvider, LLMProvider, MockProvider
from app.pipeline.generator import PathwayGenerator
from app.pipeline.schemas import (
    Checkpoint,
    Pathway,
    PathwayInput,
    PathwayResource,
    Phase,
    TopicStep,
)

ROOT = Path(__file__).resolve().parents[2]
PROFILES_PATH = Path(__file__).with_name("profiles.json")
RESULTS_DIR = ROOT / "eval" / "results"


def load_profiles(path: Path = PROFILES_PATH) -> list[dict[str, Any]]:
    """Load the fixed learner profile set and validate its basic shape."""
    profiles = json.loads(path.read_text(encoding="utf-8"))
    if len(profiles) != 20:
        raise ValueError(f"Expected 20 evaluation profiles, found {len(profiles)}")
    identifiers = [profile["id"] for profile in profiles]
    if len(identifiers) != len(set(identifiers)):
        raise ValueError("Evaluation profile IDs must be unique")
    return profiles


def _valid_fixture_output(request: PathwayInput) -> str:
    graph = load_topic_graph(request.subject)
    first_topic = next(topic for topic in graph.topics if not topic.prerequisites)
    resource = next(
        (item for item in load_resources() if item.topic_id == first_topic.id), None
    )
    step_resources = []
    if resource:
        step_resources.append(
            PathwayResource(title=resource.title, url=resource.url, type=resource.type)
        )
    hours = min(first_topic.estimated_hours, request.budget_hours)
    pathway = Pathway(
        subject=request.subject,
        goal=request.goal,
        phases=[
            Phase(
                title="Evidence-based starting point",
                steps=[
                    TopicStep(
                        topic_id=first_topic.id,
                        rationale="This foundational topic is a safe starting point.",
                        hours=hours,
                        practice_task=f"Complete a short exercise on {first_topic.name}.",
                        resources=step_resources,
                    )
                ],
                checkpoint=Checkpoint(
                    title="Explain the basics", criteria=f"Summarize {first_topic.name}."
                ),
            )
        ],
        total_hours=hours,
    )
    return pathway.model_dump_json()


def _hallucinated_output(valid_output: str) -> str:
    payload = json.loads(valid_output)
    payload["phases"][0]["steps"][0]["topic_id"] = "invented-topic-from-fixture"
    return json.dumps(payload)


def make_mock_provider(profile_index: int, valid_output: str) -> MockProvider:
    """Return deterministic valid, repair, or fallback responses for harness coverage."""
    if profile_index % 5 == 4:
        return MockProvider(["{}", "{}", "{}"], model_name="mock-fixture")
    if profile_index % 10 == 3:
        return MockProvider(["{malformed", valid_output], model_name="mock-fixture")
    if profile_index % 10 == 8:
        return MockProvider(
            [_hallucinated_output(valid_output), valid_output], model_name="mock-fixture"
        )
    return MockProvider([valid_output], model_name="mock-fixture")


def _run_comparison(
    provider_name: str,
    prompt_version: str,
    profiles: list[dict[str, Any]],
) -> dict[str, Any]:
    outcomes: list[dict[str, Any]] = []
    schema_valid: list[bool] = []
    repaired = 0
    fallback = 0
    prerequisite_violation = 0
    hallucination = 0
    compliant = 0
    total_latency = 0.0
    for index, profile in enumerate(profiles):
        request = PathwayInput.model_validate(
            {key: value for key, value in profile.items() if key != "id"}
        )
        valid_output = _valid_fixture_output(request)
        provider: LLMProvider
        if provider_name == "mock-fixture":
            provider = make_mock_provider(index, valid_output)
        else:
            provider = HFLocalProvider(provider_name)
        generator = PathwayGenerator(provider, prompt_version=prompt_version)
        result = generator.generate_pathway(request)
        metadata = result.metadata
        errors = metadata.first_try_validation_errors
        schema_valid.append(metadata.first_try_schema_valid)
        repaired += metadata.source == "llm_repaired"
        fallback += metadata.source == "fallback"
        prerequisite_violation += any("prerequisite" in error for error in errors)
        hallucination += any(
            "unknown topic" in error or "not cataloged" in error for error in errors
        )
        profile_compliant = (
            result.pathway.total_hours <= request.budget_hours
            and sum(
                step.hours
                for phase in result.pathway.phases
                for step in phase.steps
            )
            <= request.budget_hours
        )
        compliant += profile_compliant
        total_latency += metadata.latency_ms
        outcomes.append(
            {
                "profile_id": profile["id"],
                "source": metadata.source,
                "first_try_schema_valid": metadata.first_try_schema_valid,
                "first_try_semantic_valid": metadata.first_try_semantic_valid,
                "first_try_validation_errors": errors,
                "retries": metadata.retries,
                "latency_ms": metadata.latency_ms,
                "time_budget_compliant": profile_compliant,
            }
        )
    count = len(profiles)
    return {
        "provider": provider_name,
        "prompt_version": prompt_version,
        "profile_count": count,
        "metrics": {
            "schema_validity_rate_first_try": round(sum(schema_valid) / count, 4),
            "repair_rate": round(repaired / count, 4),
            "fallback_rate": round(fallback / count, 4),
            "prerequisite_order_violation_rate_first_try": round(
                prerequisite_violation / count, 4
            ),
            "hallucinated_topic_or_url_rate_first_try": round(hallucination / count, 4),
            "time_budget_compliance_rate_final": round(compliant / count, 4),
            "mean_latency_ms": round(total_latency / count, 3),
        },
        "outcomes": outcomes,
    }


def render_markdown(results: list[dict[str, Any]]) -> str:
    """Render comparison metrics as a compact Markdown table."""
    columns = [
        ("schema_validity_rate_first_try", "Schema valid"),
        ("repair_rate", "Repair"),
        ("fallback_rate", "Fallback"),
        ("prerequisite_order_violation_rate_first_try", "Prereq violations"),
        ("hallucinated_topic_or_url_rate_first_try", "Hallucinations"),
        ("time_budget_compliance_rate_final", "Budget compliant"),
        ("mean_latency_ms", "Mean latency ms"),
    ]
    lines = [
        "| Provider / prompt | " + " | ".join(label for _, label in columns) + " |",
        "|---|" + "|".join("---:" for _ in columns) + "|",
    ]
    for result in results:
        metric_values = [result["metrics"][key] for key, _ in columns]
        formatted = []
        for (key, _), value in zip(columns, metric_values, strict=True):
            is_rate = key.endswith("rate_first_try") or key.endswith("rate_final")
            is_rate = is_rate or key in {"repair_rate", "fallback_rate"}
            formatted.append(f"{value * 100:.1f}%" if is_rate else str(value))
        lines.append(
            f"| {result['provider']} / {result['prompt_version']} | "
            + " | ".join(formatted)
            + " |"
        )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--provider", choices=("mock", "local"), default="mock",
        help="Use deterministic harness fixtures or a real local Transformers model.",
    )
    parser.add_argument(
        "--models", nargs="+", default=["mock-fixture"],
        help="Model names to compare (ignored as model IDs in mock mode).",
    )
    parser.add_argument(
        "--prompts", nargs="+", default=["pathway_v2"],
        choices=("pathway_v1", "pathway_v2"),
    )
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args(argv)
    profiles = load_profiles()
    providers = ["mock-fixture"] if args.provider == "mock" else args.models
    results = [
        _run_comparison(provider, prompt, profiles)
        for provider in providers
        for prompt in args.prompts
    ]
    markdown = render_markdown(results)
    print(markdown)
    output = args.output or RESULTS_DIR / (
        f"eval_{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}_{args.provider}.json"
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(
            {
                "created_at_utc": datetime.now(UTC).isoformat(),
                "evaluation_mode": args.provider,
                "profile_set": str(PROFILES_PATH.relative_to(ROOT)),
                "analysis_note": (
                    "Mock fixtures exercise pipeline success, repair, and fallback; "
                    "they are not evidence of real model quality."
                    if args.provider == "mock"
                    else "Local model inference run; see model and prompt identifiers below."
                ),
                "markdown_table": markdown,
                "comparisons": results,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"Saved: {output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
