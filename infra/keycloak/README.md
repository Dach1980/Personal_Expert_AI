# Keycloak setup for Personal Expert AI

PEA uses the existing Keycloak deployment and the realm configured for the environment. Do not install or recreate Keycloak as part of PEA setup.

The current local development environment uses:

- Keycloak origin: **http://localhost:30000**
- Realm: **stack-app**
- OIDC issuer: **http://localhost:30000/realms/stack-app**
- JWKS endpoint: **http://localhost:30000/realms/stack-app/protocol/openid-connect/certs**

These are local development values, not production defaults. For another deployment, set the origin and realm explicitly and use the exact issuer published by that realm's discovery document.

## 1. What the bootstrap provisions

**scripts/configure_keycloak_realm.py** provisions only these PEA resources:

- **pea-api**: bearer-only resource/audience client; it is not a browser login client.
- **pea-api-context**: access-token audience mapper for **pea-api** and a **tenant_id** user-attribute mapper.
- **pea-web**: public browser client using Authorization Code Flow with PKCE S256.

The script attaches **pea-api-context** as a default client scope to **pea-web**.

It does not create users, tenants, memberships, projects, service-account clients or Bionic clients. In particular, it does not depend on **oauth2-proxy** or **pea-bionic-worker**. Bionic workload authentication and delegation are a separate integration phase.

## 2. Safety behavior

The script is read-only by default. It:

1. Reads OIDC discovery and requires an exact issuer match.
2. Authenticates to the Keycloak Admin API.
3. Reads the existing clients and client scopes.
4. Validates every existing PEA resource before planning any mutation.
5. Stops without writes if it finds a duplicate or incompatible existing resource.
6. Creates only missing resources when explicitly invoked with **--apply**.

Existing clients and scopes are never updated or overwritten. Existing **pea-web** redirect URI and origin allowlists must exactly match the requested values. An operator must resolve a mismatch manually; the bootstrap will not broaden or replace an allowlist.

The admin credentials are read only from environment variables. They are never read from files, printed, or committed. The current script uses the Keycloak **admin-cli** password grant for local administration. If that grant is disabled, the script stops without changing the realm; do not enable a broader grant merely to bypass the failure. Use an approved administrative authentication method for that environment.

## 3. Run a read-only preflight

From the repository root, in PowerShell:

~~~powershell
$env:KEYCLOAK_BASE_URL = "http://localhost:30000"
$env:KEYCLOAK_REALM = "stack-app"
$env:KEYCLOAK_ADMIN_USERNAME = "<Keycloak administrator>"
$env:KEYCLOAK_ADMIN_PASSWORD = "<password supplied locally>"
$env:PEA_WEB_REDIRECT_URIS = "https://dach1980.github.io/Personal_Expert_AI_Web/"
$env:PEA_WEB_ORIGINS = "https://dach1980.github.io"

python scripts/configure_keycloak_realm.py
~~~

The command performs a dry-run. It prints the issuer, JWKS endpoint, planned creations and blockers. It does not change Keycloak.

The script requires **KEYCLOAK_BASE_URL** to be the Keycloak origin without a path prefix such as **/oidc**.

## 4. Apply after reviewing the dry-run

Only after the dry-run has no blockers and the planned changes are correct:

~~~powershell
python scripts/configure_keycloak_realm.py --apply
~~~

The apply invocation repeats the full preflight before the first write. It creates missing resources and attaches the scope. It does not update existing resources. If an API failure occurs after creation has started, inspect the realm and rerun the dry-run before retrying; the script does not attempt destructive rollback.

## 5. Verify the realm

Open:

~~~text
http://localhost:30000/realms/stack-app/.well-known/openid-configuration
~~~

Confirm:

- **issuer** is exactly **http://localhost:30000/realms/stack-app**;
- **jwks_uri** points to the realm's published signing keys;
- **pea-api** is enabled and bearer-only;
- **pea-api-context** contains exactly the two expected mappers;
- **pea-web** is public, has Standard Flow enabled, Direct Access Grants disabled, and PKCE S256;
- **pea-api-context** is attached to **pea-web** as a default scope.

PEA's local environment currently uses:

- **OIDC_ISSUER=http://localhost:30000/realms/stack-app**
- **OIDC_JWKS_URL=http://localhost:30000/realms/stack-app/protocol/openid-connect/certs**
- **OIDC_AUDIENCE=pea-api**

Do not copy access tokens, passwords or client secrets into GitHub issues, source files or chat.

## 6. User and tenant provisioning

The **tenant_id** mapper copies the Keycloak user's **tenant_id** attribute into the access token. This claim is a tenant selector, not an authorization grant. PEA independently checks the external identity mapping, active user, tenant and membership in its own database.

Create the PEA user, tenant, project and memberships through the approved PEA provisioning workflow. Then explicitly bind the Keycloak identity using its immutable **sub** and the exact issuer:

~~~powershell
$env:DATABASE_URL = "<PEA database URL supplied locally>"
python scripts/provision_oidc_identity.py --issuer "http://localhost:30000/realms/stack-app" --subject "<Keycloak sub>" --login "<existing PEA user login>"
~~~

Do not create memberships merely by changing a Keycloak attribute. Do not run **bootstrap_initial_workspace.py** against a populated database.

## 7. Bionic integration is a later phase

The current local Kubernetes environment has the Keycloak control plane but no confirmed Bionic application deployment or Bionic OIDC client. Therefore this first bootstrap deliberately does not create or modify a Bionic client, worker client, gateway, or delegation configuration.

Before integrating Bionic, inspect its actual deployment and trust boundary. PEA remains the authorization owner and independently validates signed tokens and tenant/project memberships. Workload authentication and PEA-owned scheduled-task delegation must be designed and provisioned separately.
