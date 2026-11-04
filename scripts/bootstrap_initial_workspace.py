"""Create the first PEA user, tenant and project for a fresh local installation.

This is an explicit bootstrap operation. It does not create a Keycloak user,
password, external identity mapping or any cloud account.
"""
from __future__ import annotations

import argparse
import sys
from uuid import uuid4

from sqlalchemy import select

from app.storage.database import get_session_factory
from app.storage.models import User
from app.storage.services import ProjectService, TenantService


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--login", required=True, help="Local PEA login identifier (often an email)")
    parser.add_argument("--tenant-name", required=True, help="Name of the first PEA tenant")
    parser.add_argument("--project-name", required=True, help="Name of the first PEA project")
    parser.add_argument("--project-code", help="Optional project code")
    args = parser.parse_args()

    login = args.login.strip()
    tenant_name = args.tenant_name.strip()
    project_name = args.project_name.strip()
    if not login or len(login) > 255:
        parser.error("--login must contain 1..255 characters")
    if not tenant_name or len(tenant_name) > 255:
        parser.error("--tenant-name must contain 1..255 characters")
    if not project_name or len(project_name) > 255:
        parser.error("--project-name must contain 1..255 characters")

    factory = get_session_factory()
    with factory() as session, session.begin():
        existing = session.scalar(select(User).where(User.login == login))
        if existing is not None:
            print(
                "A PEA user with this login already exists. Refusing to create or modify "
                "tenant memberships; use the existing administrative workflow instead.",
                file=sys.stderr,
            )
            return 2

        user = User(id=uuid4(), login=login, status="active")
        session.add(user)
        session.flush()

        tenant = TenantService(session).create(tenant_name, user.id)
        project = ProjectService(session).create(
            tenant.id,
            user.id,
            name=project_name,
            code=args.project_code,
        )
        session.flush()

        result = {
            "user_id": str(user.id),
            "login": user.login,
            "tenant_id": str(tenant.id),
            "tenant_name": tenant.name,
            "project_id": str(project.id),
            "project_name": project.name,
        }

    for key, value in result.items():
        print(f"{key}={value}")
    print("Bootstrap complete. Next, provision the user's Keycloak (issuer, subject) mapping.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
