# PostgreSQL runtime role

Migrations must be executed using a dedicated schema-owner/DDL connection. The FastAPI process must use a separate role that does not own tables and has neither SUPERUSER nor BYPASSRLS.

Example (execute as the database administrator after `alembic upgrade head`):

```sql
CREATE ROLE app_runtime LOGIN PASSWORD 'REPLACE_WITH_A_LONG_RANDOM_SECRET'
    NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOBYPASSRLS;

GRANT CONNECT ON DATABASE personal_expert TO app_runtime;
GRANT USAGE ON SCHEMA public TO app_runtime;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO app_runtime;

ALTER DEFAULT PRIVILEGES FOR ROLE personal_expert IN SCHEMA public
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO app_runtime;
```

If the migration owner has a different name from `personal_expert`, use that actual role in `ALTER DEFAULT PRIVILEGES`. Execute the default-privileges statement as the role that will create future tables, or as a sufficiently privileged administrator specifying that role.

Configure the application with the runtime URL, not the migration URL:

```text
DATABASE_URL=postgresql+psycopg://app_runtime:...@localhost:5432/personal_expert
JWT_SECRET=...
JWT_ISSUER=...
JWT_AUDIENCE=...
```

The migration connection must not be used by the API process. Superusers and roles with BYPASSRLS bypass row-level security regardless of table policies. Table owners are subject to RLS only because the migrations explicitly use FORCE ROW LEVEL SECURITY.

The runtime role is intentionally not granted schema creation, role administration, or ownership. Database migrations remain a separate deployment operation.
