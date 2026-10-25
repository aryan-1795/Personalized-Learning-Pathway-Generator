"""REST endpoints with consistent Pydantic validation and error envelopes."""

from __future__ import annotations

import logging
import uuid
from typing import Any

from flask import Blueprint, current_app, jsonify, request
from pydantic import ValidationError
from werkzeug.exceptions import BadRequest

from app.api.schemas import AssessmentAnswerRequest, AssessmentStartRequest
from app.pipeline.schemas import PathwayInput

LOGGER = logging.getLogger(__name__)
api = Blueprint("api", __name__, url_prefix="/api")


def _json_body() -> dict[str, Any]:
    if not request.is_json:
        raise ValueError("Content-Type must be application/json")
    try:
        body = request.get_json(silent=False)
    except BadRequest as exc:
        raise ValueError("Request body is not valid JSON") from exc
    if not isinstance(body, dict):
        raise ValueError("Request body must be a JSON object")
    return body


def _validate(model: type[Any], body: dict[str, Any]) -> Any:
    try:
        return model.model_validate(body)
    except ValidationError as exc:
        raise ValueError(exc.errors(include_url=False)) from exc


def _error(code: str, message: str, details: Any = None, status: int = 400) -> tuple[Any, int]:
    payload: dict[str, Any] = {"error": {"code": code, "message": message}}
    if details is not None:
        payload["error"]["details"] = details
    return jsonify(payload), status


@api.post("/assessment/start")
def assessment_start() -> tuple[Any, int] | Any:
    try:
        payload = _validate(AssessmentStartRequest, _json_body())
        session_id, question = current_app.extensions["assessment_engine"].start_assessment(
            payload.subject
        )
    except ValueError as exc:
        return _error("invalid_request", "Assessment request is invalid.", str(exc))
    return jsonify({"session_id": session_id, "question": question.model_dump()}), 200


@api.post("/assessment/answer")
def assessment_answer() -> tuple[Any, int] | Any:
    try:
        payload = _validate(AssessmentAnswerRequest, _json_body())
        step = current_app.extensions["assessment_engine"].answer(
            payload.session_id, payload.question_id, payload.selected_index
        )
    except KeyError as exc:
        return _error("not_found", "Assessment session was not found.", str(exc), 404)
    except ValueError as exc:
        return _error("invalid_request", "Assessment answer is invalid.", str(exc))
    return jsonify(step.model_dump(mode="json")), 200


@api.post("/pathway/generate")
def pathway_generate() -> tuple[Any, int] | Any:
    try:
        payload = _validate(PathwayInput, _json_body())
        result = current_app.extensions["pathway_generator"].generate_pathway(payload)
        pathway_id = str(uuid.uuid4())
        pathway_json = result.pathway.model_dump(mode="json")
        metadata_json = result.metadata.model_dump(mode="json")
        current_app.extensions["pathway_repository"].save(
            pathway_id, pathway_json, metadata_json
        )
    except ValueError as exc:
        return _error("invalid_request", "Pathway request is invalid.", str(exc))
    except Exception:
        LOGGER.exception("Pathway generation or persistence failed")
        return _error(
            "generation_failed",
            "Unable to generate or save this pathway.",
            status=500,
        )
    return jsonify({"id": pathway_id, "pathway": pathway_json, "metadata": metadata_json}), 200


@api.get("/pathway/<pathway_id>")
def pathway_get(pathway_id: str) -> tuple[Any, int] | Any:
    record = current_app.extensions["pathway_repository"].get(pathway_id)
    if record is None:
        return _error("not_found", "Pathway was not found.", status=404)
    return jsonify({"id": pathway_id, **record}), 200


@api.get("/health")
def health() -> tuple[Any, int]:
    database_healthy = current_app.extensions["pathway_repository"].is_healthy()
    payload = {"status": "ok" if database_healthy else "degraded", "database": database_healthy}
    return jsonify(payload), 200 if database_healthy else 503
