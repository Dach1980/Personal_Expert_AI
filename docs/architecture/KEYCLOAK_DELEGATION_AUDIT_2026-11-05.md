# Keycloak delegation audit — 2026-11-05

Status: repository configuration audited; live Keycloak runtime and Stack-managed Keycloak version not yet inspected. No authentication or authorization code was changed as part of this audit.

## Executive decision

Keep Keycloak as the shared identity provider and keep PEA as the final authority for tenant/project/document authorization. Do **not** implement user impersonation through a service account or enable Keycloak's legacy "direct naked impersonation" flow.

Keycloak Standard Token Exchange (V2) is suitable only when Bionic actually has a valid user subject token to exchange. It does not create a user context from a database row containing `sub` and `email`, and it does not permit arbitrary subject impersonation. The current scheduled worker has no original user access token, so Standard Token Exchange alone cannot solve scheduled retrieval.

Recommended split:

1. **Interactive requests:** keep the existing verified user access token flow. If a future audience/scope downgrade is needed, use Standard Token Exchange V2 with the real user subject token and a narrowly permitted target client. Today the existing token already carries the `pea-api` audience, so an exchange is not required for the current adapter path.
2. **Scheduled/background tasks:** use a distinct confidential Bionic workload client for service authentication plus a PEA-owned, revocable delegation grant created when an authenticated user creates/authorizes the scheduled task. At execution, Bionic authenticates as the workload, presents the opaque grant identifier, and PEA independently verifies the grant, owner, tenant/project binding, expiry/revocation and the user's current memberships. PEA then performs retrieval under its own authorization context. The grant is not a bearer permission to arbitrary projects and cannot be selected or altered by the model.
3. Keep the Bionic project → PEA tenant/project mapping explicit and administratively managed. The mapping is a routing constraint, not an authorization grant.
4. PEA remains the final authorization authority for every retrieval operation. No Bionic-signed user identity claim is accepted as a substitute for PEA membership/project checks.

This preserves the approved goals (separate project mapping, least privilege, independent PEA authorization, no long-lived user refresh-token storage) while avoiding an unsafe or unsupported interpretation of Token Exchange.

## Repository evidence

### Personal_Expert_AI

- `docs/architecture/KEYCLOAK_INTEGRATION.md` defines one shared Stack-managed Keycloak realm, PEA external identity mapping by exact `(iss, sub)`, and independent PEA membership/project authorization.
- `infra/keycloak/README.md` names the realm `bionic-gpt`, the Bionic OIDC client `oauth2-proxy`, and instructs that the existing Stack-managed Keycloak control plane must be reused. It does not pin the actual Keycloak server version.
- `scripts/configure_keycloak_realm.py` provisions the `pea-api` audience client, the `pea-api-context` scope, and the public `pea-web` PKCE client. It does not configure Token Exchange, service accounts for a Bionic worker, delegation permissions or a task-owner delegation flow. Its admin password grant is used only by this local bootstrap script and is not a runtime authentication design.
- `infra/keycloak/pea-api-client.json` defines `pea-api` as a bearer-only resource client, with `serviceAccountsEnabled: false`, no standard login flow and no direct-access grant. This is appropriate as an API audience/resource client; it is not a Bionic workload client.
- `infra/keycloak/pea-api-context-client-scope.json` adds the `pea-api` audience and a single `tenant_id` user attribute. That claim is only a tenant selector; PEA still checks database membership and project access.
- `app/api/auth.py` verifies RS256/JWKS, exact issuer and audience, resolves the provisioned `(iss, sub)` identity, and checks active PEA user/tenant membership. PEA's existing authorization services remain responsible for project access.

### Bionic

- `infra-as-code/stack.yaml` uses the Stack OIDC component and names the realm `bionic-gpt`. It configures issuer, audience and JWKS URL but does not pin a Keycloak version or declare a Token Exchange client. The actual Keycloak version is supplied by the Stack-managed control plane and cannot be inferred from this manifest.
- `crates/agent-harness/jwt.rs` verifies the incoming Keycloak token and retains the raw access token in the authenticated request identity for normal web requests.
- `crates/cron/src/main.rs` loads the scheduled task owner's `openid_sub` and `email` from Bionic's database and constructs the scheduled execution identity. It does not load or possess the original user access token. Therefore a scheduled run cannot submit a real user `subject_token` to Standard Token Exchange.
- `crates/web-server/handlers/pea.rs` forwards the verified user Bearer token to the private PEA API for interactive adapter requests. This existing path should remain unchanged while scheduled retrieval is developed separately.

## Keycloak Token Exchange constraints

The official Keycloak documentation distinguishes Standard Token Exchange V2 from Legacy Token Exchange V1:

- Standard V2 exchanges an existing Keycloak token issued for one client into a token issued for another client in the same realm. The requesting client must be confidential and explicitly enabled/authorized for exchange.
- Standard V2 is not a "mint a token for any username" API. It requires a real subject token. The current scheduled worker does not have one.
- Legacy V1 includes impersonation and direct naked impersonation capabilities, but is deprecated/preview and carries a significant risk: a compromised client with naked impersonation rights can act as arbitrary users. It is not acceptable for this project.
- The installed Keycloak version remains unknown until the actual Stack-managed control plane is inspected. The repository manifest alone is insufficient evidence.

References:
- https://www.keycloak.org/securing-apps/token-exchange
- https://www.keycloak.org/2025/05/standard-token-exchange-kc-26-2

## Proposed implementation sequence

1. Inspect the live Stack/Keycloak version and realm/client configuration on the primary workstation or cluster. Do not request admin passwords, client secrets or access tokens in chat.
2. Add a separate confidential workload client for Bionic scheduled retrieval (separate from the bearer-only `pea-api` audience client and the public `pea-web` client). Enable only the client-credentials flow needed for workload authentication; do not grant impersonation.
3. Add explicit Bionic-project ↔ PEA-tenant/project binding with database constraints, unique/active semantics, admin-only mutation and audit events. Never infer UUIDs from Bionic integer IDs.
4. Add a PEA-owned delegation-grant model and authenticated grant/revoke API. Grant creation must be initiated under a verified user session and bind the task owner, Bionic task/project identity, PEA tenant/project, permitted operation (`search`), creation time, expiry/revocation state and audit metadata.
5. At scheduled execution, Bionic authenticates as its workload client and presents only the grant identifier. PEA resolves the grant, verifies Bionic workload identity, verifies that the task and mapping still match, and rechecks the user's current active identity/memberships/project permissions. Missing, expired, revoked, mismatched or unauthorized grants fail closed.
6. Build immutable `PeaRetrievalContext` inside the trusted server boundary only after the preceding checks. Do not accept tenant/project/owner/grant identifiers from model tool arguments.
7. Add bounded `pea_search` with fixed PEA origin, strict query/top-k limits, response byte/result caps, timeout, citation provenance and explicit untrusted-document treatment.
8. Add tests for grant lifecycle, owner mismatch, tenant/project substitution, revoked membership, revoked/expired grant, cross-project isolation, absent context, invalid parameters and response limits. Integrate only with the scheduled Tool Execution Loop; leave the old SSE chat unchanged.

## Outstanding runtime evidence

The following cannot be established from the Git repositories and must be checked against the actual deployment:

- Keycloak server version and enabled features;
- actual `oauth2-proxy` client type and current client authentication settings;
- whether the Stack-managed realm allows Standard Token Exchange V2 and its client permissions;
- the deployed Bionic/PEA network origins and service-to-service TLS posture;
- the actual PEA database state and whether any Bionic↔PEA project bindings exist.

Until these are verified, do not add runtime token-exchange calls, create a service client with guessed settings, or enable impersonation.


## Implementation update — 2026-11-05

The safe repository implementation has now started on `main`:

- PEA migration `0015_bionic_retrieval_delegation` adds `bionic_project_bindings` and `delegation_grants`, with composite project/tenant foreign keys, token-hash uniqueness, operation/status/expiry checks and RLS policies.
- PEA has an exact `azp` allowlist for the confidential `pea-bionic-worker` client.
- PEA provides administrator-only binding management, owner-bound grant issuance/revocation and an internal delegated search endpoint. Each search rechecks the grant, Bionic task/project identity, Keycloak owner `sub`, active user, tenant membership and project access.
- The Keycloak setup script now provisions the confidential worker client with service accounts enabled, browser/password flows disabled and the PEA audience scope attached. The secret is not printed or committed.
- Bionic scheduled runtime obtains a workload token using client credentials, requests a short-lived task grant and exposes `pea_search` only when the server-created retrieval context exists. The model can provide only query and top_k.
- The old interactive SSE chat remains on its original tool catalog and does not receive `pea_search`.
- The PEA PostgreSQL 16 database-integrity CI passed after the new schema/API implementation. Bionic Rust CI is being extended to compile/test `tool-runtime` and `cron`; its final result is still pending.

This is deliberately **not** Keycloak user impersonation. Standard Token Exchange V2 is not used to fabricate a scheduled user's identity. The scheduled worker authenticates as its own confidential service client; PEA then uses its own stored external identity mapping and current authorization records to decide whether the task owner may search the bound project.

Still outstanding: inspect the actual Stack-managed Keycloak version and realm, configure the live worker secret, set PEA workload environment, apply migration 0015 to the deployed PEA database, create an explicit project binding and perform live scheduled-task E2E. Repository contents alone cannot prove those deployment facts.
