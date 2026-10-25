"""LLM provider contract and CPU-local Hugging Face implementation."""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from threading import Lock
from typing import Any


class LLMProvider(ABC):
    """Generate text constrained by a requested structured-output schema."""

    model_name: str

    @abstractmethod
    def generate(
        self,
        messages: list[dict[str, str]],
        schema: type[Any],
        **params: Any,
    ) -> str:
        """Return generated text for chat messages and a Pydantic output schema."""


class HFLocalProvider(LLMProvider):
    """Run a Transformers text-generation pipeline with lazy singleton loading."""

    _pipeline: Any = None
    _load_lock = Lock()

    def __init__(self, model_name: str = "Qwen/Qwen2.5-1.5B-Instruct") -> None:
        self.model_name = model_name

    def _get_pipeline(self) -> Any:
        if self.__class__._pipeline is None:
            with self.__class__._load_lock:
                if self.__class__._pipeline is None:
                    try:
                        from transformers import pipeline
                    except ImportError as exc:
                        raise RuntimeError(
                            "Install the local inference dependencies to use HFLocalProvider"
                        ) from exc
                    self.__class__._pipeline = pipeline(
                        "text-generation",
                        model=self.model_name,
                        device_map="cpu",
                    )
        return self.__class__._pipeline

    def generate(
        self,
        messages: list[dict[str, str]],
        schema: type[Any],
        **params: Any,
    ) -> str:
        schema_json = json.dumps(schema.model_json_schema(), ensure_ascii=False)
        constrained_messages = [
            {
                "role": "system",
                "content": f"Return valid JSON matching this schema exactly: {schema_json}",
            },
            *messages,
        ]
        generator = self._get_pipeline()
        result = generator(
            constrained_messages,
            max_new_tokens=params.get("max_new_tokens", 1200),
            do_sample=params.get("do_sample", False),
            return_full_text=False,
        )
        return str(result[0]["generated_text"])


class MockProvider(LLMProvider):
    """Replay deterministic outputs for tests or return a fixed configured response."""

    def __init__(self, responses: list[str] | None = None, model_name: str = "mock") -> None:
        self.model_name = model_name
        self.responses = list(responses or [])
        self.calls: list[list[dict[str, str]]] = []
        self.schemas: list[type[Any]] = []

    def generate(
        self,
        messages: list[dict[str, str]],
        schema: type[Any],
        **params: Any,
    ) -> str:
        self.calls.append(messages)
        self.schemas.append(schema)
        if not self.responses:
            raise RuntimeError("MockProvider has no queued response")
        return self.responses.pop(0)
