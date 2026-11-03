"""Provision an already-existing PEA user for a Keycloak identity.

This command deliberately does not create users, tenants or memberships.
Run it from the repository root after setting DATABASE_URL.
"""
from __future__ import annotations

import argparse
import sys

from sqlalchemy import select

from app.storage.database import get_session_factory
from app.storage.models import ExternalIdentity, Membership, User


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--issuer", required=True, help="Exact Keycloak realm issuer URL (iss claim)")
    parser.add_argument("--subject", required=True, help="Immutable Keycloak sub claim")
    parser.add_argument("--login", required=True, help="Existing PEA user login")
    args = parser.parse_args()

    issuer = args.issuer.rstrip("/")
    subject = args.subject.strip()
    login = args.login.strip()
    if not issuer.startswith("https://") and not issuer.startswith("http://localhost"):
        parser.error("--issuer must use HTTPS (HTTP is allowed only for local development)")
    if not subject or len(subject) > 255:
        parser.error("--subject must contain 1..255 characters")

    factory = get_session_factory()
    with factory() as session, session.begin():
        user = session.scalar(select(User).where(User.login == login))
        if user is None or user.status != "active":
            print("No active PEA user exists for this login.", file=sys.stderr)
            return 2
        membership = session.scalar(
            select(Membership).where(
                Membership.user_id == user.id,
                Membership.status == "active",
            )
        )
        if membership is None:
            print("The PEA user has no active tenant membership.", file=sys.stderr)
            return 2

        existing = session.scalar(
            select(ExternalIdentity).where(
                ExternalIdentity.issuer == issuer,
                ExternalIdentity.subject == subject,
            )
        )
        if existing is not None:
            if existing.user_id != user.id:
                print("This Keycloak identity is already bound to a different PEA user.", file=sys.stderr)
                return 3
            if existing.status != "active":
                existing.status = "active"
            print(f"Identity mapping already exists for PEA user {user.id}.")
            return 0

        session.add(
            ExternalIdentity(
                issuer=issuer,
                subject=subject,
                user_id=user.id,
                status="active",
            )
        )
        session.flush()
        print(f"Provisioned Keycloak identity for PEA user {user.id}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
