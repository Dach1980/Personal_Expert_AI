# System administration and tenant context — design

- Status: implementation contract; backend implementation pending
- Date: 2026-11-05
- Repository: Dach1980/Personal_Expert_AI
- Target branch: main

## 1. Purpose

PEA must provide two separate authorization domains:

1. Tenant authorization: users may discover and select only tenants where they have an active PEA membership.
2. System administration: explicitly provisioned users may perform selected cross-tenant administrative operations.

Tenant roles (owner, tenant_admin, member) never imply system-admin privileges. Keycloak authenticates a subject; PEA remains authoritative for identity mapping, membership, permissions and audit history.

## 2. Current baseline and gaps

The current Principal contains user_id and one tenant_id. The RS256/JWKS verifier requires a tenant_id claim, sets transaction-local app.tenant_id, and verifies active tenant membership. All tenant-owned tables use tenant_id RLS. This is a sound single-active-tenant baseline but cannot discover multiple memberships or safely switch context.

The existing audit_events table is tenant-scoped and requires a tenant id. It cannot be the global system audit ledger. The membership role constraint has no global administrator role; do not add system_admin to tenant roles.

SECURITY_MODEL.md also contains an older HS256/JWT_SECRET description. The implementation is RS256/JWKS with issuer, audience, expiry and required claims; reconcile the document with the implementation.

## 3. Tenant identity and context contract

### 3.1 Authentication stages

Separate authentication from tenant selection:

- AuthenticatedIdentity: user_id, OIDC issuer and subject, plus verified token metadata. It has no active tenant.
- Principal: user_id, tenant_id and active membership role. It is created only after selected-tenant membership is revalidated in the database.

Resolve external identity by exact (issuer, subject). Require active ExternalIdentity and User records. Never use Keycloak username, email, unverified headers or browser-provided user id as identity.

### 3.2 Tenant selection

Add optional X-Tenant-ID as a context selector. It is untrusted input, never proof of authorization. For every request:

1. Verify RS256 token and resolve the provisioned user.
2. Set transaction-local app.user_id from that resolved user.
3. Read active memberships visible to that user.
4. Select tenant from X-Tenant-ID. For backward compatibility only, fall back to the verified legacy tenant_id claim when the header is absent.
5. Require active membership in the selected tenant and an active tenant record.
6. Set transaction-local app.tenant_id only after these checks.
7. Construct Principal and continue existing tenant/project ACL checks.

If no selector exists and there is no legacy tenant_id claim, fail closed with a clear 400. Unknown or unauthorized tenants must not reveal existence (404). Revalidate membership on every request. A legacy token tenant_id is a compatibility default, not a complete membership list.

### 3.3 Membership discovery API

Add GET /api/v1/tenants:

- Requires valid bearer token and a provisioned active identity.
- Does not require an active tenant selector.
- Returns only active memberships for the authenticated user, with tenant id/name and tenant role.
- Does not expose other users' memberships or project data.

The identity-only DB context must allow reading only the current user's membership rows and corresponding tenant records. It must not broaden access to projects, documents, conversations, knowledge, reviews or audit events.

### 3.4 RLS changes

Add set_user_context(session, user_id), callable only with the user id returned by verified ExternalIdentity resolution. Extend RLS only for discovery tables:

- memberships: allow rows for app.tenant_id OR rows whose user_id equals transaction-local app.user_id.
- tenants: allow app.tenant_id OR tenants referenced by an active membership belonging to app.user_id.

Keep all other tenant-owned tables restricted to app.tenant_id. Keep FORCE ROW LEVEL SECURITY. Runtime DB role must not be superuser, table owner or BYPASSRLS.

Custom PostgreSQL GUC values are trusted application context, not cryptographic credentials. Backend code sets them only from verified identity and membership results; request payloads and browser-forwarded identity headers must never set them. SQL injection prevention remains mandatory.

### 3.5 Switching behavior

Web sends X-Tenant-ID on the next request. PEA revalidates membership every time; a prior successful selection does not create a long-lived authorization grant. After switching, Web clears tenant-dependent project, document, conversation, knowledge and cached search state, then reloads allowed projects. On 401/403/404 it clears stale context and must not retain data from the previous tenant.

Bionic forwards the verified bearer token and selected tenant selector to PEA without converting the selector into a trusted claim. PEA independently verifies identity and membership. Public gateway requests must have browser-supplied identity/forwarded-token headers stripped.

## 4. System-admin authorization

### 4.1 Separate grant model

Add global system_admin_grants, separate from tenant Membership:

- id UUID primary key
- user_id UUID not null, FK users.id
- permission VARCHAR(100) not null
- status VARCHAR(20) constrained to active/revoked
- granted_by UUID nullable, FK users.id
- reason TEXT not null
- created_at and updated_at
- unique (user_id, permission)

Initial permission vocabulary:
- system.audit.read
- system.roadmap.read
- system.tenants.read
- system.tenants.manage
- system.admins.manage

Check permissions against PEA database grants on every protected request. Do not trust Keycloak realm/client roles, frontend flags, local storage, query parameters or tenant role names.

Initial grant provisioning is an out-of-band audited operator action. Do not create a self-service grant endpoint or automatically promote the first tenant owner. Later grant-management API requires system.admins.manage, records grant/revocation in system audit, and prevents removal of the last active administrator with recovery permissions.

### 4.2 Global audit ledger

Add system_audit_events because audit_events is intentionally tenant-scoped:

- id UUID primary key
- actor_user_id UUID nullable, FK users.id
- action VARCHAR(120) not null
- target_type VARCHAR(100) not null
- target_id UUID nullable
- tenant_id UUID nullable, FK tenants.id (nullable for platform-wide events)
- request_id VARCHAR(100) nullable
- outcome VARCHAR(30) not null
- details JSONB not null, default empty object
- created_at TIMESTAMPTZ not null, default now()

Index created_at, (tenant_id, created_at), and (target_type, target_id). Runtime role may insert but may not update/delete. Global audit reads require system.audit.read. Tenant-scoped events remain governed by tenant ACL/RLS.

Record successful and denied system-admin actions, tenant context switches, grant/revocation operations and cross-tenant administrative access. Never store bearer tokens, secrets, document contents or unnecessary personal data in audit details.

### 4.3 API contract

- GET /api/v1/admin/me — effective PEA system permissions; non-admin receives 403.
- GET /api/v1/admin/audit-events — paginated, filterable global audit events; requires system.audit.read.
- GET /api/v1/admin/tenants — cross-tenant tenant inventory; requires system.tenants.read.
- Future mutations require dedicated permissions and explicit audit events; no generic unrestricted admin CRUD.

Use stable versioned Pydantic schemas with pagination limits/cursors. Cross-tenant endpoints must not silently bypass tenant RLS or reuse a tenant Principal as an admin grant.

### 4.4 Database boundary

A user may read only their own system grant rows for /admin/me. A system audit event may be inserted only with actor equal to verified app.user_id. Audit reads require an active database grant for the verified user, not a caller-controlled app.is_admin flag. Runtime SQL privileges deny UPDATE/DELETE on the audit ledger. Migration/DDL credentials remain separate from the application role.

## 5. Required tests and release gates

### Authentication and tenant context
- Valid legacy token without header uses verified legacy tenant claim.
- Valid token with selected tenant header switches only when active membership exists.
- Header naming another user's tenant is denied.
- Inactive/revoked membership and inactive tenant are denied.
- Malformed selector is rejected.
- Membership discovery works without tenant claim and reveals only caller's memberships.
- No selector never grants access to tenant-owned endpoints.
- Context is transaction-local and cannot leak across pooled sessions or rollback.
- Cross-tenant project/document/conversation/search access remains denied after switching.
- Existing RLS tests run with restricted application role.

### System administration
- Tenant owner/admin/member do not gain system permissions implicitly.
- Missing, revoked and insufficient grants are denied.
- Each permission is checked independently.
- Cross-tenant admin endpoints deny normal tenant principals.
- Audit records actor, request id, target, outcome and tenant where applicable.
- Runtime role cannot update/delete the audit ledger.
- Non-admin cannot read global audit events; granted admin can.
- Revocation takes effect on next request.
- No token, secret or document content is persisted in audit details.

### Migration and schema
- ORM metadata and Alembic DDL match for new tables, constraints, indexes and FK delete rules.
- Upgrade → downgrade → upgrade passes on clean PostgreSQL 16.
- RLS is tested under restricted runtime role, not table owner.
- Existing tenant isolation and document integrity tests remain green.

## 6. Implementation order

1. [x] Add SystemAdminGrant and SystemAuditEvent ORM models, Alembic migrations, RLS policies and metadata unit tests. Migration/schema parity passed on commit e7f60f85; subsequent full integration tests are in progress.
2. [x] Implement identity-only authentication context, optional legacy tenant claim and GET /api/v1/tenants membership discovery.
3. [x] Implement X-Tenant-ID selection with per-request active-membership validation and identity-scoped RLS. Full cross-tenant PostgreSQL negative tests are running.
4. [x] Implement database-backed system permission dependencies and read-only GET /api/v1/admin/me, /api/v1/admin/audit-events and /api/v1/admin/tenants endpoints.
5. [ ] Complete CI, migration downgrade/re-upgrade, schema parity and all authorization/RLS tests on the latest main commit; publish final OpenAPI/API contract snapshot.
6. [ ] Integrate Web tenant selector and protected Audit & Roadmap only after backend tests pass and an initial system-admin grant is provisioned out-of-band.
7. [ ] Update Bionic adapter to forward X-Tenant-ID while retaining independent token validation; add adapter contract tests.

No frontend-only admin visibility or tenant switch is accepted as complete until the corresponding PEA endpoint and negative authorization tests pass.


## Implementation update — 2026-11-05

The first backend implementation slice now exists in main:

- SystemAdminGrant and SystemAuditEvent models plus revisions 0012 and 0014.
- Revision 0013 adds identity-scoped discovery policies only to memberships and tenants. Other tenant-owned tables remain tenant-context isolated.
- Authentication is split into AuthenticatedIdentity and tenant-bound Principal. The verified ExternalIdentity mapping sets app.user_id; selected tenant membership is checked before app.tenant_id is set.
- GET /api/v1/tenants lists only the caller's active memberships. X-Tenant-ID is an untrusted selector and is revalidated on every request; legacy tenant_id claim remains a compatibility fallback.
- System permissions are loaded from PEA grants, not Keycloak roles or frontend flags. Read-only admin endpoints expose the caller's permissions, global audit events and tenant inventory.
- No system-admin grants have been provisioned yet. Provisioning remains out-of-band; therefore the admin endpoints correctly deny all users until a grant is explicitly created.
- CI found and drove fixes for ORM/migration JSONB parity, FastAPI Header default handling, backward-compatible Principal test fixtures and inactive-tenant status validation. Do not treat earlier intermediate failures as the final result; the latest main run is the acceptance target.
