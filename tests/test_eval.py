from __future__ import annotations

from app.eval.run import _run_comparison, load_profiles, render_markdown
from app.knowledge.loader import load_topic_graph


def test_evaluation_profiles_cover_all_subjects_and_complete_mastery_vectors() -> None:
    profiles = load_profiles()
    assert len(profiles) == 20
    for subject in ("python", "dsa", "machine_learning", "web_development"):
        selected = [profile for profile in profiles if profile["subject"] == subject]
        assert len(selected) == 5
        topic_ids = {topic.id for topic in load_topic_graph(subject).topics}
        assert all(set(profile["mastery"]) == topic_ids for profile in selected)


def test_mock_evaluation_measures_success_repair_fallback_and_safety_rates() -> None:
    result = _run_comparison("mock-fixture", "pathway_v2", load_profiles())
    metrics = result["metrics"]
    assert result["profile_count"] == 20
    assert metrics["schema_validity_rate_first_try"] == 0.7
    assert metrics["repair_rate"] == 0.2
    assert metrics["fallback_rate"] == 0.2
    assert metrics["prerequisite_order_violation_rate_first_try"] == 0.0
    assert metrics["hallucinated_topic_or_url_rate_first_try"] == 0.1
    assert metrics["time_budget_compliance_rate_final"] == 1.0
    assert metrics["mean_latency_ms"] > 0


def test_markdown_table_formats_rates_as_percentages() -> None:
    result = _run_comparison("mock-fixture", "pathway_v1", load_profiles())
    markdown = render_markdown([result])
    assert "70.0%" in markdown
    assert "100.0%" in markdown
    assert "Mean latency ms" in markdown
