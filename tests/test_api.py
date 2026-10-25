from __future__ import annotations

from pathlib import Path

import pytest
from app import create_app


@pytest.fixture
def client(tmp_path: Path):
    application = create_app(
        {
            "TESTING": True,
            "LLM_PROVIDER": "mock",
            "DATABASE_PATH": str(tmp_path / "pathways.sqlite3"),
        }
    )
    return application.test_client()


def test_homepage_renders_learning_pathway_ui(client) -> None:
    response = client.get("/")
    assert response.status_code == 200
    assert b"Learning Pathway Generator" in response.data
    assert b"How this was generated" in response.data


def test_health_reports_database_status(client) -> None:
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.get_json() == {"status": "ok", "database": True}


def test_assessment_start_and_answer(client) -> None:
    started = client.post("/api/assessment/start", json={"subject": "python"})
    assert started.status_code == 200
    payload = started.get_json()
    assert payload["session_id"]
    assert "correct_index" not in payload["question"]

    answered = client.post(
        "/api/assessment/answer",
        json={
            "session_id": payload["session_id"],
            "question_id": payload["question"]["id"],
            "selected_index": 0,
        },
    )
    assert answered.status_code == 200
    answer_payload = answered.get_json()
    assert answer_payload["correct"] in (True, False)
    assert answer_payload["question"] or answer_payload["report"]


def test_invalid_request_uses_consistent_json_error(client) -> None:
    response = client.post("/api/assessment/start", json={"subject": "cobol"})
    assert response.status_code == 400
    assert response.get_json()["error"]["code"] == "invalid_request"


def test_bad_json_and_wrong_content_type_use_consistent_error(client) -> None:
    malformed = client.post(
        "/api/assessment/start", data="{invalid", content_type="application/json"
    )
    wrong_type = client.post("/api/assessment/start", data="{}", content_type="text/plain")
    assert malformed.status_code == 400
    assert malformed.get_json()["error"]["code"] == "invalid_request"
    assert wrong_type.status_code == 400
    assert wrong_type.get_json()["error"]["code"] == "invalid_request"


def test_pathway_generation_persists_and_can_be_retrieved(client) -> None:
    generated = client.post(
        "/api/pathway/generate",
        json={
            "subject": "python",
            "goal": "Prepare for a Python interview",
            "mastery": {},
            "budget_hours": 8,
        },
    )
    assert generated.status_code == 200
    body = generated.get_json()
    assert body["metadata"]["source"] == "fallback"
    assert body["pathway"]["subject"] == "python"
    retrieved = client.get(f"/api/pathway/{body['id']}")
    assert retrieved.status_code == 200
    assert retrieved.get_json()["pathway"] == body["pathway"]


def test_missing_pathway_and_unknown_api_route_return_json_404(client) -> None:
    missing = client.get("/api/pathway/missing")
    unknown = client.get("/api/not-a-route")
    assert missing.status_code == 404
    assert unknown.status_code == 404
    assert missing.get_json()["error"]["code"] == "not_found"
    assert unknown.get_json()["error"]["code"] == "not_found"
