# Database and ORM audit — 2026-11-01

## Scope and method

Reviewed the current `main` versions of:
- `app/storage/models.py`
- `app/storage/database.py`
- `migrations/versions/0001_initial_domain.py`
- `migrations/env.py`
- `alembic.ini`
- `tests/unit/test_database_models.py`
- `pyproject.toml`
- `docs/architecture/DATABASE_SCHEMA.md`

This is a source-level audit. No PostgreSQL server was available to this audit session; therefore no claim is made that `alembic upgrade`, `downgrade`, or live database integration tests passed.

## Executive result

The ORM and initial DDL describe the same 17 table names and are broadly aligned on columns, SQL types, primary keys, declared foreign keys, unique constraints, check constraints, and named indexes.

They are **not yet production-safe for multi-tenant/project isolation**. Most tenant and project relationships are independent single-column foreign keys. The database can therefore accept rows whose `tenant_id` does not match the tenant of the referenced project or parent record. Service-level filtering alone is not an adequate integrity boundary.

## Table inventory

All 17 ORM tables are present in the migration:

1. tenants
2. users
3. memberships
4. workspaces
5. projects
6. project_memberships
7. documents
8. document_versions
9. processing_runs
10. processing_artifacts
11. source_fragments
12. knowledge_items
13. knowledge_assertions
14. conversations
15. messages
16. memory_entries
17. audit_events

## Findings

### Critical — tenant/project ownership is not enforced by relational constraints

Examples:
- `projects.workspace_id` can reference a workspace owned by a different tenant.
- `project_memberships.tenant_id` can differ from the referenced project's tenant; the user is not required to have a tenant membership either.
- `documents.tenant_id` can differ from the referenced project's tenant.
- `document_versions` can reference a document and project that do not belong together, and can carry a different tenant.
- Processing runs, artifacts, source fragments, knowledge rows, assertions, conversations and memory rows can similarly combine unrelated tenant/project parents.
- `documents.current_version_id` references a version, but does not ensure that version belongs to that same document/project/tenant.

**Required remediation:** add candidate unique keys and composite foreign keys for tenant/project parentage; for document versions, enforce the same document/project/tenant tuple; enforce current-version ownership. Add PostgreSQL RLS only after a trusted transaction-local tenant context and connection-pool reset strategy are implemented.

### High — Alembic downgrade uses broad CASCADE

The downgrade drops all tables with `CASCADE`. This can silently remove dependent objects not owned by this migration (for example, external views or constraints). Prefer dependency-ordered explicit table drops without CASCADE, and let unexpected dependencies fail loudly.

### High — migration execution has not been exercised against PostgreSQL

The current test file checks table registration and three selected constraints only. It does not:
- compare the complete ORM metadata with the migration-created schema;
- exercise upgrade/downgrade/re-upgrade;
- test cross-tenant or cross-project writes;
- validate actual PostgreSQL catalog indexes and constraints.

A real PostgreSQL 16 CI service/container is required for these checks.

### Medium — referential actions are implicit

ORM and DDL foreign keys currently omit `ON DELETE`, so PostgreSQL defaults to `NO ACTION`. This is safer than broad cascading deletion for project records, but should be explicit in the schema contract. No ORM relationships/cascade configuration currently exists, so ORM unit-of-work delete semantics are not yet defined.

### Medium — defaults are split between Python and database

Status and JSON fields use Python-side `default` values in ORM, while the DDL does not declare corresponding SQL `DEFAULT` values. Inserts made outside SQLAlchemy therefore need to provide those fields. Decide whether database-level defaults are required and align both sides.

### Medium — incomplete index coverage

Several frequently filtered FK columns have no dedicated index, including multiple `tenant_id` columns and some parent references. PostgreSQL does not automatically index referencing FK columns. Add indexes based on expected access patterns and verify query plans rather than blindly indexing every column.

### Medium — polymorphic references cannot be FK-validated

`memory_entries.scope_id` points to different entity types according to `scope_type`; `audit_events.target_id` is also polymorphic. The database cannot validate these references with the current design. This needs application-level validation or a normalized target table.

### Low — timestamp update semantics

`updated_at` has a SQLAlchemy `onupdate` expression but no database trigger. Updates performed outside SQLAlchemy will not update it. Decide whether this is acceptable or move the behavior into PostgreSQL.

## Foreign keys and delete behavior

All current foreign keys use PostgreSQL's default `NO ACTION` behavior because neither the DDL nor ORM specifies `ondelete`. No broad ORM delete cascades are declared. This avoids accidental child deletion, but parent deletion will be rejected while dependent rows exist.

The downgrade's `CASCADE` is separate from normal row deletion and is too broad for a reusable migration.

## Alembic assessment

Source inspection:
- `env.py` imports model metadata and enables `compare_type=True`.
- `DATABASE_URL` can override the placeholder URL.
- The initial migration is a frozen DDL snapshot, not generated from live ORM metadata.
- The cyclic documents/document_versions relationship is created by creating both tables and adding the current-version FK afterward; this ordering is valid in PostgreSQL.
- The migration splits its DDL on semicolons and executes each statement individually.

Not verified:
- PostgreSQL syntax/runtime behavior on the supported server version;
- actual upgrade, downgrade, and re-upgrade;
- Alembic autogenerate diff after upgrade;
- downgrade behavior in the presence of external dependencies.

## Required next implementation steps

1. Add explicit tenant/project composite constraints and candidate unique keys.
2. Add document/version same-parent integrity, including current-version ownership.
3. Add repository methods that always scope reads and writes by authenticated tenant and authorized project.
4. Add service methods that validate membership and reject caller-supplied tenant/project mismatches.
5. Add tests for cross-tenant and cross-project access and attempted inconsistent inserts.
6. Add PostgreSQL-backed CI tests for migration lifecycle and metadata/schema parity.
7. Remove `CASCADE` from downgrade and make delete behavior explicit.
8. Decide and align server-side defaults and timestamp update policy.

## Verification status

| Check | Status |
|---|---|
| 17 table names present in ORM and migration | Source-reviewed |
| Column/type/nullability parity | Source-reviewed; requires automated PostgreSQL catalog comparison |
| PK/FK/UNIQUE/CHECK/index parity | Source-reviewed; requires automated metadata/catalog comparison |
| Delete behavior | Source-reviewed; implicit NO ACTION |
| Alembic upgrade/downgrade/re-upgrade | Not run — PostgreSQL unavailable |
| Repository/service isolation | Not implemented at audit start |
| Cross-project/cross-tenant tests | Not implemented at audit start |
| RLS | Not implemented |

## Work completed after the source audit

The following first-pass application-layer components have now been added on `main`:

- `app/storage/repositories.py`: tenant, project and document repositories. Scoped lookups require tenant ID; document lookups additionally require project ID.
- `app/storage/services.py`: tenant, project and document services. Access checks require active tenant membership and, for project/document access, active project membership. Project creation requires a tenant owner/admin role. Optional workspace assignment is checked against the same tenant.
- `tests/unit/test_storage_access.py`: SQL-scope assertions and service-level denial tests for missing membership and insufficient tenant role.

These are an initial application-layer guard, not a substitute for database composite constraints/RLS. They have not yet been executed in a Python environment in this session. The project service is not yet wired to HTTP routes or an authentication dependency; callers must pass a trusted authenticated user ID, never a user ID supplied by an untrusted request body.

Updated status:
| Item | Status |
|---|---|
| Tenant/Project/Document repositories | Implemented, runtime tests not run |
| Tenant/Project/Document services | Implemented, runtime tests not run |
| Scoped access unit tests | Added, runtime tests not run |
| Composite tenant/project foreign keys | Not implemented |
| PostgreSQL RLS | Not implemented |
| PostgreSQL migration lifecycle tests | Not implemented |
| ORM-to-live-schema parity test | Not implemented |


## Follow-up implementation and CI evidence

After the initial source review, the following changes were committed to `main`:

- Added `0002_tenant_isolation`: composite candidate keys and foreign keys enforce tenant/project consistency across workspaces, projects, project memberships, documents, versions, processing runs/artifacts, source fragments, knowledge items/assertions, conversations/messages and project memory.
- Replaced the unscoped current-version FK with a composite FK tying the selected version to the same tenant, project and document.
- Enabled and forced RLS for tenant-owned tables and the tenants table. RLS uses transaction-local `app.tenant_id`.
- Added `set_tenant_context` and transaction-scoped request sessions with commit on success and rollback on exception.
- Removed `CASCADE` from the initial migration downgrade.
- Added JWT verification and authenticated Tenant/Project/Document endpoints. Tokens are expected from an external trusted issuer; token issuance/password lifecycle is not implemented.
- Added PostgreSQL 16 GitHub Actions CI with a non-owner, non-superuser, `NOBYPASSRLS` runtime test role.
- Added PostgreSQL integration tests for RLS visibility, cross-tenant FK rejection and ORM/database table-column inventory.

### Observed CI result (run for commit `ca4cd6e`)

The following steps completed successfully on PostgreSQL 16:
- Alembic upgrade to head;
- `alembic check` — no new upgrade operations detected;
- PostgreSQL integration tests — 3 passed;
- Alembic downgrade to base;
- Alembic re-upgrade to head.

The full test suite initially stopped during collection because the installed Starlette TestClient now requires the `httpx2` package. That dependency has been added to the development extras; a new workflow run is required to confirm the full suite and lint.

The metadata check emitted a SQLAlchemy warning about the intentional circular dependency between `documents` and `document_versions`. PostgreSQL migration execution succeeds because the initial migration creates both tables and adds the current-version constraint afterward. This warning should be addressed in a later ORM relationship/metadata cleanup, but it did not produce an Alembic diff.

### Remaining security/operational caveats

- A trusted identity provider must issue JWTs with the configured issuer/audience and claims. The application does not yet provide user registration, password storage, refresh tokens or token issuance.
- Production runtime DB credentials must be a separate non-owner role without SUPERUSER/BYPASSRLS. Never run the API as the migration owner or a superuser.
- The current CI tests prove representative cross-tenant isolation and schema inventory, not every possible endpoint/operation or all 17-table adversarial combinations.
- The schema inventory test checks table and column names; `alembic check` supplies additional metadata comparison. A broader catalog-level assertion for every FK, index, check and delete action is still desirable.
- RLS is enabled on the initial tenant-owned tables; `users` remains a global identity table and must only be queried through authenticated identity-specific paths.
- Before production, add integration tests for every composite FK family, token revocation/rotation, membership changes, and all API authorization roles.
