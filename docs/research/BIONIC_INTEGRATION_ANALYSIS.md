# Bionic Integration Analysis

- **Status:** source-code audit; integration decision pending
- **Audit date:** 2026-11-03
- **Bionic repository:** https://github.com/bionic-gpt/bionic-gpt
- **Bionic audited ref:** `main`, tree/commit `8a9797c39680ae8421bfaef72f87eb90650e7a09`
- **Personal Expert AI audited ref:** `main`, commit `157774606ccb7daba9913d6b1cc6cfc89daa16a8`
- **Scope:** architecture, runtime, model providers, RAG/document ingestion, persistence, identity/authorization, sandbox, Skills, deployment and integration boundaries.
- **Important:** this is a static source/configuration audit. No Bionic deployment, penetration test, runtime compatibility test, performance benchmark or LM Studio end-to-end test was run.

## 1. Executive summary

Bionic is not merely a chat UI. The current repository describes and implements a self-hostable Rust agentic harness with a web application, PostgreSQL persistence, model/provider configuration, document datasets and RAG, an agent request pipeline, Skills, integrations, a virtual filesystem and a mediated sandbox.

The earlier statement that Personal Expert AI already had all of these capabilities was too broad. Personal Expert AI has implemented important foundations—document storage and integrity, document extraction/OCR, provenance-bearing fragments, PostgreSQL domain schema and tenant isolation mechanisms, API authentication boundary, worker queue and an LM Studio provider adapter. It does **not** yet have a complete conversational RAG product, production identity lifecycle, general-purpose agent runtime or Skills execution platform.

**Recommendation: do not embed or adopt the whole Bionic platform as the owner of Personal Expert AI. Keep Personal Expert AI as the system of record and domain backend. Evaluate Bionic as an optional agent-runtime/UI candidate behind a narrow integration boundary, and borrow its virtual-filesystem, lazy-context, Skills and mediated-tool design even if we later build our own runtime/UI.**

The strongest potential reuse is the agent runtime and virtual filesystem—not Bionic's document database or project/tenant model. Its OpenAI-compatible provider path makes LM Studio integration plausible at the chat-completion layer, but does not prove complete LM Studio compatibility for embeddings, vision, tool calling, cancellation or local-only networking.

## 2. What was actually implemented in Personal Expert AI

This section distinguishes code already present at the audited commit from target architecture and planned work.

| Area | Implemented at audited commit | Not yet a complete capability |
|---|---|---|
| Document storage | Local file store; upload service; streaming writes; SHA-256; immutable version records; integrity verification on read; upload operation/recovery workflow; format validation | General-purpose object/file platform for every agent artifact and connector |
| Document processing | PDF/DOCX/XLSX/PPTX extraction adapters; PDF page rendering; OCR enrichment; processing worker/queue; fragments and artifacts with version/run provenance | Full engineering-grade extraction of every drawing/vector/chart/embedded object; parser sandbox with OS-level resource isolation |
| Knowledge model | Relational entities for knowledge items/assertions and source fragments; deterministic fragment identity; source locators and extraction provenance | End-to-end question answering over hybrid retrieval; production embeddings/vector index/retriever/reranker; citation validation in a live chat flow |
| Database and tenancy | PostgreSQL schema/migrations; tenant/project/document relations; composite consistency constraints; RLS policies and tenant context; integration tests for isolation | Finished production identity lifecycle and complete authorization policy across future agent tools |
| API | FastAPI health, workspace/document endpoints, authenticated document upload/download and processing endpoints | Full user-facing chat API, conversation orchestration and agent task lifecycle |
| Authentication | JWT validation boundary requiring issuer/audience/expiry/subject/tenant; active user lookup | Token issuance/refresh, password or account lifecycle, external IdP/SSO integration and full admin UI |
| LLM | Provider-neutral contracts and LM Studio OpenAI-compatible adapter for chat/streaming/embeddings/model listing/health plus explicit capability gates | Runtime wiring into an orchestrator; live LM Studio compatibility verification; reranker adapter |
| Agent runtime | Package placeholders and architectural design | General tool loop, planner, sandbox, Skills execution, tool authorization and persistent agent workspace |

Evidence in the repository includes `app/storage/file_store.py`, `app/storage/upload_service.py`, `app/processing/adapters.py`, `app/processing/pdf_enrichment.py`, `app/processing/worker.py`, `app/api/auth.py`, `app/api/routes.py`, `app/llm/contracts.py`, `app/llm/lm_studio.py`, migrations `0001`–`0007`, and `tests/integration/test_postgres_tenant_isolation.py`.

The knowledge model and target architecture documents specify intended retrieval, provenance, memory and orchestration behavior; those specifications must not be mistaken for already operational services.

## 3. Bionic source architecture

The audited repository is a Rust workspace with multiple crates. Relevant implementation areas:

| Bionic component | Source locations | Observed role |
|---|---|---|
| Web application and pages | `crates/web-server`, `crates/web-pages`, `crates/bionic-gpt` | Server-rendered application, workspace/conversation and administration UI |
| Agent request harness | `crates/agent-harness` | Loads chat/model/history, builds prompt, configures tools/moderation/limits, streams model output and persists results |
| Tool runtime | `crates/tool-runtime` | Tool definitions, connector discovery, Skills, virtual filesystem, mediated network, file and bash tools |
| Sandbox boundary | `crates/sandbox` | Provider-neutral command execution contract with caller-supplied filesystem/network capabilities; Bashkit implementation |
| Database | `crates/db`, `crates/db/migrations`, `crates/db/queries` | PostgreSQL schema and generated queries for users, teams, permissions, projects, conversations, documents, datasets, chunks, models, Skills and audit |
| RAG worker | `crates/rag-engine` | Document chunking and embedding worker |
| Object storage | `crates/object-storage` | Database-backed object storage adapter; Supabase variant is declared but currently returns “not implemented” |
| Built-in Skills | `crates/builtin-skills` | Packaged reusable task workflows |

Bionic's `agent-harness` is real application logic, not just a conceptual roadmap. Its README documents chat streaming, prompt assembly, tool definitions, moderation, usage limits, logging and persistence. `ui_chat_orchestrator.rs` implements streamed completions and scheduled chat continuation. `chat_request.rs` loads the model, conversation, history and capabilities, builds the request and prepares tools.

## 4. RAG and document pipeline comparison

### 4.1 Bionic

Bionic has a working RAG ingestion architecture:
- PostgreSQL with pgvector extension and chunk embeddings.
- `datasets`, `documents` and `chunks` tables.
- A separate `rag-engine` worker processes unprocessed documents in batches.
- Chunking can call Unstructured or Kreuzberg document services.
- Embeddings are requested through the Rig provider layer and stored as pgvector vectors.
- The tool runtime exposes dataset content to the agent through virtual paths and a dataset search route.

Relevant source: `crates/rag-engine/src/main.rs`, `config.rs`, `unstructured.rs`, `crates/db/migrations/20230807080530_documents_and_datasets.sql`, `crates/tool-runtime/builtin_tools/bashkit.rs` and `connector_network.rs`.

The current RAG pipeline is useful general-purpose document RAG. It is not equivalent to Personal Expert AI's target engineering knowledge representation: the latter needs immutable document versions, page/sheet/cell/bbox locators, structured engineering entities/assertions, cross-document conflicts and traceable evidence. Do not replace our extraction/provenance layer with Bionic's generic chunks.

### 4.2 Personal Expert AI

Personal Expert AI already has a more explicit document-version and source-provenance model, with extraction and OCR artifacts. It does not yet have the full embedding → retrieval → reranking → context assembly → grounded answer pipeline connected to user chat.

### 4.3 Decision

- **Do not use Bionic datasets/documents/chunks as the canonical project knowledge store.**
- If Bionic runtime is evaluated, expose a Personal Expert AI retrieval API/tool that returns only authorized, provenance-bearing fragments.
- Do not copy the whole project corpus into Bionic as a second index unless a measured POC proves a clear benefit and a synchronization/retention strategy is specified.
- Keep Bionic's chunk/RAG pipeline as a reference implementation or optional adapter for non-engineering datasets, not the authoritative engineering pipeline.

## 5. Identity, authorization and multi-tenancy

### 5.1 Bionic

The source includes:
- `users`, `teams`, `team_users`, invitations and role/permission structures.
- Team and project authorization paths.
- PostgreSQL row-level security setup using transaction-local `row_level_security.user_id`.
- Dataset/chat visibility and permission checks.
- OIDC/SSO configuration documented through a Kubernetes secret.
- Audit trail tables and triggers.
- API keys and OAuth connection storage.

This is a substantial platform capability and overlaps with Personal Expert AI's user/tenant/project/membership and RLS foundations. The models are not interchangeable: Bionic's team-centric model and integer IDs differ from Personal Expert AI's tenant/project model and UUID identities.

### 5.2 Important security observations

1. Bionic's local Docker Compose file explicitly says it is an example and **not production configuration**. It exposes several services on host ports and includes a `DANGER_JWT_OVERRIDE` test token. Never deploy that compose file unchanged in a trusted environment.
2. `crates/agent-harness/jwt.rs` decodes JWT payload claims from a forwarded access-token header; this code does not itself verify the cryptographic signature, issuer or audience. The design therefore depends on the upstream authentication/proxy boundary being correctly configured and not bypassable.
3. The same file supports a `DANGER_JWT_OVERRIDE` environment variable. It must be absent in production.
4. `crates/agent-harness/lib.rs` applies a permissive CORS layer (`Any` origin/method/header) to the agent routes. Production deployment must review and constrain this at the edge/application boundary.
5. Bionic's RLS and authorization logic is substantial, but its security posture cannot be declared safe solely from source inspection. Deployment topology, trusted headers, secrets, database roles, reverse proxy and enabled features need a separate threat-model and runtime test.
6. The Compose database credentials and test defaults are for local evaluation, not production.

### 5.3 Decision

Personal Expert AI remains the sole authority for user identity, tenant membership, project membership and document access. If Bionic is connected:
- it must not independently create or administer Personal Expert AI users/projects;
- it must not accept client-supplied tenant/project identifiers as authorization;
- the backend must mint a short-lived, scoped service capability or perform a server-to-server authorization exchange;
- every retrieval, download, write or tool action must be re-authorized by Personal Expert AI;
- do not pass the user's original JWT or long-lived database credentials into the sandbox;
- map identities explicitly; never assume Bionic team IDs equal Personal Expert AI tenant IDs.

## 6. Agent runtime, Skills and virtual filesystem

This is Bionic's most relevant differentiator for our next development stage.

The current tool runtime exposes a small model-facing tool surface (including `run_bash`, file read/write/edit and Python) and presents capabilities through a conversation-scoped virtual filesystem. The README documents lazy access to remote-backed files and persistence of writes in selected work/output directories. `lazy_fs.rs` implements lazy file materialization and a write journal. `skills.rs` resolves built-in and database-backed Skills and maps them into virtual paths. `connector_network.rs` mediates network access, connector routing, credentials and destination validation.

The sandbox crate is deliberately decoupled from Bionic database IDs and application concepts. Its `RunRequest` receives caller-supplied filesystem, network and Python capabilities. This is a useful separation: authorization and secret resolution remain in the application adapters, not inside arbitrary shell code.

### Reusable ideas

- Filesystem abstraction for context discovery instead of stuffing all context into prompts.
- Lazy materialization of document bodies and dataset chunks.
- Read-only source mounts and explicit writable output/work directories.
- Skill instructions plus operation-specific docs loaded on demand.
- A provider-neutral sandbox interface.
- Mediated network and connector calls with credential injection outside the sandbox.
- Persisted generated artifacts and explicit scheduled-task execution.

### Cautions

- Bionic's Bashkit sandbox is not a general Linux VM/container. Its own README says it supports shell, Python and SQLite but not a general Linux userspace or arbitrary package installation.
- The sandbox boundary is only as safe as the filesystem/network adapters and their authorization checks.
- A Skill is executable workflow guidance, not a security boundary. Every operation still needs server-side permission checks and parameter validation.
- Bionic's virtual filesystem layout is an application contract; adopting it wholesale would couple our data model to Bionic conventions.

### Decision

**Reuse the design; evaluate the runtime.** Prototype a Personal Expert AI filesystem adapter that exposes:
- `/project/manifest.md` — safe project summary and current document/version index;
- `/project/documents/<id>/metadata.json` — metadata and provenance only;
- `/project/sources/<fragment-id>.md` — authorized source fragments on demand;
- `/skills/<skill-id>/SKILL.md` — versioned approved skills;
- `/work/` — temporary writable workspace;
- `/artifacts/` — controlled generated outputs.

The actual original documents should be read through an authorized backend tool, not mounted as an unrestricted host directory. Source paths should be read-only; writes must go through explicit artifact APIs and be audited.

## 7. Model provider and LM Studio compatibility

Bionic's database supports provider types `OpenAI`, `Groq`, `OpenRouter`, `Ollama` and `OpenAICompatible`. In `ui_chat_orchestrator.rs`, the `OpenAICompatible` branch uses the Rig OpenAI provider with a configurable base URL. This is a strong indication that an LM Studio OpenAI-compatible chat endpoint can be configured without a bespoke Bionic provider type.

However:
- the source-level evidence confirms the **chat completion** route; it does not establish that all Bionic features work against LM Studio;
- the RAG embedding worker uses its own provider path and must be verified separately;
- tool calling depends on the loaded model's capabilities and LM Studio's implementation/format compatibility;
- vision, structured outputs, cancellation, streaming edge cases and concurrent requests need live tests;
- Bionic's provider configuration accepts configurable base URLs. It does not enforce the loopback-only rule used by Personal Expert AI's LM Studio adapter. Local-only deployment must enforce endpoint allowlisting and network egress controls outside the model form.

Personal Expert AI already has a loopback-only LM Studio adapter with explicit capability flags. It should remain the canonical model-provider boundary unless a POC proves Bionic can safely delegate to it or be configured to the same local-only guarantees.

**Conclusion:** LM Studio chat compatibility is plausible from source, not yet verified. Do not claim tested compatibility.

## 8. Storage and database overlap

Bionic persists its own users, teams, projects, conversations, documents, datasets, chunks, models, Skills, connectors, generated outputs and audit records in PostgreSQL. Its document storage currently has a database-backed implementation; the declared Supabase backend is not implemented in `object-storage/src/lib.rs`.

Personal Expert AI already has a separate PostgreSQL schema and local document object store with stronger explicit immutable-version/checksum semantics. Running both platforms as equal owners would create:
- two user/team/project authorization domains;
- two document registries and potentially two copies of originals;
- two knowledge/chunk indexes with different provenance semantics;
- two conversation histories and artifact registries;
- difficult deletion, retention, backup and audit reconciliation.

Avoid shared-table coupling or direct Bionic access to Personal Expert AI's PostgreSQL schema. Integration should be through a versioned internal API or narrow adapter, with Personal Expert AI retaining data ownership.

## 9. Deployment, dependencies and license

- Bionic is a Rust workspace (Cargo workspace with multiple crates), using Axum, Tokio, Rig, PostgreSQL/pgvector, Dioxus and Bashkit among other dependencies.
- The repository declares Apache-2.0. This is generally permissive, but adoption still requires preserving notices and reviewing all bundled/transitive dependencies and any separately distributed assets.
- The local Compose file is a demo/evaluation setup, not production. The repository also provides Kubernetes-oriented deployment paths.
- Running the full stack adds operational components: Bionic web app, PostgreSQL/pgvector, migrations, RAG worker, document/chunking service(s), cron and optional integration services.
- This is not a lightweight drop-in UI dependency. It adds a substantial Rust application and its own database lifecycle.

Before a real deployment, pin a release/commit and container digests, review SBOM and dependency licenses, disable unused services, configure secrets, TLS, network policies, resource limits, backups and restore tests, and perform security testing.

## 10. Integration options

| Option | Benefits | Risks/costs | Assessment |
|---|---|---|---|
| Bionic as the complete platform | Fastest access to a mature UI, RAG, users, Skills and tools | Replaces/duplicates our document, tenant, knowledge and provenance model; large migration and lock-in | **Reject for current architecture** |
| Bionic as UI only | Reuses a polished application | UI is tightly coupled to Bionic's own chat/project/model/data APIs; not a thin standalone frontend | **Not recommended without substantial adaptation** |
| Bionic as agent runtime behind Personal Expert AI | Reuses orchestration, tool runtime, Skills, sandbox and VFS | Requires a stable adapter/API, identity delegation, lifecycle mapping and careful security boundaries | **Best candidate for a bounded POC** |
| Borrow selected concepts; build our own runtime/UI | Maximum control and clean domain fit | More implementation work; delays feature delivery | **Safe fallback and parallel design path** |

## 11. Proposed architecture if POC proceeds

```text
Personal Expert AI UI (initially simple first-party UI)
              |
              v
Personal Expert AI API / Orchestrator
  - identity and tenant/project authorization
  - document and version ownership
  - retrieval and provenance validation
  - audit and artifact registration
              |
       scoped internal adapter
              |
              v
Bionic agent runtime (optional)
  - prompt/context assembly
  - Skills and tool loop
  - virtual filesystem adapter
  - sandbox execution
              |
       approved tools only
              |
              v
Personal Expert AI domain APIs
  - search_sources()
  - read_fragment()
  - get_document_metadata()
  - create_artifact()
  - run_engineering_check()
              |
              v
Personal Expert AI PostgreSQL + local storage + LM Studio
```

Bionic must not connect directly to the Personal Expert AI database or local document storage. The adapter should return scoped data and short-lived capabilities; all mutations and document reads pass through Personal Expert AI authorization.

If Bionic cannot be integrated without allowing it to become the source of truth for user/project/document data, stop the integration and reuse only its architectural ideas.

## 12. Minimal proof of concept (POC)

### Phase A — isolate and run Bionic

1. Pin the audited Bionic commit or a reviewed release.
2. Run only in an isolated local environment with synthetic documents and test identities.
3. Do not use production documents, credentials or the production Personal Expert AI database.
4. Remove `DANGER_JWT_OVERRIDE`; do not expose demo ports outside loopback; replace default credentials; restrict CORS and network egress.
5. Confirm the application can be configured with an OpenAI-compatible local endpoint.

### Phase B — LM Studio tests

Test one supported local model and record:
- model discovery and health;
- chat completion and streaming;
- tool call request/response round trip;
- embedding generation via Bionic's RAG worker;
- cancellation/client disconnect;
- two or more concurrent requests;
- behavior when LM Studio is stopped;
- network capture proving no external model/telemetry egress in local-only mode.

Pass criteria: all required calls remain on loopback/private local network; no silent fallback to a hosted model; errors are explicit; model capabilities are not assumed.

### Phase C — Personal Expert AI API adapter

Implement a disposable adapter, not a production integration:
- authenticate Bionic runtime using a dedicated service identity;
- resolve a user-scoped, project-scoped capability server-side;
- retrieve a small set of synthetic source fragments from Personal Expert AI;
- expose them read-only through Bionic's virtual filesystem;
- create one generated artifact through the Personal Expert AI artifact API;
- verify audit records and access denial for another project/tenant.

Pass criteria:
- Bionic cannot list or access ungranted projects;
- direct object IDs do not bypass authorization;
- no DB credentials or unrestricted host filesystem are available to the sandbox;
- source fragments retain immutable version, locator and provenance;
- all writes are registered and auditable in Personal Expert AI.

### Phase D — decision gate

Proceed only if:
1. all security and tenant-isolation tests pass;
2. LM Studio chat and embedding behavior meets required use cases;
3. the runtime can use our APIs without owning our data model;
4. operational footprint and latency are acceptable;
5. upgrade/version pinning and license review are complete.

Otherwise, stop the Bionic runtime POC and implement the VFS/Skills/tool contracts in our own Python backend.

## 13. Final recommendation

1. **Keep Personal Expert AI's database, identity, tenant/project access, original documents, processing pipeline, knowledge provenance and engineering-checking engine authoritative.**
2. **Do not migrate our documents or users into Bionic and do not run two canonical RAG indexes.**
3. **Treat Bionic's agent runtime, virtual filesystem, lazy loading, Skills and sandbox mediation as the main reuse candidates.**
4. **Run a small isolated POC before any production integration.** OpenAI-compatible chat support is present in source, but LM Studio end-to-end support is not verified.
5. **Keep the option to build our own runtime/UI.** Bionic should remain replaceable and must not become a hard dependency of the domain model.

## 14. Source references

### Bionic
- Repository and license: https://github.com/bionic-gpt/bionic-gpt
- Agent harness: https://github.com/bionic-gpt/bionic-gpt/tree/main/crates/agent-harness
- Tool runtime: https://github.com/bionic-gpt/bionic-gpt/tree/main/crates/tool-runtime
- Sandbox: https://github.com/bionic-gpt/bionic-gpt/tree/main/crates/sandbox
- RAG engine: https://github.com/bionic-gpt/bionic-gpt/tree/main/crates/rag-engine
- Database migrations: https://github.com/bionic-gpt/bionic-gpt/tree/main/crates/db/migrations
- Docker Compose example: https://github.com/bionic-gpt/bionic-gpt/blob/main/infra-as-code/docker-compose.yml
- OIDC documentation: https://github.com/bionic-gpt/bionic-gpt/blob/main/crates/bionic-gpt/content/docs/authentication/sso/index.md

### Personal Expert AI
- Repository: https://github.com/Dach1980/Personal_Expert_AI
- Target architecture: https://github.com/Dach1980/Personal_Expert_AI/blob/main/docs/architecture/TARGET_ARCHITECTURE.md
- Security model: https://github.com/Dach1980/Personal_Expert_AI/blob/main/docs/architecture/SECURITY_MODEL.md
- Knowledge model: https://github.com/Dach1980/Personal_Expert_AI/blob/main/docs/architecture/KNOWLEDGE_MODEL.md
- LM Studio provider architecture: https://github.com/Dach1980/Personal_Expert_AI/blob/main/docs/architecture/LLM_PROVIDER_ARCHITECTURE.md
- Document lifecycle: https://github.com/Dach1980/Personal_Expert_AI/blob/main/docs/architecture/DOCUMENT_LIFECYCLE.md
