# Functional acceptance — 2026-11-06

Scope: Personal Expert AI backend, Personal Expert AI Web and the Bionic fork.
This is a source/CI acceptance record, not a live Stack acceptance. No credentials,
Keycloak realm, Bionic runtime host, PEA API host or local LM Studio endpoint were
available to this GitHub-only check.

## Repository revisions inspected

- PEA backend: 1f75bced905dd7373f535b5a4944b2bc170000f2
- Web frontend: 4dde3a7f92ae24411c8b47efea7ae19dfdcf3a89
- Bionic fork: 50512302a9f6e0a8a353886521273a81b7ba8e9b

## Acceptance matrix

| Area | Source/CI result | Live result | Decision |
|---|---|---|---|
| Keycloak OIDC | Web uses Authorization Code + PKCE, state/nonce, RS256 ID-token/JWKS verification and memory-only token storage. PEA independently verifies RS256/JWKS access tokens, issuer, audience, time claims, external identity mapping and active membership. | Not run: actual realm, client redirect URIs, pea-api audience, trusted gateway token injection and secrets are deployment-owned. | Source implementation present; live login pending. |
| Tenant/project switching | PEA membership discovery and X-Tenant-ID validation are implemented. Web lists active memberships, remembers only a preferred tenant UUID and sends tenant-scoped requests through fixed adapter routes. A failure path was hardened so an unaccepted tenant is not committed to local state or localStorage. | Not run against two real tenants and two projects. | Source implementation present; live negative/positive switch tests pending. |
| Chats | PEA conversation/message schema and scoped APIs exist. Bionic adapter exposes conversation list/create, history and streaming message routes. Web has create/select/history/SSE UI. | Not run against deployed Bionic, PEA and LM Studio. | API/UI source present; live chat pending. |
| Bionic Agent Runtime + pea_search | PEA owns project bindings and short-lived revocable grants. Bionic scheduled-task runtime obtains a confidential workload token, creates a task-bound grant, exposes only query/top_k to the model, treats fragments as untrusted and allowlists citations. | Not run against Stack Keycloak, worker secrets, live binding or PEA database. | Scheduled-task source path present; live acceptance pending. |
| Interactive chat retrieval | Bionic ordinary /completions/{chat_id} calls create_request(..., None); it has no conversation-scoped PEA retrieval context and does not register pea_search. The Web chat adapter currently streams the PEA conversation response; it must not be described as Bionic Agent Runtime retrieval. | Not applicable until the separate conversation-scoped authorization/runtime path is implemented. | BLOCKED — implementation gap. |
| Citations | Scheduled runtime validates final [PEA:<fragment_id>] markers against IDs returned by PEA. PEA search returns fragment/document/version/locator metadata; Web can render citation payloads. | No live source-document query or citation click-through was performed. | Source controls present for scheduled path; interactive citations pending. |
| Tenant/project isolation | PEA CI covers PostgreSQL RLS, tenant/project composite FK constraints, chat conversation/message scope and cross-tenant invisibility. | No live multi-tenant identity/session test against deployment. | Automated DB tests pass; live acceptance pending. |

## CI evidence

### PEA backend

Workflow: https://github.com/Dach1980/Personal_Expert_AI/actions/runs/42126697868

- PostgreSQL migration downgrade to base and upgrade to head completed.
- ORM/schema parity check completed.
- pytest -q: 136 passed.
- ruff check app migrations tests: all checks passed.
- The PostgreSQL integration suite includes tenant RLS isolation and conversation/message tenant/project scope tests.

### Web frontend

Workflow: https://github.com/Dach1980/Personal_Expert_AI_Web/actions/runs/42167427094

- The previous run on the earlier revision passed the frontend protocol tests (10 passed), TypeScript build and Vite build.
- This revision includes a fail-closed tenant-switch state update: the new tenant is committed only after its authorized project/chat data has loaded; failure clears partially loaded data and does not persist the rejected tenant.
- The current Pages workflow must complete before this revision is marked CI-green.
- Browser acceptance already confirmed by the user on 2026-11-06: JS and CSS assets return HTTP 200, no JavaScript console errors, and the application interface renders.

### Bionic fork

Workflow: https://github.com/Dach1980/bionic-personal-expert-ai/actions/runs/42167251443

- A previous current-source run failed only at cargo fmt --all -- --check due to one formatting difference in the new PEA retrieval test.
- That formatting difference was corrected in 50512302a9f6e0a8a353886521273a81b7ba8e9b.
- The new run is the verification gate for this revision; compile and Rust/Agent Runtime/tool-runtime tests must complete before acceptance is green.

## Required remaining release gates

1. Provision and inspect the actual Stack-managed Keycloak realm and version.
2. Verify the public Web OIDC client redirect URI, exact issuer, PKCE S256, pea-api audience and trusted gateway behavior. The GitHub Pages deployment is currently built in explicit demo mode and is not evidence of live OIDC/API configuration.
3. Set deployment-only PEA/Bionic workload credentials and private API URLs; do not commit secrets.
4. Provision at least two test tenants, distinct projects and test users with deliberately different memberships.
5. Run browser login/logout/refresh/expiry tests and verify that unauthorized tenant selection fails closed.
6. Create a Bionic-project → PEA tenant/project binding; run a scheduled task with a permitted owner and verify grant expiry, revocation, disabled binding, revoked membership and cross-project substitution all fail closed.
7. Implement a separate conversation-scoped PEA retrieval grant/context for interactive Bionic chats. Do not reuse scheduled-task IDs or scheduled-task grants as chat identity.
8. Add an interactive bounded tool loop that persists tool-call results, streams final text and citations, and validates every citation against the exact PEA fragments returned in that conversation.
9. Verify a user in tenant A cannot retrieve tenant B's project, document, conversation, fragment or citation by changing path IDs, headers, cached state or model tool arguments.
10. Verify citation click-through resolves to the exact source document/version/page or fragment in the authorized project.

## Acceptance conclusion

Database integrity and backend source tests are green on the inspected PEA revision.
The Web application has been rendered successfully in the user's browser; the latest
tenant-switch hardening is awaiting its CI result. Bionic scheduled retrieval has a
source implementation and its formatting regression was corrected; its current
Rust CI is still running. Full functional acceptance is not yet passed because the
live Stack/OIDC environment is not available for this check and interactive
Bionic chat retrieval is not implemented.
