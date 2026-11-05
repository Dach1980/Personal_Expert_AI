"""Provision initial PEA system-admin permissions through an audited DB-owner operation.

Run from the repository root with DATABASE_URL pointing to a protected PostgreSQL
administrative connection. This script never accepts browser or JWT supplied IDs.
"""
from __future__ import annotations

import argparse
import sys
from uuid import uuid4

from sqlalchemy import select, text

from app.storage.database import get_session_factory
from app.storage.models import SystemAdminGrant, SystemAuditEvent, User

PERMISSIONS = (
    "system.audit.read",
    "system.roadmap.read",
    "system.tenants.read",
    "system.tenants.manage",
    "system.admins.manage",
    "system.integrations.manage",
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target-login", required=True, help="Existing active PEA login receiving permissions")
    parser.add_argument("--operator-login", required=True, help="Existing active PEA login recorded as grant operator")
    parser.add_argument(
        "--permission",
        action="append",
        choices=PERMISSIONS,
        required=True,
        help="Permission to grant; repeat for multiple permissions",
    )
    parser.add_argument("--reason", required=True, help="Change ticket or explicit administrative reason")
    parser.add_argument(
        "--confirm",
        action="store_true",
        help="Actually apply the grants; without this flag the command refuses to mutate data",
    )
    args = parser.parse_args()

    target_login = args.target_login.strip()
    operator_login = args.operator_login.strip()
    reason = args.reason.strip()
    permissions = tuple(dict.fromkeys(args.permission))
    if not target_login or not operator_login or not reason:
        parser.error("target login, operator login and reason must not be blank")
    if len(reason) > 2000:
        parser.error("--reason must be no longer than 2000 characters")
    if not args.confirm:
        parser.error("No changes made. Re-run with --confirm after reviewing the exact target and permissions.")

    factory = get_session_factory()
    created_or_reactivated: list[str] = []
    unchanged: list[str] = []
    with factory() as session, session.begin():
        privileged = session.execute(
            text(
                "SELECT rolsuper OR rolbypassrls "
                "FROM pg_roles WHERE rolname = current_user"
            )
        ).scalar_one_or_none()
        if not privileged:
            print(
                "Refusing to provision grants: DATABASE_URL must use a PostgreSQL "
                "superuser or BYPASSRLS operator role.",
                file=sys.stderr,
            )
            return 4

        target = session.scalar(select(User).where(User.login == target_login))
        operator = session.scalar(select(User).where(User.login == operator_login))
        if target is None or target.status != "active":
            print("Target PEA user does not exist or is inactive.", file=sys.stderr)
            return 2
        if operator is None or operator.status != "active":
            print("Operator PEA user does not exist or is inactive.", file=sys.stderr)
            return 3

        for permission in permissions:
            grant = session.scalar(
                select(SystemAdminGrant).where(
                    SystemAdminGrant.user_id == target.id,
                    SystemAdminGrant.permission == permission,
                )
            )
            if grant is not None and grant.status == "active":
                unchanged.append(permission)
                continue
            if grant is None:
                grant = SystemAdminGrant(
                    id=uuid4(),
                    user_id=target.id,
                    permission=permission,
                    status="active",
                    granted_by=operator.id,
                    reason=reason,
                )
                session.add(grant)
            else:
                grant.status = "active"
                grant.granted_by = operator.id
                grant.reason = reason
            session.flush()
            session.add(
                SystemAuditEvent(
                    id=uuid4(),
                    actor_user_id=operator.id,
                    action="system_admin.grant.provisioned",
                    target_type="system_admin_grant",
                    target_id=grant.id,
                    tenant_id=None,
                    outcome="success",
                    details={
                        "target_user_id": str(target.id),
                        "target_login": target.login,
                        "permission": permission,
                        "reason": reason,
                        "provisioning_method": "out_of_band_operator_script",
                    },
                )
            )
            created_or_reactivated.append(permission)

    print(f"Target user: {target_login} ({target.id})")
    print(f"Operator: {operator_login} ({operator.id})")
    print(f"Granted/reactivated: {', '.join(created_or_reactivated) or 'none'}")
    print(f"Already active: {', '.join(unchanged) or 'none'}")
    print("An append-only system audit event was recorded for every new or reactivated grant.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
