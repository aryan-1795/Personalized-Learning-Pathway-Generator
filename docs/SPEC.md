# Learning Pathway Generator — Specification

## Problem
Learners often need a structured next-step plan but do not know which concepts they already understand, what prerequisites they are missing, or which resources to trust. This project provides an adaptive diagnostic quiz and a personalized, explainable roadmap grounded in a small curated knowledge base.

## Goals
- Deliver a working Flask application for Python, Data Structures & Algorithms (DSA), Machine Learning basics, and Web Development.
- Estimate per-topic mastery with a deterministic adaptive assessment.
- Generate an ordered pathway with prerequisites, hours, resources, practice tasks, and checkpoints.
- Ground generated content in curated topic and resource catalogs; reject ungrounded output.
- Run locally on laptop CPU without paid API credentials. A configurable local Hugging Face instruct model is the default LLM; a deterministic mock supports CI and offline tests.
- Expose typed, documented core functions and REST endpoints, with transparent provenance and validation outcomes.
- Measure pathway quality using a repeatable evaluation harness and report actual results.

## Non-goals
- Replacing a full learning management system or providing user accounts/social features.
- Claiming that mastery estimates are psychometrically calibrated; this is a lightweight learning aid.
- Browsing arbitrary resources or accepting LLM-invented topics and URLs.
- Cloud-hosted inference, paid API providers, or GPU-only execution as a requirement.
- A heavy client-side framework, multi-tenant production security, or high-availability deployment.
- The MCP server is a stretch goal and is not required for the core product.

## Users and primary flow
A learner selects a subject, answers a short adaptive quiz, enters a goal and available time, then reviews an ordered roadmap. They may regenerate or adjust the roadmap (for example, a four-week timeline or interview focus). The UI shows whether generation used the LLM, repair, or deterministic fallback, plus validation information.

## Architecture
The application is divided into independently testable layers:

- `app/knowledge`: version-controlled topic DAG JSON and a resource catalog, with typed loaders and integrity checks.
- `app/assessment`: question bank, adaptive item selection, deterministic scoring, mastery report.
- `app/retrieval`: optional sentence-transformers embeddings over curated content, cached locally; returns bounded topic/resource candidates.
- `app/llm`: provider interface, lazy local Transformers provider, deterministic mock provider, versioned prompts.
- `app/pipeline`: context construction, pathway schemas, generation, semantic validation, bounded repair, deterministic fallback, caching.
- `app/api`: Flask blueprints, Pydantic request/response validation, consistent JSON errors.
- `app/eval`: fixed learner profiles, metrics, prompt/model comparison, saved reports.
- `app/observability`: structured request and model-call logs.
- `templates/` and `static/`: Jinja-rendered HTML, CSS, and plain JavaScript.
- `tests/`: unit and Flask integration tests; mock provider is used for deterministic CI.

The Flask API orchestrates services but does not own domain logic. SQLite is accessed through a repository boundary (initially the Python `sqlite3` module unless implementation needs justify SQLAlchemy). Heavy model and embedding dependencies are loaded lazily so health checks, tests, and fallback paths work without downloading model weights.

## Data contracts

### Topic
Each subject graph is a directed acyclic graph of records with `id`, `name`, `description`, `prerequisites` (topic IDs), `difficulty` (integer 1–5), `estimated_hours` (positive number), and `tags` (strings). Python and DSA require at least 25 topics each; Machine Learning basics and Web Development require about 15 each. IDs are unique within a subject and every prerequisite must exist.

### Resource
Catalog entries contain `title`, `url`, `type`, `topic_id`, and `verified` (boolean). Only catalog URLs may appear in pathway output. Unverified entries are explicitly marked and should not be represented as verified.

### Assessment
Question records include `id`, `topic_id`, `difficulty` (1–5), prompt, options, correct answer, and explanation. The report contains per-topic mastery in `[0,1]` and an overall `beginner`, `intermediate`, or `advanced` level. Assessment state is server-side and referenced by an opaque session ID; answer correctness is never accepted from the client.

### Pathway
A pathway has subject, goal, ordered phases, estimated total hours, and checkpoints. Each topic step references a known topic ID and includes a rationale, planned hours, practice task, and catalog resource references. Generation metadata records `source` (`llm_ok`, `llm_repaired`, or `fallback`), prompt version, model, latency, retry count, and validation results. Pydantic v2 models define the canonical API and pipeline contracts.

### API
- `POST /api/assessment/start`: subject; returns session ID and first question.
- `POST /api/assessment/answer`: session ID, question ID, selected answer; returns next question or mastery report.
- `POST /api/pathway/generate`: subject, mastery report, goal, and time budget; returns pathway and generation metadata.
- `GET /api/pathway/<id>`: reads a persisted pathway.
- `GET /api/health`: lightweight health status without forcing model downloads.

Requests are length-bounded and validated. Errors share an envelope such as `{"error":{"code":"...","message":"...","details":...}}` and use appropriate HTTP status codes.

## Assessment algorithm
Each subject has four ordered topic clusters and at least eight items per cluster. Start at difficulty 3 (medium). Correct answers increase the next target difficulty by one; incorrect answers decrease it by one, bounded to 1–5. Selection balances evidence across clusters, then topics, and chooses the remaining item closest to the current target difficulty; IDs break ties deterministically. Stop at 12 questions, or after at least 8 questions once each cluster has at least two answers. Per-cluster mastery uses a Beta(1,1) smoothing prior: `(correct + 1) / (answered + 2)`. That estimate is assigned to topics in the cluster, including unasked topics. Overall level is `beginner` below 0.40 mean mastery, `intermediate` from 0.40 to below 0.75, and `advanced` at or above 0.75. The question bank is curated from each topic's concise description so every item remains anchored to the graph; it is an initial diagnostic, not a calibrated exam.

## Retrieval and context budget
Use `sentence-transformers/all-MiniLM-L6-v2` for local embeddings, with a disk cache keyed by content and embedding model version. Retrieval ranks only catalog topic/resource records against goal text and weak-topic descriptions. Context includes a compact allowlisted set of retrieved graph nodes, their prerequisite edges, mastery values, and catalog resources. The prompt builder ranks candidates deterministically and enforces its 8,000-character budget (about 2,000 tokens at the conservative four-characters-per-token estimate), retaining prerequisite closure where possible. Raw learner goal text is sanitized, delimited, and treated as untrusted. Model output cannot expand the allowlist.

## Generation and validation
1. Build bounded context and call the provider with a versioned prompt and JSON schema.
2. Parse and validate against Pydantic schemas.
3. Semantically validate topic existence, uniqueness, prerequisite order, catalog-only URLs, time-budget compliance, and handling of topics with mastery above 0.85 (skip or mark as review).
4. On invalid output, issue a repair prompt containing specific validation errors, at most two retries.
5. If output remains invalid or local inference fails, produce a deterministic pathway using a prerequisite-respecting topological ordering weighted toward mastery gaps, then validate it.
6. Record provenance (`llm_ok`, `llm_repaired`, `fallback`); never return unvalidated model output.

Time budget is a hard ceiling for planned pathway hours. If mandatory prerequisites exceed it, include the highest-priority feasible prerequisite-respecting subset and report omitted work explicitly rather than silently exceeding the budget.

## Failure modes and handling
- Missing/corrupt knowledge or question data: fail startup/service operation with a clear structured log/error; do not generate from incomplete grounding.
- Local model missing, unavailable, or out of memory: log the failure and use deterministic fallback; model loading is lazy.
- Malformed JSON, schema errors, invented topic/resource, bad order, or budget overrun: repair up to two times, then fallback.
- Embedding package/model unavailable: use deterministic lexical retrieval over the same curated catalog and record degraded retrieval status.
- Invalid/oversized API input or prompt-injection-like goal text: reject length/schema violations, delimit the accepted text, and instruct the model to ignore embedded instructions.
- SQLite unavailable or persistence error: return a consistent server error; do not claim that an unsaved pathway can later be fetched.
- Cache key collision/stale output: include subject, normalized mastery vector, goal, budget, prompt version, model/config version in the key; cache only validated pathways.

## Safety and observability
Free-text goals are untrusted data. Normalize whitespace, enforce length bounds, delimit in prompts, and explicitly instruct the model to treat goal content as data rather than instructions. Structured JSON logs include request ID, prompt version, model, input/output token counts when available, latency, validation result, retries, and source. Do not log secrets or unnecessary personal data. Cache validated results by a stable hash of all generation inputs.

## Evaluation
A fixed set of approximately 20 learner profiles runs through the generation pipeline. Report first-pass schema validity, repair rate, fallback rate, prerequisite-order violations, hallucinated topic/URL rate, time-budget compliance, and mean latency. Save machine-readable results under `eval/results/`; `docs/EVAL.md` must describe actual runs and actual numbers, including failures and changes. Never fabricate metrics. CI uses the mock provider; local real-model evaluation is explicitly identified as such and records model/prompt versions.

## Constraints and defaults
- Python 3.11 or newer; Flask, Pydantic v2, Transformers, sentence-transformers, pytest, and Ruff.
- Default local model: `Qwen/Qwen2.5-1.5B-Instruct`, override with `LLM_MODEL`; provider selection is configurable for mock/local execution.
- SQLite persistence; local model/embedding files and evaluation output are not committed.
- CPU operation is supported; inference may be slow and model download requires network access on first use. No paid API key is required.

## Milestones
1. Specification, agent/repository rules, skeleton, tooling.
2. Knowledge graphs/catalog/loaders/tests.
3. Assessment engine/tests.
4. Provider interface, mock provider, prompt templates.
5. Generation pipeline, validators, repair, fallback/tests.
6. Retrieval layer.
7. Flask API and frontend.
8. Evaluation harness and real evaluation run/report.
9. Observability, guardrails, injection tests.
10. README polish, CI, optional MCP server.

Each milestone is committed independently. Work stops after each milestone for a concise progress summary.
