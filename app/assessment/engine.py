"""Deterministic adaptive quiz selection and mastery scoring."""

from __future__ import annotations

import json
import uuid
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.knowledge.loader import Subject, load_topic_graph

BANK_PATH = Path(__file__).resolve().parents[1] / "knowledge" / "question_bank.json"


class Question(BaseModel):
    """A scored multiple-choice item linked to a curated topic."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str
    subject: Subject
    topic_cluster: str
    topic_id: str
    difficulty: int = Field(ge=1, le=5)
    prompt: str = Field(min_length=1)
    options: list[str] = Field(min_length=2)
    correct_index: int = Field(ge=0)
    explanation: str = Field(min_length=1)

    @model_validator(mode="after")
    def answer_key_in_range(self) -> Question:
        if self.correct_index >= len(self.options):
            raise ValueError("correct_index must refer to an available option")
        return self


class PublicQuestion(BaseModel):
    """Question payload safe to return to a learner; excludes answer keys."""

    id: str
    topic_cluster: str
    difficulty: int
    prompt: str
    options: list[str]


class AssessmentReport(BaseModel):
    """Per-topic mastery estimate and overall learner level."""

    subject: Subject
    mastery: dict[str, float]
    overall_level: Literal["beginner", "intermediate", "advanced"]
    questions_answered: int


class AssessmentStep(BaseModel):
    """One adaptive assessment response containing another item or final report."""

    question: PublicQuestion | None = None
    report: AssessmentReport | None = None
    explanation: str | None = None
    correct: bool | None = None
    done: bool


@dataclass
class _Session:
    subject: Subject
    questions: tuple[Question, ...]
    current_question_id: str | None = None
    current_difficulty: int = 3
    answers: dict[str, bool] = field(default_factory=dict)
    asked_ids: set[str] = field(default_factory=set)
    topic_counts: Counter[str] = field(default_factory=Counter)
    cluster_counts: Counter[str] = field(default_factory=Counter)


@lru_cache(maxsize=1)
def load_question_bank() -> tuple[Question, ...]:
    """Load and validate question data, rejecting broken topic references."""
    try:
        payload = json.loads(BANK_PATH.read_text(encoding="utf-8"))
        questions = tuple(Question.model_validate(item) for item in payload)
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Unable to load question bank: {exc}") from exc
    ids = [question.id for question in questions]
    if len(ids) != len(set(ids)):
        raise ValueError("Question IDs must be unique")
    for question in questions:
        if question.correct_index >= len(question.options):
            raise ValueError(f"Question {question.id} has an out-of-range answer key")
        if question.topic_id not in load_topic_graph(question.subject).by_id():
            raise ValueError(f"Question {question.id} refers to an unknown topic")
    clusters = defaultdict(list)
    for question in questions:
        clusters[(question.subject, question.topic_cluster)].append(question)
    if any(len(items) < 8 for items in clusters.values()):
        raise ValueError("Each subject topic cluster must contain at least eight questions")
    return questions


class AssessmentEngine:
    """Start and score server-owned adaptive quiz sessions deterministically."""

    def __init__(self, max_questions: int = 12, min_questions: int = 8) -> None:
        if max_questions < min_questions or min_questions < 1:
            raise ValueError("max_questions must be >= min_questions >= 1")
        self.max_questions = max_questions
        self.min_questions = min_questions
        self._sessions: dict[str, _Session] = {}
        self._bank = load_question_bank()

    def start_assessment(self, subject: Subject) -> tuple[str, PublicQuestion]:
        """Create a quiz session and return its first medium-difficulty item."""
        questions = tuple(question for question in self._bank if question.subject == subject)
        if not questions:
            raise ValueError(f"No assessment questions available for {subject}")
        session_id = str(uuid.uuid4())
        session = _Session(subject=subject, questions=questions)
        self._sessions[session_id] = session
        question = self._select_next(session)
        return session_id, self._public(question)

    def answer(self, session_id: str, question_id: str, selected_index: int) -> AssessmentStep:
        """Score an answer, adapt difficulty, then return the next item or report."""
        session = self._sessions.get(session_id)
        if session is None:
            raise KeyError("Assessment session not found")
        if session.current_question_id != question_id:
            raise ValueError("Question does not match the active assessment item")
        question = next(item for item in session.questions if item.id == question_id)
        if not 0 <= selected_index < len(question.options):
            raise ValueError("Selected answer is outside the question's options")
        is_correct = selected_index == question.correct_index
        session.answers[question_id] = is_correct
        session.asked_ids.add(question_id)
        session.topic_counts[question.topic_id] += 1
        session.cluster_counts[question.topic_cluster] += 1
        session.current_difficulty = max(
            1, min(5, session.current_difficulty + (1 if is_correct else -1))
        )
        if self._is_complete(session):
            return AssessmentStep(
                report=self._report(session),
                explanation=question.explanation,
                correct=is_correct,
                done=True,
            )
        next_question = self._select_next(session)
        return AssessmentStep(
            question=self._public(next_question),
            explanation=question.explanation,
            correct=is_correct,
            done=False,
        )

    def _is_complete(self, session: _Session) -> bool:
        clusters = {question.topic_cluster for question in session.questions}
        evidence_ready = len(session.answers) >= self.min_questions and all(
            session.cluster_counts[cluster] >= 2 for cluster in clusters
        )
        return len(session.answers) >= self.max_questions or evidence_ready

    @staticmethod
    def _public(question: Question) -> PublicQuestion:
        return PublicQuestion(
            id=question.id,
            topic_cluster=question.topic_cluster,
            difficulty=question.difficulty,
            prompt=question.prompt,
            options=question.options,
        )

    def _select_next(self, session: _Session) -> Question:
        remaining = [
            question
            for question in session.questions
            if question.id not in session.asked_ids
        ]
        if not remaining:
            raise RuntimeError("Question bank exhausted before stopping criteria")
        min_cluster_count = min(session.cluster_counts[q.topic_cluster] for q in remaining)
        remaining = [
            q for q in remaining if session.cluster_counts[q.topic_cluster] == min_cluster_count
        ]
        min_topic_count = min(session.topic_counts[q.topic_id] for q in remaining)
        remaining = [q for q in remaining if session.topic_counts[q.topic_id] == min_topic_count]
        selected = min(
            remaining,
            key=lambda q: (abs(q.difficulty - session.current_difficulty), q.id),
        )
        session.current_question_id = selected.id
        return selected

    def _report(self, session: _Session) -> AssessmentReport:
        clusters = sorted({question.topic_cluster for question in session.questions})
        cluster_correct = Counter()
        for question in session.questions:
            if question.id in session.answers and session.answers[question.id]:
                cluster_correct[question.topic_cluster] += 1
        cluster_mastery = {
            cluster: (cluster_correct[cluster] + 1) / (session.cluster_counts[cluster] + 2)
            for cluster in clusters
        }
        topic_cluster = {
            question.topic_id: question.topic_cluster for question in session.questions
        }
        mastery = {
            topic.id: round(cluster_mastery[topic_cluster.get(topic.id, clusters[0])], 3)
            for topic in load_topic_graph(session.subject).topics
        }
        observed_mean = sum(cluster_mastery.values()) / len(cluster_mastery)
        if observed_mean < 0.4:
            level = "beginner"
        elif observed_mean < 0.75:
            level = "intermediate"
        else:
            level = "advanced"
        return AssessmentReport(
            subject=session.subject,
            mastery=mastery,
            overall_level=level,
            questions_answered=len(session.answers),
        )
