# PEA implementation status — 2026-11-05

## Retrieval API foundation

Implemented in `main`: tenant/project-scoped lexical search over `SourceFragment.content`.

- `POST /api/v1/tenants/{tenant_id}/projects/{project_id}/search`.
- Request: query (2–1000 non-space chars), top_k (1–50), document type filters and version_state (`current` by default, `all` optional).
- Authorization: verified principal, exact active tenant context, `ProjectService.get` membership check, PostgreSQL tenant RLS context.
- Query: parameterized, escaped `ILIKE` phrase search; current version filter is enforced by joining Document.current_version_id to DocumentVersion.id.
- Response: fragment/document/version IDs, document title/type, original filename, fragment type, locator, excerpt and content hash.
- Result mode is explicitly `lexical`; no embedding/vector search, reranking or KnowledgeItem traversal is claimed.
- Unit tests cover route registration and request validation.

## Bionic integration

Bionic `crates/web-server/handlers/pea.rs` now proxies the fixed route:
`POST /api/pea/tenants/{tenant_id}/projects/{project_id}/search`.

The proxy forwards the verified caller's access token server-to-server. It does not accept arbitrary upstream URLs or browser-supplied tenant identity.

## Still outstanding

- Bionic Agent Runtime model-facing `pea_search` tool definition and execution.
- Propagate the verified JWT access token into tool invocation without putting credentials in model prompts.
- Ensure tenant/project scope is derived from verified identity and checked again by PEA.
- Add retrieved content as untrusted source data, never as instructions.
- Add ACL-before-prompt context assembly and a citation allowlist tied to returned fragment IDs/version IDs.
- Add document-grounded dialogue tests, cross-tenant negative tests, prompt-injection tests and live local-model evaluation.
- Add semantic retrieval/embeddings and reranking only after lexical baseline tests and evaluation corpus are in place.

## Commit references

- PEA API schema: `b42200434b6051218ed60b6b7793c7d5de6b949e`.
- PEA route: `79e1bee73b74b59c673f20bf8a1a89e3e0371126`.
- PEA tests: `24010818b6beb13970cf6f8b8ac0127ea1d87e07`.
- PEA API contract docs: `bb5bbdb56cf9d6ac84500a51cfc9cfcac1d031ec`.
- Bionic proxy route: `6c25fd3a81fb878224917a94c4ce011ab68bedea`.
- Bionic integration docs: `8863219018d0ab8def4bb926c637a184fc8f1583`.

CI statuses were not available from the repository status endpoint at the time of this report. Source changes must be treated as `NOT VERIFIED` until the respective GitHub Actions checks pass.


## Tenant switching contract update — 2026-11-05

- `GET /api/v1/session` now authenticates and returns the provisioned user identity without requiring a tenant selection; `tenantId` is nullable.
- `GET /api/v1/tenants` remains the membership discovery endpoint and returns only active memberships visible through the caller's `app.user_id` RLS context.
- Tenant-scoped requests use `X-Tenant-ID`; the header is only a selection request. PEA checks active membership and tenant status on every request before setting `app.tenant_id`.
- A missing legacy `tenant_id` JWT claim is supported. If present, it remains a compatibility fallback only; it does not replace membership checks.
- Tests now cover a token without the legacy tenant claim selecting an active membership through `X-Tenant-ID`, plus an identity-only session response.
- CI acceptance for the latest commit and live Keycloak/Bionic/PostgreSQL E2E remain pending; the previous PostgreSQL 16 CI pass must not be attributed to these new commits.

## Bionic scheduled retrieval delegation — source reconciliation 2026-11-06

Current `main` now includes a PEA-owned delegation boundary in `app/api/delegation.py`:

- System administrators with `system.integrations.manage` can create/disable explicit Bionic project → PEA tenant/project bindings. Binding creation rejects inactive tenants/projects and records a system audit event.
- A Bionic confidential workload client authenticates with the `pea-api-context` scope and may request a task-bound grant only for a configured Bionic instance and active project binding.
- The grant is bound to Bionic project, Bionic task, verified owner subject, PEA tenant/project and `search` operation. TTL is bounded to 60 seconds–7 days (default 1 hour).
- PEA stores only SHA-256 of the one-time grant secret. The raw secret is returned once to the trusted Bionic worker.
- Each delegated search rechecks grant hash/status/expiry, active Bionic binding, external owner identity, active PEA user, active tenant membership and current project access before calling the same ACL-scoped lexical search implementation.
- Grant revocation is owner-scoped for user-issued grants; internal workload grants also have a revocation endpoint for Bionic.
- PEA remains the authorization authority. The Bionic workload token does not itself grant document access; it can only exercise a matching active PEA grant.

### Acceptance still required

- Run current-HEAD PostgreSQL 16 migration/schema/RLS/full-test CI; the historical successful run `41813394892` predates the latest delegation/auth commits and must not be attributed to current HEAD.
- Exercise the confidential client against the live Stack-managed `bionic-gpt` realm and verify the exact issuer, audience, JWKS and `pea-api-context` scope.
- Test binding disable, grant expiry, revoke, owner deprovisioning, tenant/project membership removal, wrong Bionic project/task/owner, wrong workload client and cross-tenant/project attempts against PostgreSQL 16.
- Verify the Bionic worker revokes grants on normal completion and TTL safely bounds abandoned tasks.
- The scheduled-task delegation API is not yet a substitute for an interactive browser-chat delegation contract.