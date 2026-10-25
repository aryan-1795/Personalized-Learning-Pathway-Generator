"""Flask application factory and runtime service wiring."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from flask import Flask, jsonify, render_template, request

from app.api.repository import PathwayRepository
from app.api.routes import api
from app.assessment.engine import AssessmentEngine
from app.llm.providers import HFLocalProvider, LLMProvider, MockProvider
from app.pipeline.generator import PathwayGenerator


def create_app(config: dict[str, Any] | None = None) -> Flask:
    """Create a configured Flask app with isolated assessment and persistence services."""
    application = Flask(__name__, template_folder="../templates", static_folder="../static")
    application.config.from_mapping(
        DATABASE_PATH=os.getenv("DATABASE_PATH", str(Path("instance") / "pathways.sqlite3")),
        LLM_PROVIDER=os.getenv("LLM_PROVIDER", "local"),
        LLM_MODEL=os.getenv("LLM_MODEL", "Qwen/Qwen2.5-1.5B-Instruct"),
        PROMPT_VERSION=os.getenv("PROMPT_VERSION", "pathway_v2"),
    )
    if config:
        application.config.update(config)

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

    return application


app = create_app()
