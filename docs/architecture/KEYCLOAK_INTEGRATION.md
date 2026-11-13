# Keycloak authentication integration

Status: PEA OIDC validation is implemented; local realm discovery is verified; safe provisioning and end-to-end browser authentication remain pending runtime acceptance (2026-11-13).

## Decisions and trust boundaries

Keycloak is the identity provider. PEA is the authorization authority for PEA data.

- Keycloak authenticates users and issues signed OpenID Connect tokens.
- PEA owns internal user IDs, external identity mappings, tenants, memberships, projects and resource authorization.
- Bionic, when deployed and integrated, is a client of PEA and is not the authority for PEA document permissions.
- PEA independently validates every presented access token and checks its own database authorization state.
- PEA PostgreSQL and document storage remain private to PEA.
- Browser code must never receive PEA service credentials, signing keys or database credentials.

Do not map identities by email. Email is mutable. The stable external identity key is the pair **(issuer, subject)**, where subject is the signed OIDC **sub** claim within the exact configured issuer.

A verified external identity does not automatically create a PEA user, tenant, membership, project membership or owner role. Provisioning and membership grants are explicit administrative operations.

## Current local Keycloak facts

The verified local development configuration is:

- Keycloak origin: **http://localhost:30000**
- Realm: **stack-app**
- Discovery issuer: **http://localhost:30000/realms/stack-app**
- JWKS URI: **http://localhost:30000/realms/stack-app/protocol/openid-connect/certs**
- Signing key: RSA, **use=sig**, **alg=RS256**

The issuer and JWKS URI were checked against the live realm discovery document. These values are local-development configuration and must not be copied into production deployment settings without replacing them with the deployment's exact discovery values.

The current local cluster has Keycloak and its database/operator resources. A Bionic application deployment, StackApp resource and Bionic OIDC client have not been confirmed. Do not assume that **oauth2-proxy**, **pea-bionic-worker** or a Bionic gateway exists in this realm.

## PEA Keycloak client model

The first provisioning slice is intentionally limited to three PEA resources:

1. **pea-api**: bearer-only resource/audience client. It is not used for interactive login.
2. **pea-api-context**: client scope with an access-token audience mapper for **pea-api** and a **tenant_id** user-attribute mapper.
3. **pea-web**: public SPA client using Authorization Code Flow and PKCE S256, with exact redirect URI and web-origin allowlists.

The scope is attached as a default scope to **pea-web**. It is not attached to an unverified Bionic client.

The **tenant_id** claim is a context selector only. PEA must still resolve the signed **(iss, sub)** to an active external identity and user, then verify active tenant membership and project permissions from its own database. A token claim alone never grants access.

## Safe provisioning contract

**scripts/configure_keycloak_realm.py** is read-only by default. **--apply** is required for mutations.

The provisioning contract is:

- Verify OIDC discovery before calling the Admin API.
- Require the discovery issuer to exactly equal the configured origin and realm.
- Require admin credentials through environment variables; never read credentials from files or print them.
- Read and validate all relevant existing clients/scopes before the first write.
- Create only missing **pea-api**, **pea-api-context** and **pea-web** resources.
- Never update or overwrite an existing client or scope.
- Treat duplicate names, incompatible flags, mapper drift and redirect/origin allowlist drift as blockers.
- Attach **pea-api-context** to **pea-web** only when it is not already attached.
- Do not create users, tenants, memberships, Bionic clients, workload clients or delegation grants.

The local defaults are **KEYCLOAK_BASE_URL=http://localhost:30000** and **KEYCLOAK_REALM=stack-app**. Redirect URI and origin defaults target the PEA GitHub Pages SPA; deployments must supply their own exact allowlists.

The current implementation uses the Keycloak **admin-cli** password grant. If it is disabled, provisioning stops without changing the realm. Do not enable a broad grant as an automatic workaround; use an explicitly approved administrative mechanism.

## Token validation requirements

PEA validates Keycloak access tokens using the configured realm JWKS and an explicit asymmetric algorithm allowlist (currently RS256). Validation checks:

- signature against a key from the configured JWKS endpoint;
- exact **iss** match against **OIDC_ISSUER**;
- expected API audience (**OIDC_AUDIENCE=pea-api**);
- **exp**, **iat** and, when present, **nbf**;
- non-empty **sub**;
- active external-identity mapping and active PEA user;
- active membership of that user in the requested tenant.

PEA must not accept an algorithm selected by an untrusted token header, an arbitrary JWKS URL from a request, an unverified JWT payload, a tenant claim without membership verification, or an email-only identity match. Key rotation must work through the configured JWKS endpoint.

The former HS256/internal-UUID token contract is not used by the API authentication dependency.

## Bionic integration — deferred until deployment is verified

Bionic integration is a separate phase and must not delay the first standalone PEA launch.

Before provisioning Bionic-related clients or gateways:

1. Inspect the actual Bionic deployment, namespace, ingress and service endpoints.
2. Identify the real OIDC client and trusted login gateway from live configuration.
3. Verify that the gateway strips client-supplied forwarded-token headers and injects only the authenticated user's access token over a private app network.
4. Verify that PEA independently validates the forwarded Bearer token.
5. Keep Bionic's server-side API adapter fixed to approved PEA routes; never allow the browser or model to select an upstream URL.
6. Keep PEA as the owner of tenant/project authorization.

Do not expose Bionic's application port directly to untrusted networks. Do not trust Bionic user-ID/email headers as identity proof.

### Scheduled/background tasks

Interactive user-token authentication and scheduled-task authorization are separate flows. A database **sub** or email is not a signed subject token.

The safe scheduled-task direction remains:

- a separate confidential workload identity for Bionic;
- a PEA-owned, revocable delegation grant created only after an authenticated user authorizes a task;
- binding to the task owner, Bionic project/task, PEA tenant/project and permitted operation;
- PEA rechecking workload identity, grant lifecycle and the human owner's current memberships/permissions at execution;
- fail-closed behavior for missing, expired, revoked or mismatched grants.

Do not use Legacy Token Exchange V1, direct naked impersonation, or a service account that can choose arbitrary user subjects. Standard Token Exchange V2 cannot manufacture an arbitrary user's identity from a scheduled task row.

No Bionic worker client or delegation grant is created by the first Keycloak bootstrap package.

## Current PEA implementation state

- PEA has an **external_identities** table keyed uniquely by (**issuer**, **subject**).
- Unknown external identities are rejected; there is no automatic account or tenant creation.
- PEA validates Keycloak RS256/JWKS tokens and resolves the internal user.
- Tenant membership is checked by PEA; project access remains enforced by PEA project/document services.
- Local PostgreSQL 16 and the LM Studio provider have passed their initial smoke checks.
- A complete browser login, token refresh, tenant/project switching, chat/SSE persistence and document workflow have not yet passed end-to-end acceptance.

## Implementation and acceptance sequence

1. Provision the PEA-only Keycloak resources with dry-run, then explicit apply.
2. Create or identify a normal Keycloak user and verify a real access token locally.
3. Explicitly bind the user's **(issuer, sub)** to an existing PEA user.
4. Verify database connectivity, restricted runtime grants and PostgreSQL RLS.
5. Verify authenticated session, tenant/project APIs, chat persistence and SSE.
6. Verify the Web SPA login/logout/refresh and its main workflows.
7. Record the first standalone PEA launch acceptance.
8. Only then continue with the separately audited Bionic integration.

Never commit admin passwords, client secrets, private keys, access tokens or production credentials.
