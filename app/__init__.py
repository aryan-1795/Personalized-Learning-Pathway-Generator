"""Flask application factory and runtime service wiring."""

from __future__ import annotations

import os
from pathlib import Path
from time import perf_counter
from typing import Any

from flask import Flask, g, jsonify, render_template, request
from werkzeug.exceptions import RequestEntityTooLarge

from app.api.repository import PathwayRepository
from app.api.routes import api
from app.assessment.engine import AssessmentEngine
from app.llm.providers import HFLocalProvider, LLMProvider, MockProvider
from app.observability.events import (
    REQUEST_ID,
    configure_logging,
    emit_event,
    reset_request_id,
    set_request_id,
)
from app.pipeline.generator import PathwayGenerator


def create_app(config: dict[str, Any] | None = None) -> Flask:
    """Create a configured Flask app with isolated assessment and persistence services."""
    application = Flask(__name__, template_folder="../templates", static_folder="../static")
    application.config.from_mapping(
        DATABASE_PATH=os.getenv("DATABASE_PATH", str(Path("instance") / "pathways.sqlite3")),
        LLM_PROVIDER=os.getenv("LLM_PROVIDER", "local"),
        LLM_MODEL=os.getenv("LLM_MODEL", "Qwen/Qwen2.5-1.5B-Instruct"),
        PROMPT_VERSION=os.getenv("PROMPT_VERSION", "pathway_v2"),
        MAX_CONTENT_LENGTH=32 * 1024,
    )
    if config:
        application.config.update(config)
    configure_logging()

    @application.before_request
    def begin_request() -> None:
        g.request_id_token = set_request_id(request.headers.get("X-Request-ID"))
        g.request_started_at = perf_counter()

    @application.after_request
    def finish_request(response: Any) -> Any:
        if hasattr(g, "request_id_token"):
            request_id = REQUEST_ID.get()
            response.headers["X-Request-ID"] = request_id
            emit_event(
                "http_request",
                method=request.method,
                path=request.path,
                status_code=response.status_code,
                latency_ms=round((perf_counter() - g.request_started_at) * 1000, 3),
            )
            reset_request_id(g.request_id_token)
        else:
            token = set_request_id(request.headers.get("X-Request-ID"))
            response.headers["X-Request-ID"] = REQUEST_ID.get()
            reset_request_id(token)
        return response

    provider: LLMProvider
    if application.config["LLM_PROVIDER"] == "mock":
        provider = application.config.get("LLM_PROVIDER_INSTANCE") or MockProvider()
    elif application.config["LLM_PROVIDER"] == "local":
        provider = application.config.get("LLM_PROVIDER_INSTANCE") or HFLocalProvider(
            application.config["LLM_MODEL"]
        )
    else:
        raise ValueError("LLM_PROVIDER must be either 'local' or 'mock'")

    application.extensions["llm_provider"] = provider
    application.extensions["assessment_engine"] = AssessmentEngine()
    application.extensions["pathway_generator"] = PathwayGenerator(
        provider, prompt_version=application.config["PROMPT_VERSION"]
    )
    application.extensions["pathway_repository"] = PathwayRepository(
        application.config["DATABASE_PATH"]
    )
    application.register_blueprint(api)

    @application.get("/")
    def index() -> str:
        return render_template("index.html")

    @application.errorhandler(404)
    def not_found(_error: Any) -> Any:
        if request.path.startswith("/api/"):
            payload = {"error": {"code": "not_found", "message": "Resource not found."}}
            return jsonify(payload), 404
        return render_template("index.html"), 404

    @application.errorhandler(RequestEntityTooLarge)
    def request_too_large(_error: RequestEntityTooLarge) -> Any:
        return jsonify(
            {
                "error": {
                    "code": "request_too_large",
                    "message": "Request body exceeds the 32 KB limit.",
                }
            }
        ), 413

    return application


app = create_app()
