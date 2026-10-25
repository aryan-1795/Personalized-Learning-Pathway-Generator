from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from app.knowledge.loader import load_topic_graph
from app.retrieval.service import Retriever, retrieve_resources


class _Vectors(list[list[float]]):
    def tolist(self) -> list[list[float]]:
        return list(self)


class _FakeModel:
    def __init__(self) -> None:
        self.calls = 0

    def encode(self, texts: list[str], **kwargs: Any) -> _Vectors:
        self.calls += 1
        return _Vectors(
            [[1.0, 0.0] if "graph" in text.lower() else [0.0, 1.0] for text in texts]
        )


def test_lexical_retrieval_returns_relevant_allowlisted_records() -> None:
    result = Retriever(enable_embeddings=False).retrieve(
        "dsa", "binary search sorted arrays", top_k=5
    )
    assert result.backend == "lexical"
    assert result.topics[0].topic.id == "binary-search"
    assert result.resources
    valid_ids = {candidate.topic.id for candidate in result.topics}
    assert all(candidate.resource.topic_id in valid_ids for candidate in result.resources)
    assert all(candidate.resource.url.startswith("https://") for candidate in result.resources)


def test_weak_topics_are_included_even_when_goal_is_unrelated() -> None:
    weak = "graph-traversal"
    result = Retriever(enable_embeddings=False).retrieve(
        "dsa", "learn unrelated basics", [weak], top_k=1
    )
    assert result.topics[0].topic.id == weak


def test_embedding_index_is_written_and_reused(tmp_path: Path) -> None:
    first = Retriever(cache_dir=tmp_path)
    first_model = _FakeModel()
    first._model = first_model
    first_result = first.retrieve("dsa", "graph traversal", top_k=3)
    assert first_result.backend == "embeddings"
    assert any(
        candidate.topic.id == "graphs-and-representations"
        for candidate in first_result.topics
    )
    cache_files = list(tmp_path.glob("dsa-*.json"))
    assert len(cache_files) == 1
    assert first_model.calls == 2

    second = Retriever(cache_dir=tmp_path)
    second_model = _FakeModel()
    second._model = second_model
    second.retrieve("dsa", "graph traversal", top_k=3)
    assert second_model.calls == 1


def test_retrieval_is_scoped_to_subject() -> None:
    result = retrieve_resources("python", "Python functions", top_k=10)
    python_ids = {topic.id for topic in load_topic_graph("python").topics}
    assert result.topics
    assert all(candidate.resource.topic_id in python_ids for candidate in result.resources)


def test_invalid_top_k_and_unknown_weak_topic_are_rejected() -> None:
    retriever = Retriever(enable_embeddings=False)
    with pytest.raises(ValueError, match="at least 1"):
        retriever.retrieve("python", "goal", top_k=0)
    with pytest.raises(ValueError, match="unknown"):
        retriever.retrieve("python", "goal", ["missing-topic"])
