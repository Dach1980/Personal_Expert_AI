# Keycloak realm setup

Personal Expert AI and the Bionic fork use the **same Stack-managed Keycloak realm**. Do not start a second Keycloak server for this integration: Bionic's Stack OIDC component already provides the realm and login gateway.

## 1. Configure the shared realm

The bootstrap script is idempotent. It:

- creates or updates the `pea-api` audience client;
- creates or updates the `pea-api-context` client scope;
- adds an access-token audience mapper for `pea-api`;
- adds a user-attribute mapper for `tenant_id`;
- attaches `pea-api-context` as a default client scope to Bionic's OIDC client.

It does **not** create users, tenants, memberships or PEA permissions.

From the Personal Expert AI repository root, set the Keycloak admin credentials supplied by the Stack deployment. Do not put them in source files or commit them.

PowerShell:

```powershell
$env:KEYCLOAK_BASE_URL = "http://localhost:30000/oidc"
$env:KEYCLOAK_REALM = "bionic-gpt"
$env:BIONIC_OIDC_CLIENT_ID = "oauth2-proxy"
$env:KEYCLOAK_ADMIN_USERNAME = "<Stack Keycloak administrator>"
$env:KEYCLOAK_ADMIN_PASSWORD = "<Stack Keycloak administrator password>"
python scripts/configure_keycloak_realm.py
```

The script prints the exact `OIDC_ISSUER` and `OIDC_JWKS_URL` discovered from the realm. Use those values in PEA's `.env` and Bionic's server environment. If the Stack version uses a different client ID, set `BIONIC_OIDC_CLIENT_ID` to the actual client ID in the realm.

The Keycloak admin API must be reachable from the machine running the script. Do not expose the admin console/API to the public internet.

## 2. Assign the tenant context to a Keycloak user

For each user who should access PEA, set the Keycloak user attribute:

- Name: `tenant_id`
- Value: the UUID of the user's existing PEA tenant

The mapper places this attribute into the **access token**. PEA still checks its own database and will reject a missing/disabled tenant or missing membership. A Keycloak attribute is context, not an authorization grant.

Do not add a user to a tenant or project merely by changing a token mapper.

## 3. Create the first local PEA workspace (fresh database only)

If this is a fresh PEA database and no user/tenant/project exists yet, create the initial local records explicitly:

```powershell
$env:DATABASE_URL = "postgresql+psycopg://..."
python scripts/bootstrap_initial_workspace.py `
  --login "your-login@example.local" `
  --tenant-name "My organization" `
  --project-name "First project"
```

The command creates one active PEA user, one tenant with that user as owner, and one project with project-manager membership. It refuses to reuse an existing login. It does not create a Keycloak user or external identity mapping. Do not run it against a populated production database.

## 4. Provision the external identity mapping

First create the PEA user, tenant membership and project memberships through the normal PEA administrative workflow. Then obtain the user's immutable Keycloak `sub` from the realm and run:

```powershell
$env:DATABASE_URL = "postgresql+psycopg://..."
python scripts/provision_oidc_identity.py `
  --issuer "http://localhost:30000/oidc/realms/bionic-gpt" `
  --subject "<Keycloak sub>" `
  --login "<existing PEA user login>"
```

The command binds `(issuer, subject)` to an existing active PEA user. It refuses to create users, tenants or memberships and refuses to rebind an identity already attached to another PEA user.

For production, use the HTTPS issuer URL configured for the deployment, not the local HTTP URL.

## 5. Configure the services

PEA environment:

- `OIDC_ISSUER`: exact `issuer` printed by the setup script;
- `OIDC_AUDIENCE=pea-api`;
- `OIDC_JWKS_URL`: exact `jwks_uri` printed by the setup script, or the equivalent private Keycloak service URL reachable by PEA.

Bionic web-server environment:

- `OIDC_ISSUER`: same exact issuer;
- `OIDC_AUDIENCE=pea-api`;
- `OIDC_JWKS_URL`: Keycloak JWKS endpoint reachable from the Bionic pod/container;
- `PEA_API_BASE_URL`: private PEA API URL reachable from the Bionic server.

Bionic must remain behind the trusted Stack OIDC gateway. The gateway must strip any client-supplied `X-Forwarded-Access-Token` header and inject the actual access token after authenticating the browser session. Never expose the Bionic application port directly to an untrusted network.

## 6. Verify

1. Open the realm's OIDC discovery document at `{KEYCLOAK_BASE_URL}/realms/{KEYCLOAK_REALM}/.well-known/openid-configuration`.
2. Confirm that the `issuer` exactly matches `OIDC_ISSUER`.
3. Log in through Bionic and inspect the access token locally in a trusted development environment. It must contain `iss`, `sub`, `aud` including `pea-api`, `exp`, `iat` and `tenant_id`. Do not paste production tokens into tickets or chat.
4. Confirm PEA accepts a provisioned user with active tenant membership.
5. Confirm PEA rejects an unprovisioned subject, disabled identity, inactive user, inactive tenant, missing membership and cross-tenant/project access.

The PEA API independently verifies the RS256 signature using the configured JWKS, validates issuer/audience/time claims and checks tenant/project memberships on every request.


## Public Pages client

The same realm also provisions a separate public browser client `pea-web` for the static GitHub Pages SPA. It uses Authorization Code + PKCE S256, has no client secret and has no password/direct-access grant. The setup script attaches `pea-api-context` to this client so the access token carries the `pea-api` audience and the configured `tenant_id` claim.

Before running `python scripts/configure_keycloak_realm.py`, set:

- `PEA_WEB_REDIRECT_URIS`: exact callback URL(s), default `https://dach1980.github.io/Personal_Expert_AI_Web/`.
- `PEA_WEB_ORIGINS`: exact origin(s), default `https://dach1980.github.io`.

The Bionic server must use `PEA_WEB_ORIGIN` with the same exact origin for CORS. The Pages build needs `VITE_OIDC_ISSUER`, `VITE_OIDC_CLIENT_ID=pea-web`, `VITE_OIDC_REDIRECT_URI` and `VITE_API_BASE_URL` pointing to Bionic. These are public configuration values, not secrets.

Provision each person explicitly in PEA with `scripts/provision_oidc_identity.py` and create the corresponding active tenant/project memberships. The Keycloak `tenant_id` attribute is a routing context claim only; it does not grant PEA access by itself. Never automatically attach a first-time user to a tenant based only on email or an untrusted browser parameter.



## 7. Confidential Bionic scheduled-worker client

The setup script also creates/updates a separate confidential client:

- Client ID: `pea-bionic-worker`
- Client authentication: client secret
- Service accounts: enabled
- Standard browser flow: disabled
- Direct access/password grant: disabled
- Impersonation: not enabled
- Default client scope: `pea-api-context`, which supplies the `pea-api` audience

This client is **not** the `pea-api` resource/audience client, the public `pea-web` client, or Bionic's browser-login `oauth2-proxy` client. Do not reuse their credentials.

After running the setup script, open the Keycloak admin console, select **Clients → pea-bionic-worker → Credentials**, generate/rotate its client secret and place it only in the Bionic deployment secret store. Never commit it or paste it into chat. Configure:

- Bionic secret: `PEA_WORKLOAD_CLIENT_SECRET`;
- Bionic and PEA allowlist: `PEA_WORKLOAD_CLIENT_ID=pea-bionic-worker`;
- both deployments: the same stable `PEA_BIONIC_INSTANCE_ID`, e.g. `bionic-primary`.

The service obtains an access token with the OAuth2 client-credentials grant and calls PEA's private internal retrieval endpoint. PEA validates the token signature, issuer, audience and exact `azp` client ID. It then resolves the PEA-owned delegation grant and rechecks the human owner's current tenant/project permissions.

This is **workload authentication, not user impersonation**. Do not enable Keycloak Legacy Token Exchange V1, direct naked impersonation, or arbitrary subject impersonation. Standard Token Exchange V2 may be used only when a real user subject token exists and a narrower target token is needed; it does not create a scheduled user's identity from Bionic's database row.

The PEA delegation token is generated per scheduled task, returned once, stored by Bionic as a task secret, and persisted in PEA only as a SHA-256 hash. It is bound to one Bionic project, one task, one PEA tenant/project, one owner and the `search` operation. PEA rejects missing, mismatched, expired, revoked or unauthorized grants. The Bionic server must create/store the grant only after verifying the caller owns the scheduled task; it must never expose the grant token as a model tool argument.
