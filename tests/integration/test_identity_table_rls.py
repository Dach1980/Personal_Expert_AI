"""Restricted-role RLS and privilege tests for identity tables."""
import os
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError

from app.storage.database import build_session_factory

OWNER_DATABASE_URL = os.getenv("DATABASE_URL")
APP_DATABASE_URL = os.getenv("APP_DATABASE_URL")

pytestmark = pytest.mark.skipif(
    not OWNER_DATABASE_URL or not APP_DATABASE_URL,
    reason="schema-owner DATABASE_URL and restricted APP_DATABASE_URL are required",
)


def test_runtime_identity_tables_are_self_scoped_read_only_and_not_migration_visible():
    user_a, user_b = uuid4(), uuid4()
    issuer = "https://sso.identity-rls.test/realms/pea"
    subject_a, subject_b = f"subject-{uuid4()}", f"subject-{uuid4()}"

    owner_factory = build_session_factory(OWNER_DATABASE_URL)
    try:
        with owner_factory() as session, session.begin():
            from app.storage.models import ExternalIdentity, User

            session.add_all([
                User(id=user_a, login=f"identity-a-{user_a}@test.local", status="active"),
                User(id=user_b, login=f"identity-b-{user_b}@test.local", status="active"),
            ])
            session.flush()
            session.add_all([
                ExternalIdentity(
                    id=uuid4(), issuer=issuer, subject=subject_a,
                    user_id=user_a, status="active",
                ),
                ExternalIdentity(
                    id=uuid4(), issuer=issuer, subject=subject_b,
                    user_id=user_b, status="active",
                ),
            ])
    finally:
        owner_factory.kw["bind"].dispose()

    runtime_engine = create_engine(APP_DATABASE_URL)
    try:
        with runtime_engine.connect() as conn, conn.begin():
            current_user = conn.execute(text("SELECT current_user")).scalar_one()
            assert current_user == "app_runtime"

            # Both identity tables fail closed without the corresponding context.
            assert conn.execute(text("SELECT id FROM users")).scalars().all() == []
            assert conn.execute(text("SELECT id FROM external_identities")).scalars().all() == []

            conn.execute(
                text("SELECT set_config('app.user_id', :user_id, true)"),
                {"user_id": str(user_a)},
            )
            assert conn.execute(text("SELECT id FROM users")).scalars().all() == [user_a]
            conn.execute(
                text("SELECT set_config('app.user_id', :user_id, true)"),
                {"user_id": str(user_b)},
            )
            assert conn.execute(text("SELECT id FROM users")).scalars().all() == [user_b]

            conn.execute(
                text(
                    "SELECT set_config('app.oidc_issuer', :issuer, true), "
                    "set_config('app.oidc_subject', :subject, true)"
                ),
                {"issuer": issuer, "subject": subject_a},
            )
            assert conn.execute(
                text("SELECT user_id FROM external_identities")
            ).scalars().all() == [user_a]

            conn.execute(
                text("SELECT set_config('app.oidc_subject', :subject, true)"),
                {"subject": subject_b},
            )
            assert conn.execute(
                text("SELECT user_id FROM external_identities")
            ).scalars().all() == [user_b]

            conn.execute(
                text("SELECT set_config('app.oidc_subject', :subject, true)"),
                {"subject": f"unknown-{uuid4()}"},
            )
            assert conn.execute(
                text("SELECT id FROM external_identities")
            ).scalars().all() == []

            for table in ("users", "external_identities"):
                for privilege in ("INSERT", "UPDATE", "DELETE"):
                    allowed = conn.execute(
                        text("SELECT has_table_privilege(current_user, :table, :privilege)"),
                        {"table": table, "privilege": privilege},
                    ).scalar_one()
                    assert allowed is False, (table, privilege)

            assert conn.execute(
                text("SELECT has_table_privilege(current_user, 'alembic_version', 'SELECT')")
            ).scalar_one() is False

            with pytest.raises(DBAPIError):
                with conn.begin_nested():
                    conn.execute(text("SELECT version_num FROM alembic_version"))

            with pytest.raises(DBAPIError):
                with conn.begin_nested():
                    conn.execute(
                        text(
                            "INSERT INTO users (id, login, status) "
                            "VALUES (:id, :login, 'active')"
                        ),
                        {"id": uuid4(), "login": f"runtime-write-{uuid4()}@test.local"},
                    )

            with pytest.raises(DBAPIError):
                with conn.begin_nested():
                    conn.execute(text("UPDATE users SET status = 'disabled'"))

            with pytest.raises(DBAPIError):
                with conn.begin_nested():
                    conn.execute(text("DELETE FROM users"))

            with pytest.raises(DBAPIError):
                with conn.begin_nested():
                    conn.execute(
                        text(
                            "INSERT INTO external_identities "
                            "(id, issuer, subject, user_id, status) "
                            "VALUES (:id, :issuer, :subject, :user_id, 'active')"
                        ),
                        {
                            "id": uuid4(), "issuer": issuer,
                            "subject": f"runtime-write-{uuid4()}",
                            "user_id": user_a,
                        },
                    )

            with pytest.raises(DBAPIError):
                with conn.begin_nested():
                    conn.execute(text("UPDATE external_identities SET status = 'disabled'"))

            with pytest.raises(DBAPIError):
                with conn.begin_nested():
                    conn.execute(text("DELETE FROM external_identities"))
    finally:
        runtime_engine.dispose()
