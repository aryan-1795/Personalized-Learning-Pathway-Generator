"""Local embedding retrieval with a deterministic lexical fallback."""

from __future__ import annotations

import hashlib
import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from app.knowledge.loader import Resource, Subject, Topic, load_resources, load_topic_graph

LOGGER = logging.getLogger(__name__)
DEFAULT_EMBEDDING_MODEL = os.getenv(
    "EMBEDDING_MODEL", "sentence-transformers/all-MiniLM-L6-v2"
)
DEFAULT_CACHE_DIR = Path(__file__).resolve().parents[2] / ".cache" / "embeddings"


class TopicCandidate(BaseModel):
    """A retrieved topic and its relevance score."""

    model_config = ConfigDict(frozen=True)

    topic: Topic
    score: float


class ResourceCandidate(BaseModel):
    """A retrieved catalog resource and its relevance score."""

    model_config = ConfigDict(frozen=True)

    resource: Resource
    score: float


class RetrievalResult(BaseModel):
    """Relevant topic and resource candidates plus the backend used."""

    model_config = ConfigDict(frozen=True)

    topics: list[TopicCandidate]
    resources: list[ResourceCandidate]
    backend: Literal["embeddings", "lexical"]
    model: str


@dataclass(frozen=True)
class _Document:
    document_id: str
    kind: Literal["topic", "resource"]
    topic_id: str
    text: str
    topic: Topic | None = None
    resource: Resource | None = None


class Retriever:
    """Retrieve allowlisted knowledge using cached embeddings or lexical ranking."""

    def __init__(
        self,
        model_name: str = DEFAULT_EMBEDDING_MODEL,
        cache_dir: Path = DEFAULT_CACHE_DIR,
        enable_embeddings: bool = True,
    ) -> None:
        self.model_name = model_name
        self.cache_dir = cache_dir
        self.enable_embeddings = enable_embeddings
        self._model: Any = None
        self._embedding_failure: str | None = None
        self._documents: dict[str, tuple[_Document, ...]] = {}
        self._vectors: dict[str, list[list[float]]] = {}

    def retrieve(
        self,
        subject: Subject,
        goal: str,
        weak_topic_ids: list[str] | None = None,
        top_k: int = 8,
    ) -> RetrievalResult:
        """Retrieve goal-relevant topics/resources for prompt grounding."""
        if top_k < 1:
            raise ValueError("top_k must be at least 1")
        graph = load_topic_graph(subject)
        by_id = graph.by_id()
        weak_ids = list(dict.fromkeys(weak_topic_ids or []))
        unknown = set(weak_ids) - by_id.keys()
        if unknown:
            raise ValueError(f"Weak-topic IDs are unknown: {sorted(unknown)}")
        documents = self._subject_documents(subject)
        weak_text = " ".join(
            f"{by_id[topic_id].name} {by_id[topic_id].description}" for topic_id in weak_ids
        )
        query = f"{goal} {weak_text}".strip()
        vectors = self._get_vectors(subject, documents)
        if vectors is not None:
            try:
                scores = self._embedding_scores(query, documents, vectors)
                backend: Literal["embeddings", "lexical"] = "embeddings"
            except (OSError, RuntimeError, ValueError, TypeError) as exc:
                self._embedding_failure = str(exc)
                LOGGER.warning("Embedding query failed; using lexical ranking: %s", exc)
                scores = self._lexical_scores(query, documents)
                backend = "lexical"
        else:
            scores = self._lexical_scores(query, documents)
            backend = "lexical"
        ranked = sorted(
            zip(documents, scores, strict=True),
            key=lambda pair: (-pair[1], pair[0].document_id),
        )
        topic_scores: dict[str, float] = {}
        resource_scores: list[tuple[Resource, float]] = []
        for document, score in ranked:
            if document.kind == "topic":
                topic_scores[document.topic_id] = max(topic_scores.get(document.topic_id, 0), score)
            elif document.resource is not None:
                resource_scores.append((document.resource, score))
        for topic_id in weak_ids:
            topic_scores[topic_id] = max(topic_scores.get(topic_id, 0), 1.0)
        topic_lookup = by_id
        topic_candidates = [
            TopicCandidate(topic=topic_lookup[topic_id], score=score)
            for topic_id, score in sorted(
                topic_scores.items(), key=lambda pair: (-pair[1], pair[0])
            )[:top_k]
        ]
        resource_candidates = [
            ResourceCandidate(resource=resource, score=score)
            for resource, score in resource_scores[:top_k]
        ]
        return RetrievalResult(
            topics=topic_candidates,
            resources=resource_candidates,
            backend=backend,
            model=self.model_name if backend == "embeddings" else "lexical-fallback",
        )

    def _subject_documents(self, subject: Subject) -> tuple[_Document, ...]:
        if subject in self._documents:
            return self._documents[subject]
        graph = load_topic_graph(subject)
        topic_ids = set(graph.by_id())
        documents: list[_Document] = []
        for topic in graph.topics:
            documents.append(
                _Document(
                    document_id=f"topic:{topic.id}",
                    kind="topic",
                    topic_id=topic.id,
                    text=f"{topic.name}. {topic.description}. {' '.join(topic.tags)}",
                    topic=topic,
                )
            )
        for index, resource in enumerate(load_resources()):
            if resource.topic_id not in topic_ids:
                continue
            documents.append(
                _Document(
                    document_id=f"resource:{resource.topic_id}:{index}",
                    kind="resource",
                    topic_id=resource.topic_id,
                    text=f"{resource.title}. {resource.type}. {resource.url}",
                    resource=resource,
                )
            )
        self._documents[subject] = tuple(documents)
        return self._documents[subject]

    def _get_vectors(
        self, subject: Subject, documents: tuple[_Document, ...]
    ) -> list[list[float]] | None:
        if not self.enable_embeddings:
            return None
        model = self._get_model()
        if model is None:
            return None
        cache_path = self._cache_path(subject, documents)
        try:
            cached = json.loads(cache_path.read_text(encoding="utf-8"))
            vectors = cached["vectors"]
            if cached["document_ids"] == [document.document_id for document in documents]:
                self._vectors[subject] = vectors
                return vectors
        except (OSError, json.JSONDecodeError, KeyError, TypeError):
            pass
        try:
            vectors = self._encode(model, [document.text for document in documents])
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            cache_path.write_text(
                json.dumps(
                    {
                        "model": self.model_name,
                        "document_ids": [document.document_id for document in documents],
                        "vectors": vectors,
                    },
                    separators=(",", ":"),
                ),
                encoding="utf-8",
            )
        except (OSError, RuntimeError, ValueError, TypeError) as exc:
            self._embedding_failure = str(exc)
            LOGGER.warning("Embedding retrieval unavailable; using lexical ranking: %s", exc)
            return None
        self._vectors[subject] = vectors
        return vectors

    def _get_model(self) -> Any | None:
        if self._model is not None:
            return self._model
        if self._embedding_failure is not None:
            return None
        try:
            from sentence_transformers import SentenceTransformer

            self._model = SentenceTransformer(self.model_name, device="cpu")
        except (ImportError, OSError, RuntimeError, ValueError) as exc:
            self._embedding_failure = str(exc)
            LOGGER.warning("Embedding model unavailable; using lexical ranking: %s", exc)
            return None
        return self._model

    def _cache_path(self, subject: Subject, documents: tuple[_Document, ...]) -> Path:
        content = "\n".join(document.text for document in documents)
        digest = hashlib.sha256(f"{self.model_name}\n{content}".encode()).hexdigest()[:20]
        return self.cache_dir / f"{subject}-{digest}.json"

    @staticmethod
    def _encode(model: Any, texts: list[str]) -> list[list[float]]:
        encoded = model.encode(texts, normalize_embeddings=True, show_progress_bar=False)
        return [[float(value) for value in row] for row in encoded.tolist()]

    def _embedding_scores(
        self,
        query: str,
        documents: tuple[_Document, ...],
        vectors: list[list[float]],
    ) -> list[float]:
        model = self._get_model()
        if model is None:
            raise RuntimeError("Embedding model became unavailable after index creation")
        query_vector = self._encode(model, [query])[0]
        return [
            sum(left * right for left, right in zip(query_vector, row, strict=True))
            for row in vectors
        ]

    @staticmethod
    def _lexical_scores(query: str, documents: tuple[_Document, ...]) -> list[float]:
        query_terms = set(_tokens(query))
        if not query_terms:
            query_terms = {"learning"}
        scores = []
        for document in documents:
            terms = set(_tokens(document.text))
            overlap = len(query_terms & terms)
            coverage = overlap / len(query_terms)
            jaccard = overlap / len(query_terms | terms) if terms else 0
            scores.append(coverage * 0.8 + jaccard * 0.2)
        return scores


def _tokens(text: str) -> list[str]:
    normalized = "".join(c.lower() if c.isalnum() else " " for c in text)
    return [token for token in normalized.split() if len(token) > 2]


_DEFAULT_RETRIEVER = Retriever()


def retrieve_resources(
    subject: Subject,
    goal: str,
    weak_topic_ids: list[str] | None = None,
    top_k: int = 8,
) -> RetrievalResult:
    """Return allowlisted topic and resource candidates relevant to a learning goal."""
    return _DEFAULT_RETRIEVER.retrieve(subject, goal, weak_topic_ids, top_k)
