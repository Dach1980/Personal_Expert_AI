# Keycloak authentication integration

Status: architecture approved; first implementation slice committed; local Keycloak provisioning and end-to-end deployment remain pending (2026-11-03).

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

The former HS256/internal-UUID token contract is no longer used by the API authentication dependency. Tests cover signature, issuer, audience, expiry, malformed tenant context, explicit identity provisioning and active membership.

## Bionic security finding — must be fixed before production

The fork's `crates/web-server/jwt.rs` now verifies RS256 signatures against the configured JWKS, validates issuer/audience/time claims, caches JWKS for five minutes and refreshes when a key id is not found. It accepts only `X-Forwarded-Access-Token`; the hard-coded `DANGER_JWT_OVERRIDE` and forwarded user/email fallback have been removed.

Therefore:

1. Do not expose the Bionic web-server port directly to untrusted networks.
2. Do not treat Bionic's decoded `sub` as proof of identity.
3. The Bionic app must remain behind the Stack OIDC component or an equivalent trusted gateway that performs the Keycloak login flow, strips client-supplied forwarded-token headers and injects the actual access token over the private app network. The plain Docker Compose example does not provide this gateway and must not be treated as a complete login deployment.
4. PEA independently validates the forwarded Bearer token. It does not trust Bionic user-id/email headers.

The Bionic server-side API Adapter now exposes a fixed set of GET routes under `/api/pea`. It forwards the verified Keycloak access token to PEA; PEA independently validates it. The browser never receives service credentials and cannot choose an upstream URL.

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

- PEA now has an `external_identities` table keyed uniquely by (`issuer`, `subject`) and a migration for it. Unknown external identities are rejected; there is no automatic PEA account or tenant creation.
- PEA now validates Keycloak RS256/JWKS tokens, resolves the internal user and verifies active tenant membership. Project access remains enforced by the existing project/document services.
- PEA has initial Review, Finding and Evidence models, migration and tenant/project-scoped create/read/status endpoints with audit events.
- Bionic now verifies Keycloak RS256/JWKS tokens and has fixed server-side GET adapter routes for projects, documents, versions, source fragments, artifacts and knowledge.
- Local Keycloak realm/client provisioning, trusted OIDC gateway wiring, external identity provisioning, UI wiring and full end-to-end tests remain outstanding.
- The fork CI no longer attempts to publish Docker images to the upstream GHCR package. Rust verification for the new authentication/adapter commits is still running; only completed successful workflow runs will be considered proof of compilation.
