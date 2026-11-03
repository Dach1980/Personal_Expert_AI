# Keycloak authentication integration

Status: architecture approved; implementation in progress (2026-11-03).

## Decision

Keycloak is the single identity provider for both Bionic and Personal Expert AI (PEA).

- Keycloak authenticates the human and issues signed OpenID Connect tokens.
- Bionic owns the chat/agent user experience, but is not the authority for PEA document permissions.
- PEA owns internal user UUIDs, tenant memberships, project memberships and resource authorization.
- The Bionic server-side API Adapter calls PEA. Browser code must never receive PEA service credentials, JWT signing keys or database credentials.
- PEA PostgreSQL and the document filesystem remain private to PEA.

## Identity mapping

Do not map users by email. Email is mutable and can be reassigned.

PEA will maintain an explicit external-identity mapping:

- `issuer`: exact, configured Keycloak realm issuer URL;
- `subject`: immutable OIDC `sub` within that issuer;
- `user_id`: existing internal PEA User UUID;
- unique key: (`issuer`, `subject`).

A verified external identity does not automatically create a tenant, membership, project membership or owner role. Provisioning and membership grants are explicit administrative operations. A user must have an active PEA membership in the tenant named by the request/token before any tenant-scoped operation is allowed.

## Token validation requirements in PEA

The PEA API must validate Keycloak access tokens using the realm's published JWKS and an explicit asymmetric algorithm allowlist (initially RS256). Validation must check:

- signature against a key from the configured JWKS endpoint;
- exact `iss` match against `OIDC_ISSUER`;
- expected API audience (`OIDC_AUDIENCE`);
- `exp`, `iat` and, when present, `nbf`;
- non-empty `sub`;
- active external-identity mapping and active PEA User;
- active membership of that user in the requested tenant.

The API must not accept an algorithm selected by the untrusted token header, an arbitrary JWKS URL from a request, an unverified JWT payload, a tenant claim without membership verification, or an email-only identity match. Key rotation must work through the configured JWKS endpoint.

The legacy HS256 development-token path must not be silently treated as Keycloak authentication. Any temporary development mode must be explicitly enabled, isolated from production and covered by tests.

## Bionic security finding — must be fixed before production

The current fork's `crates/web-server/jwt.rs` does **not** cryptographically verify JWT signatures. It splits the token, base64-decodes the payload and reads `sub` and `email`. It also supports `DANGER_JWT_OVERRIDE` and fallback `X-Forwarded-User` / `X-Forwarded-Email` headers.

Therefore:

1. Do not expose the Bionic web-server port directly to untrusted networks.
2. Do not treat Bionic's decoded `sub` as proof of identity.
3. Before production, either add cryptographic OIDC/JWKS verification in Bionic or place it behind a hardened authentication gateway that verifies Keycloak tokens, strips all incoming identity headers and injects trusted identity data over a private network. The chosen gateway topology must be tested; merely setting an HTTP header is not authentication.
4. Remove or strictly disable `DANGER_JWT_OVERRIDE` outside isolated tests.
5. The PEA API must independently validate its own Bearer token. It must not trust Bionic's user ID/email headers.

The API Adapter will use a server-side credential flow. A browser-provided user token may be forwarded only after the trust boundary and audience have been explicitly designed; Bionic must not mint PEA identities from unverified claims.

## Target request flow

1. Browser redirects to Keycloak for OIDC login.
2. Keycloak authenticates the user and returns tokens to the configured OIDC client.
3. Bionic establishes its application session only after trusted token verification.
4. Bionic's server-side API Adapter calls PEA over the private application network.
5. PEA validates the Keycloak-issued token (or a narrowly scoped, cryptographically authenticated backend token issued through an explicitly designed exchange).
6. PEA maps (`iss`, `sub`) to an internal User UUID.
7. PEA checks active tenant and project memberships on every request.
8. PEA returns only authorized domain data and safe document previews.

## Deployment and secrets

- Keycloak is self-hosted alongside the application stack.
- Production issuer URL must be stable and use HTTPS.
- Realm export may contain public client configuration only; never commit client secrets, bootstrap admin passwords, private keys or production credentials.
- Secrets are supplied through deployment secrets/environment files excluded from Git.
- Use separate OIDC clients for Bionic browser login and PEA API audience; configure exact redirect URIs and web origins.
- Disable public registration unless deliberately required.
- Enable secure cookies, short-lived access tokens, refresh-token rotation and brute-force protection according to the deployment profile.
- Back up the Keycloak database and realm configuration securely.

## Implementation sequence

1. Make Bionic's Rust build/test workflow independent from upstream GHCR publication.
2. Add PEA external-identity persistence and RS256/JWKS validation with negative tests.
3. Configure a local Keycloak realm and separate Bionic/PEA clients without committing secrets.
4. Implement the Bionic trust boundary and server-side PEA API Adapter.
5. Connect real projects, documents, versions and source-fragment previews.
6. Add Review/Finding/Evidence domain entities and tenant-isolation tests.
7. Run end-to-end login, token expiry/rotation, tenant isolation, dialogue and Agent Runtime tests.

## Current implementation state

- Existing PEA tenant/project/document read APIs are implemented and tenant-scoped.
- Existing PEA authentication currently expects HS256 with a shared secret and internal UUID `sub`; it is not yet Keycloak-compatible.
- Bionic's current JWT extractor decodes claims but does not verify signatures.
- The Bionic adapter, external identity mapping and Review/Finding/Evidence domain are not yet implemented.
- The fork's previous CI failure occurred after successful Rust compilation, during a push to the upstream `ghcr.io/bionic-gpt/bionicgpt` package. The fork CI has been changed to use the Dagger pull-request validation mode, which builds/tests without publishing images; the new run must finish successfully before this change is considered verified.
