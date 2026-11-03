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
- Bionic now verifies Keycloak RS256/JWKS tokens and has fixed server-side GET adapter routes for projects, documents, versions, source fragments, artifacts, knowledge, reviews, findings and evidence.
- Bionic's authenticated `/o/{team_id}/pea` workspace page is wired into Documents, Reviews and Knowledge Base navigation. It loads live PEA data through same-origin adapter routes and connects source-fragment locators to rendered page previews.
- The Keycloak client-scope template and provisioning command are committed, but the audience/tenant mappers still need to be imported into the running Bionic realm and an actual user must be explicitly mapped. Local runtime verification of the Stack OIDC gateway, PEA network reachability, and full login/dialogue/Agent Runtime end-to-end flow remains outstanding.
- The fork CI no longer attempts to publish Docker images to the upstream GHCR package. Rust verification for the new authentication/adapter commits is still running; only completed successful workflow runs will be considered proof of compilation.


## Using the Keycloak instance already provisioned for Bionic

Do not deploy a second Keycloak instance. The Bionic Stack manifest already enables the Stack OIDC component. Stack installs/uses a shared Keycloak control plane and creates a realm for each StackApp; its OIDC component places oauth2-proxy in front of the app. The Bionic realm is `bionic-gpt` (also reflected in its configured logout URL).

For a local development cluster:

1. Ensure the shared Keycloak control plane is installed once with `stack init --install-keycloak`.
2. Deploy Bionic using its `dev` profile, which enables the OIDC component.
3. Obtain the temporary Keycloak admin credentials with `stack status --manifest infra-as-code/stack.yaml`. Do not paste these credentials into GitHub or chat.
4. Open the Keycloak admin console by forwarding the service: `kubectl -n keycloak port-forward svc/keycloak-service 8080:8080`.
5. Use the Bionic realm `bionic-gpt`; do not create a separate PEA realm.

### Required Keycloak token claims

In the Bionic realm, configure the Bionic OIDC client (the client used by Stack's oauth2-proxy) so that its access token has:

1. Create a Keycloak client with ID `pea-api` as the API audience. It is not a browser login client; disable Standard Flow, Direct Access Grants and Service Accounts.
2. Import the client-scope template [pea-api-context-client-scope.json](../../infra/keycloak/pea-api-context-client-scope.json) under **Client scopes → Create client scope → Import**.
3. Attach `pea-api-context` to the Bionic oauth2-proxy client as a **Default** client scope. Do not attach it only as Optional.
4. Set the `tenant_id` user attribute on each Keycloak user to the PEA tenant UUID.

The imported scope adds `aud` containing `pea-api` and the `tenant_id` String claim to the access token only (not the ID token). This is only a tenant selector, not an authorization grant: PEA still checks the user's active membership and project access. The current first integration uses one active tenant per token; a tenant-switching flow will be needed before one identity can operate in multiple tenants without reauthentication.

Before configuring `OIDC_ISSUER`, inspect the realm's OpenID discovery document at `{issuer}/.well-known/openid-configuration` and copy its exact `issuer` value. Do not infer or hand-edit the issuer URL. For a local PEA process on the host, forward Keycloak to port 8080 and set `OIDC_JWKS_URL` to the realm's `protocol/openid-connect/certs` endpoint through that forwarded port. The public issuer and the private JWKS retrieval URL may differ, but the token's `iss` must match `OIDC_ISSUER` exactly.

### Explicitly bind a Keycloak user to an existing PEA user

After the Keycloak user has logged in once, obtain the immutable `sub` value from the access token (or the Keycloak user's internal ID, if it is confirmed to be the same subject). Then run this from the PEA repository with `DATABASE_URL` configured:

```bash
python scripts/provision_oidc_identity.py \
  --issuer "EXACT_ISSUER_FROM_TOKEN" \
  --subject "KEYCLOAK_SUBJECT" \
  --login "EXISTING_PEA_USER_LOGIN"
```

This command only binds an already-existing active PEA user. It never creates a user, tenant, membership, project grant or owner role. Those must exist independently before the user can access project data.
