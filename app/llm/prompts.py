"""Versioned prompt loading and rendering helpers."""

from __future__ import annotations

from pathlib import Path

PROMPT_DIR = Path(__file__).resolve().parent / "prompts"
SUPPORTED_PROMPTS = {"pathway_v1", "pathway_v2"}


def load_prompt(version: str) -> str:
    """Load a checked-in prompt template by stable version identifier."""
    if version not in SUPPORTED_PROMPTS:
        raise ValueError(f"Unsupported prompt version: {version}")
    return (PROMPT_DIR / f"{version}.md").read_text(encoding="utf-8")


def render_prompt(version: str, context: str, goal: str) -> str:
    """Fill context and delimited untrusted goal fields in a prompt template."""
    template = load_prompt(version)
    return template.replace("{{CONTEXT}}", context).replace("{{GOAL}}", goal)
