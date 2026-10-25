from __future__ import annotations

import pytest
from app.assessment.engine import (
    AssessLevelInput,
    AssessmentEngine,
    assess_level,
    load_question_bank,
)
from app.knowledge.loader import load_topic_graph


def test_question_bank_has_eight_questions_per_subject_cluster() -> None:
    questions = load_question_bank()
    counts: dict[tuple[str, str], int] = {}
    for question in questions:
        key = (question.subject, question.topic_cluster)
        counts[key] = counts.get(key, 0) + 1
    assert len(counts) == 16
    assert all(count >= 8 for count in counts.values())


def test_start_returns_medium_question_without_answer_key() -> None:
    session_id, question = AssessmentEngine().start_assessment("python")
    assert session_id
    assert question.difficulty == 3
    assert not hasattr(question, "correct_index")


def test_staircase_increases_after_correct_and_decreases_after_incorrect() -> None:
    engine = AssessmentEngine()
    session_id, first = engine.start_assessment("python")
    bank = {item.id: item for item in load_question_bank()}
    next_step = engine.answer(session_id, first.id, bank[first.id].correct_index)
    assert next_step.question is not None
    assert next_step.question.difficulty == 4

    second_engine = AssessmentEngine()
    other_session, first_again = second_engine.start_assessment("python")
    wrong_index = (bank[first_again.id].correct_index + 1) % 4
    next_wrong = second_engine.answer(other_session, first_again.id, wrong_index)
    assert next_wrong.question is not None
    assert next_wrong.question.difficulty == 2


def test_two_answers_per_cluster_end_at_eight_with_full_mastery_report() -> None:
    engine = AssessmentEngine()
    session_id, question = engine.start_assessment("dsa")
    step = None
    bank = {item.id: item for item in load_question_bank()}
    while step is None or not step.done:
        item = bank[question.id]
        step = engine.answer(session_id, question.id, item.correct_index)
        if step.question is not None:
            question = step.question
    assert step.report is not None
    assert step.report.questions_answered == 8
    assert len(step.report.mastery) == len(load_topic_graph("dsa").topics)
    assert step.report.overall_level == "advanced"
    assert all(0 <= score <= 1 for score in step.report.mastery.values())


def test_rejects_wrong_active_question_and_out_of_range_answer() -> None:
    engine = AssessmentEngine()
    session_id, question = engine.start_assessment("web_development")
    with pytest.raises(ValueError, match="active"):
        engine.answer(session_id, "not-active", 0)
    with pytest.raises(ValueError, match="outside"):
        engine.answer(session_id, question.id, 100)


def test_unknown_assessment_session_is_rejected() -> None:
    with pytest.raises(KeyError, match="not found"):
        AssessmentEngine().answer("missing", "q", 0)


def test_assess_level_tool_returns_full_typed_report() -> None:
    report = assess_level(AssessLevelInput(subject="python", mastery={}, questions_answered=0))
    assert report.overall_level == "intermediate"
    assert len(report.mastery) == len(load_topic_graph("python").topics)
    assert set(report.mastery.values()) == {0.5}


def test_assess_level_rejects_unknown_or_out_of_range_mastery() -> None:
    with pytest.raises(ValueError, match="unknown topic"):
        assess_level(
            AssessLevelInput(
                subject="python", mastery={"not-real": 0.5}, questions_answered=1
            )
        )
    with pytest.raises(ValueError, match="between 0 and 1"):
        assess_level(
            AssessLevelInput(
                subject="python",
                mastery={"variables-and-basic-types": 2},
                questions_answered=1,
            )
        )


def test_maximum_question_cap_stops_session() -> None:
    engine = AssessmentEngine(max_questions=4, min_questions=4)
    session_id, question = engine.start_assessment("machine_learning")
    bank = {item.id: item for item in load_question_bank()}
    for _ in range(4):
        step = engine.answer(session_id, question.id, bank[question.id].correct_index)
        if step.done:
            break
        assert step.question is not None
        question = step.question
    assert step.done
    assert step.report is not None
    assert step.report.questions_answered == 4
