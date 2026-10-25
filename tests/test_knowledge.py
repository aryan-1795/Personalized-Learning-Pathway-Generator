from __future__ import annotations

import pytest
from app.knowledge.loader import Resource, Topic, TopicGraph, load_resources, load_topic_graph
from pydantic import ValidationError


@pytest.mark.parametrize(
    ("subject", "minimum"),
    [("python", 25), ("dsa", 25), ("machine_learning", 15), ("web_development", 15)],
)
def test_bundled_graphs_have_required_topic_counts(subject: str, minimum: int) -> None:
    graph = load_topic_graph(subject)  # type: ignore[arg-type]
    assert len(graph.topics) >= minimum
    assert len(graph.by_id()) == len(graph.topics)


def test_all_prerequisite_edges_are_valid_and_ordered_acyclically() -> None:
    for subject in ("python", "dsa", "machine_learning", "web_development"):
        graph = load_topic_graph(subject)  # type: ignore[arg-type]
        positions = {topic.id: index for index, topic in enumerate(graph.topics)}
        assert all(
            positions[prerequisite] < positions[topic.id]
            for topic in graph.topics
            for prerequisite in topic.prerequisites
        )


def test_resources_are_https_and_reference_curated_topics() -> None:
    resources = load_resources()
    known_ids = {
        topic.id
        for subject in ("python", "dsa", "machine_learning", "web_development")
        for topic in load_topic_graph(subject).topics
    }
    assert resources
    assert all(resource.url.startswith("https://") for resource in resources)
    assert all(resource.topic_id in known_ids for resource in resources)


def test_graph_rejects_a_prerequisite_cycle() -> None:
    first = Topic(
        id="first", name="First", description="First", prerequisites=["second"],
        difficulty=1, estimated_hours=1, tags=[],
    )
    second = Topic(
        id="second", name="Second", description="Second", prerequisites=["first"],
        difficulty=1, estimated_hours=1, tags=[],
    )
    with pytest.raises(ValidationError, match="cycle"):
        TopicGraph(subject="python", topics=[first, second])


def test_resource_rejects_non_https_url() -> None:
    with pytest.raises(ValidationError):
        Resource(
            title="Unsafe", url="http://example.org", type="docs", topic_id="x", verified=False
        )
