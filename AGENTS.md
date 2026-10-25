# Repository conventions

## Project layout
Domain code lives under `app/` in the layer described in `docs/SPEC.md`. Keep API wiring thin. Keep topic and resource knowledge in reviewed JSON files. Templates and static assets live outside the Python package. Tests mirror the package layout under `tests/`.

## Development setup

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt -r requirements-dev.txt
```

Set `LLM_PROVIDER=mock` for deterministic offline development and CI. Local Hugging Face inference is configured by `LLM_MODEL` and may download model weights on first use. Tests must not require model downloads, paid API keys, or network access.

## Quality checks

```powershell
ruff check .
pytest
```

Add focused tests alongside every module or behavior change. Keep assessment, knowledge, and pipeline coverage at or above 85%. Use deterministic fixtures and the mock provider. Do not change evaluation fixtures or expected metrics merely to make results look better; explain and record meaningful changes in `docs/DECISIONS.md` and `docs/EVAL.md`.

## Code conventions
- Require Python 3.11+ and type hints on public functions.
- Keep functions small, documented, and focused; prefer explicit data contracts.
- Validate external input at boundaries with Pydantic v2.
- Keep provider/model loading lazy and injectable.
- Ground generated topics and links in the knowledge catalog; never bypass semantic validation.
- Use structured logging and avoid logging secrets or raw sensitive data.
- Preserve stable API error envelopes and document contract changes in `docs/SPEC.md`.

## Agent rules
- Read `docs/SPEC.md` and `docs/DECISIONS.md` before implementation; the spec is authoritative.
- Work through all milestones requested by the user; keep milestone commits separate and summarize when the requested sequence is complete. Stop after one milestone only when the user explicitly asks for a pause.
- Update the spec and decision log when architecture, contracts, defaults, or algorithms change.
- Write and run relevant tests before moving to the next milestone; do not hide failures.
- Do not invent evaluation results. Label mock runs and real-model runs accurately.
- Do not commit downloaded weights, caches, secrets, local databases, or generated model artifacts.
- Commit each completed milestone separately, with a concise descriptive message. Do not rewrite unrelated history or discard user changes.
