# Bionic scheduled retrieval integration

Status: implementation slice committed; live Keycloak/Stack provisioning and cross-repository runtime verification remain pending.

## Trust model

- Keycloak authenticates the confidential Bionic worker with OAuth2 client credentials.
- PEA validates the RS256/JWKS signature, exact issuer, `pea-api` audience and exact `azp` value configured by `PEA_WORKLOAD_CLIENT_ID`.
- The worker identity is not a human identity and is never treated as one.
- PEA resolves the Bionic project mapping and the owner's exact `(issuer, sub)` external identity.
- PEA checks the owner is active and currently has active tenant and project access.
- PEA creates a short-lived, task-bound search grant. Only a SHA-256 hash is stored in PostgreSQL; the raw capability is returned once to the trusted Bionic worker.
- Each search request must present the workload access token, raw grant, Bionic project ID, Bionic task ID and the task owner's Keycloak `sub`. PEA checks all of them and revalidates current owner access before retrieval.
- Tenant/project/owner/grant values are fixed by the server-created context. They are not model tool arguments.

## PEA database objects

Migration: `0015_bionic_retrieval_delegation`.

### `bionic_project_bindings`

An administrator maps a Bionic numeric project ID to one exact PEA tenant/project UUID pair. The Bionic instance identity comes from PEA server configuration, not the API body.

Constraints enforce:
- one Bionic project per Bionic instance;
- one PEA project per Bionic instance;
- composite FK to the exact `(tenant_id, project_id)` PEA project;
- active/disabled lifecycle and positive Bionic IDs;
- creator FK and audit event.

### `delegation_grants`

A grant binds:
- exact Bionic project binding;
- Bionic scheduled task ID;
- PEA tenant/project;
- original PEA owner user;
- one operation (`search`);
- SHA-256 token hash;
- expiry and revocation timestamps.

The owner must have a PEA membership row in the same tenant. The grant FK also ties the grant's tenant/project to the referenced binding, preventing cross-project substitution.

## API surface

### Administrative binding

- `POST /api/v1/admin/bionic-project-bindings` — requires `system.integrations.manage`.
- `DELETE /api/v1/admin/bionic-project-bindings/{binding_id}` — disables the mapping without deleting history.

The permission is deliberately not granted automatically. Provision it only through the protected operator script:

```powershell
python scripts/provision_system_admin.py `
  --target-login "<existing PEA administrator login>" `
  --operator-login "<existing PEA operator login>" `
  --permission system.integrations.manage `
  --reason "Authorize Bionic project binding administration" `
  --confirm
```

The command requires an administrative `DATABASE_URL`, an explicit operator and reason, and records an append-only system audit event. Never grant this permission automatically to the first user.

### Workload grant issue

- `POST /api/v1/internal/bionic/delegation-grants`
- Requires a valid Keycloak service token from the allowlisted `pea-bionic-worker` client.
- Body: `bionic_project_id`, `bionic_task_id`, `owner_subject`, optional bounded `ttl_seconds`.
- PEA resolves the configured Bionic instance mapping, external identity, active user, tenant membership and project membership.
- Returns the raw grant token once. Bionic keeps it only in the current scheduled run's memory.

### Grant revocation\n\n- `POST /api/v1/internal/bionic/delegation-grants/{grant_id}/revoke`\n- Requires the workload token, exact grant token, Bionic project/task and owner subject.\n- PEA verifies all bindings before revoking; expired grants transition to `expired`.\n\n### Delegated search

- `POST /api/v1/internal/bionic/retrieval/search`
- Requires the same workload client token and the task-bound grant.
- Body additionally includes only `query` and `top_k`; Bionic project/task and owner subject are server-derived.
- PEA checks grant hash, status, expiry, task ID, project binding, owner subject and current PEA authorization.
- Results preserve fragment ID, document/version identity, locator, excerpt and content hash.

### User grant lifecycle

- `POST /api/v1/tenants/{tenant_id}/projects/{project_id}/delegation-grants` can issue a grant for an authenticated project member.
- `DELETE /api/v1/tenants/{tenant_id}/projects/{project_id}/delegation-grants/{grant_id}` lets only the grant owner revoke it.
- The model never receives a grant token.

## Environment

PEA API:
- `PEA_WORKLOAD_CLIENT_ID=pea-bionic-worker`
- `PEA_BIONIC_INSTANCE_ID=bionic-primary`
- existing `OIDC_ISSUER`, `OIDC_AUDIENCE=pea-api`, `OIDC_JWKS_URL`.

Bionic cron worker:
- `PEA_API_BASE_URL`: private PEA API origin;
- `PEA_OIDC_TOKEN_URL`: Keycloak realm token endpoint;
- `PEA_WORKLOAD_CLIENT_ID=pea-bionic-worker`;
- `PEA_WORKLOAD_CLIENT_SECRET`: deployment secret only; never in Git, PEA or browser configuration.

The Keycloak bootstrap script creates the confidential client and attaches the PEA API audience scope. The client secret must be generated/rotated in Keycloak and stored in the Bionic cron deployment secret manager. The live Stack secret objects still need to be created.

Production PEA API and Keycloak token endpoints must use HTTPS unless the host is one of the explicit local/in-cluster development endpoints configured in Bionic's URL validator. No redirects are followed. HTTP responses are capped at 1 MiB and requests time out.

## Bionic runtime behavior

- The cron worker creates a PEA grant just before running a scheduled task that has a Bionic project.
- Grant TTL is one hour; Bionic revokes it after the scheduled run and the expiry is the fallback. The raw grant and service credentials are held in memory only; no long-lived user token or grant secret is stored in the Bionic database.
- If PEA is not configured, the project is not bound, or the owner lacks current PEA access, the task continues without the `pea_search` tool. The tool is not registered.
- When a trusted context exists, `pea_search` is added to that scheduled turn's tool definitions and dispatcher only.
- The tool accepts `query` and `top_k` only. It cannot select tenant, project, task, owner, instance or grant.
- Search excerpts are explicitly marked as untrusted source material. The scheduled prompt instructs the model not to follow instructions inside retrieved documents and to cite exact fragment IDs.
- The ordinary interactive SSE path calls `create_request(..., None)` and uses the unchanged fixed tool catalog. `pea_search` is not registered in old SSE chat.

## Verification still required

1. Inspect the actual Stack-managed Keycloak version and realm at deployment time.
2. Run the PEA Keycloak setup script against the shared `bionic-gpt` realm.
3. Generate and store the worker client secret in the cron service secret manager.
4. Set `PEA_BIONIC_INSTANCE_ID` in PEA and create explicit Bionic→PEA project bindings using an administrator with `system.integrations.manage`.
5. Apply PEA migration 0015 to the actual database.
6. Run scheduled-task E2E with an owner who has active PEA access.
7. Verify no tool is registered for missing mapping, inactive grant, expired grant, disabled identity, revoked membership or cross-project substitution.
8. Confirm the old SSE chat still has no `pea_search` tool.

No live Keycloak instance, PEA deployment or private database was accessed during repository implementation. Green CI is necessary but does not replace these deployment checks.
