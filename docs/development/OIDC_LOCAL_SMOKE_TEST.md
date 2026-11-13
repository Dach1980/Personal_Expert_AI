# Local OIDC Authorization Code + PKCE smoke test

This check exercises the **pea-web** public client from a local WSL terminal. It uses
Authorization Code Flow with PKCE S256, validates the ID token and the PEA API access
token against the configured realm JWKS, and never prints or saves either token.

## Important: one exact loopback redirect URI is required

The current `pea-web` client has the GitHub Pages redirect URI. The local smoke test
uses this additional exact callback:

```text
http://127.0.0.1:8765/callback
```

Before running the test, an administrator must add that URI to:

**Keycloak → realm stack-app → Clients → pea-web → Settings → Valid redirect URIs**

Keep the existing GitHub Pages URI. Add only the exact loopback URI above; do not use
wildcards. Do not change Web origins, client authentication, flow toggles or PKCE settings.
The callback listener binds only to `127.0.0.1`.

This is a deliberate, narrowly scoped Keycloak configuration change. Do not make it until
the user has reviewed and approved the change. It can be removed from Valid redirect URIs
after the smoke test.

## Run from WSL

The script requires the project's existing Python environment and PyJWT dependency:

```bash
.venv/bin/python scripts/oidc_pkce_smoke.py
```

Accept the default issuer:

```text
http://localhost:30000/realms/stack-app
```

The script opens the system browser. Sign in as the normal test user. The browser returns
a one-time authorization code to the loopback callback; the script exchanges it using
the in-memory PKCE verifier.

## What a passing result means

- Authorization Code + PKCE S256 completed.
- ID token signature, issuer, client audience and nonce were validated.
- Access token signature, issuer and `pea-api` audience were validated.
- The ID token and access token subjects match.

The script does **not** provision a PEA identity, tenant or membership. A passing token
check therefore does not imply that the user is authorized to access a PEA tenant.
Tenant binding and API authorization are separate acceptance steps.

## Data handling and limits

- No password is entered into the terminal or script.
- Authorization code, PKCE verifier, ID token and access token remain in process memory.
- Tokens are never printed, logged or written to disk.
- The callback listener binds to loopback only and accepts a single callback.
- The script is for local development only; it rejects non-local HTTP issuer/endpoints.
- The script does not call the PEA API and does not change Keycloak configuration.
