# Architecture decision record

## 0001 — Use a layered Flask application and curated local knowledge
- **Decision:** Separate API, assessment, knowledge, retrieval, LLM, pipeline, evaluation, and observability concerns under `app/`; ground generation in reviewed topic/resource catalogs.
- **Alternatives:** Put logic directly in Flask routes; allow free-form model output; use a hosted commercial inference API.
- **Why:** Layer boundaries make behavior testable and interview-explainable, the catalogs reduce hallucination risk, and local inference satisfies the no-paid-key and laptop CPU constraints.

## 0002 — Use a deterministic mock provider in tests and CI
- **Decision:** The mock implements the same provider contract as local Hugging Face inference and is the CI default.
- **Alternatives:** Download/run a real model in every test; test only with hand-crafted route stubs.
- **Why:** Tests remain offline, repeatable, fast, and able to exercise malformed and semantically invalid model outputs.

## 0003 — Begin with SQLite and defer the ORM choice
- **Decision:** Use SQLite for persistence and start with Python's standard `sqlite3`; adopt SQLAlchemy only if the implemented repository boundary benefits from it.
- **Alternatives:** Add an ORM before persistence needs are known; use a remote database.
- **Why:** The application has a small local data model, SQLite has no service dependency, and deferring an ORM keeps the initial project lean.

## 0004 — Keep embeddings and model weights lazy and locally cached
- **Decision:** Load Transformers and sentence-transformers only when their services are used, and keep downloaded artifacts outside version control.
- **Alternatives:** Load models at Flask import/startup; require cloud inference.
- **Why:** Health checks, tests, and deterministic fallback remain usable without model downloads or GPU hardware.
