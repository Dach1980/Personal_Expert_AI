# Initial system administrator provisioning

PEA system-admin permissions are global platform grants. They are not tenant roles, Keycloak realm roles, frontend flags, or JWT claims. Every administrative API call continues to verify the active grant in PostgreSQL.

## Controlled first grant

The first grant must be provisioned out of band by an operator using a protected PostgreSQL connection whose current role is a superuser or has BYPASSRLS. The runtime application role must not be given write access to system_admin_grants.

Use scripts/provision_system_admin.py. It requires an existing active PEA target login, an existing active operator login, explicit permission names, a reason/change reference, and the explicit --confirm switch.

Example (replace all placeholders; never put passwords in the command):

```powershell
$env:DATABASE_URL = "postgresql+psycopg://<privileged-role>@<host>:5432/<database>"
python -m scripts.provision_system_admin `
  --target-login "<target-user-login>" `
  --operator-login "<operator-user-login>" `
  --permission system.audit.read `
  --permission system.tenants.read `
  --reason "Initial platform administrator bootstrap; change <ticket>" `
  --confirm
```

The script checks the database role before writing, verifies both PEA users are active, creates or reactivates only the requested grants, and writes an append-only system_audit_events record for every grant it changes. Existing active grants are left unchanged. It does not create users, tenant memberships, or projects.

The --operator-login value is the human attribution stored in the audit record; it is not a substitute for protecting privileged database credentials. The privileged database session is the actual authority for this bootstrap action.

## Permissions for the initial Audit & Roadmap screen

Grant only the permissions required by the intended operator:

- system.audit.read — read platform audit events;
- system.tenants.read — read platform tenant inventory;
- system.roadmap.read — reserved for a future server-backed roadmap API.

Do not grant system.tenants.manage or system.admins.manage merely to make the read-only screen visible. Those permissions are for separate management workflows.

## Post-provisioning verification

1. Sign in through Keycloak using the target user.
2. Call GET /api/v1/admin/me and verify the exact expected permission list.
3. Call GET /api/v1/admin/audit-events and GET /api/v1/admin/tenants.
4. Sign in as a normal user and verify the same endpoints return 403.
5. Verify the bootstrap action appears in the append-only audit journal.

Never commit database credentials, Keycloak tokens, or production identifiers to Git.