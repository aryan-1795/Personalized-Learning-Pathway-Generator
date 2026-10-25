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

## 0005 — Treat the curated knowledge files as validated application data
- **Decision:** Store each subject as a JSON prerequisite DAG and maintain a separate resource allowlist; validate identifiers, edges, uniqueness, and cycles at load time with Pydantic v2.
- **Alternatives:** Embed knowledge directly in Python; trust graph/resource JSON without validation.
- **Why:** Curators can review content without changing code, while generation and retrieval can only use known topic IDs and catalog links.

## 0006 — Use a balanced staircase with cluster-level mastery smoothing
- **Decision:** Start at difficulty 3, step one level based on each answer, balance questions across four subject clusters, stop after eight questions with two observations per cluster or at twelve, and use a Beta(1,1) prior for mastery.
- **Alternatives:** Fixed-length quizzes; report zero mastery for unasked topics; use a complex IRT model without calibrated item data.
- **Why:** This is deterministic, explainable, and gives a usable estimate for every topic while clearly documenting that the initial quiz is diagnostic rather than psychometrically calibrated.

## 0007 — Make local and mock inference share one provider contract
- **Decision:** Keep `LLMProvider.generate` as the seam, load Transformers lazily for CPU inference, and replay queued outputs with a deterministic mock in tests.
- **Alternatives:** Couple prompt/pipeline code to Transformers; call a paid hosted model; patch generation internals in each test.
- **Why:** Provider substitution keeps orchestration testable and works without model downloads, network access, or paid credentials.

## 0008 — Validate every generated pathway and cap repairs at two
- **Decision:** Parse Pydantic output, check graph/resource/budget semantics, pass specific errors into no more than two repair calls, then use a prerequisite-first deterministic fallback. Cache only validated results by complete request/model/prompt identity.
- **Alternatives:** Trust valid JSON; retry indefinitely; return partial invalid output; use a random fallback.
- **Why:** Schema correctness alone cannot catch invented links or broken learning order, and bounded deterministic recovery keeps latency and behavior explainable.

## 0009 — Keep retrieval local, cached, and degradable
- **Decision:** Rank curated topic/resource documents with MiniLM embeddings cached by subject/content/model; if model loading or encoding fails, use deterministic lexical scoring over the same records.
- **Alternatives:** Require network-backed search; fail pathway generation when embeddings are absent; retrieve from arbitrary URLs.
- **Why:** Grounding stays bounded to reviewed data while the demo and tests remain usable offline and on CPU-only systems.
