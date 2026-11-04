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
