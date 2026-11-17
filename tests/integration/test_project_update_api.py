"""PostgreSQL-backed authorization tests for project settings updates."""

import os
from uuid import uuid4

import pytest
from fastapi import Depends
from fastapi.testclient import TestClient

from app.api.auth import Principal, get_current_principal
from app.api.routes import get_session
from app.main import app
from app.storage.database import build_session_factory, set_tenant_context, set_user_context
from app.storage.models import Membership, Project, Tenant, User

OWNER_DATABASE_URL = os.getenv("DATABASE_URL")
APP_DATABASE_URL = os.getenv("APP_DATABASE_URL")

pytestmark = pytest.mark.skipif(
    not OWNER_DATABASE_URL or not APP_DATABASE_URL,
    reason="DATABASE_URL and restricted APP_DATABASE_URL are required",
)


def _seed_project(role: str):
    user_id, tenant_id, project_id = uuid4(), uuid4(), uuid4()
    owner_factory = build_session_factory(OWNER_DATABASE_URL)
    try:
        with owner_factory() as session, session.begin():
            session.add(User(id=user_id, login=f"project-update-{user_id}@test.local", status="active"))
            session.flush()
            set_tenant_context(session, tenant_id)
            session.add(Tenant(id=tenant_id, name="Project update integration", status="active"))
            session.flush()
            session.add(Membership(
                id=uuid4(), tenant_id=tenant_id, user_id=user_id, role=role, status="active"
            ))
            session.add(Project(
                id=project_id, tenant_id=tenant_id, workspace_id=None,
                name="Original project", description="Old description",
                instructions="Old instructions", status="active", project_metadata={},
            ))
        return user_id, tenant_id, project_id
    finally:
        owner_factory.kw["bind"].dispose()


def _client_for(user_id, tenant_id):
    runtime_factory = build_session_factory(APP_DATABASE_URL)

    def override_session():
        with runtime_factory() as session, session.begin():
            yield session

    def override_principal(session=Depends(get_session)):
        set_user_context(session, user_id)
        set_tenant_context(session, tenant_id)
        return Principal(user_id=user_id, tenant_id=tenant_id, membership_role="member")

    previous = app.dependency_overrides.copy()
    app.dependency_overrides[get_session] = override_session
    app.dependency_overrides[get_current_principal] = override_principal
    return TestClient(app), runtime_factory, previous


def _close(client, factory, previous):
    client.close()
    app.dependency_overrides.clear()
    app.dependency_overrides.update(previous)
    factory.kw["bind"].dispose()


def test_patch_project_settings_updates_name_description_and_instructions():
    user_id, tenant_id, project_id = _seed_project("owner")
    client, factory, previous = _client_for(user_id, tenant_id)
    try:
        response = client.patch(
            f"/api/v1/tenants/{tenant_id}/projects/{project_id}",
            json={"name": "  Updated project  ", "description": "New description",
                  "instructions": "New instructions"},
        )
        assert response.status_code == 200
        assert response.json()["name"] == "Updated project"
        assert response.json()["description"] == "New description"
        assert response.json()["instructions"] == "New instructions"
    finally:
        _close(client, factory, previous)


def test_patch_project_settings_denies_regular_tenant_member():
    user_id, tenant_id, project_id = _seed_project("member")
    client, factory, previous = _client_for(user_id, tenant_id)
    try:
        response = client.patch(
            f"/api/v1/tenants/{tenant_id}/projects/{project_id}",
            json={"name": "Unauthorized rename"},
        )
        assert response.status_code == 403
    finally:
        _close(client, factory, previous)


def test_patch_project_settings_returns_not_found_for_missing_project():
    user_id, tenant_id, _project_id = _seed_project("owner")
    client, factory, previous = _client_for(user_id, tenant_id)
    try:
        response = client.patch(
            f"/api/v1/tenants/{tenant_id}/projects/{uuid4()}",
            json={"name": "Does not exist"},
        )
        assert response.status_code == 404
    finally:
        _close(client, factory, previous)
