import pytest
from pydantic import ValidationError

from app.api.delegation import (
    BindingCreate,
    BionicDelegationIssueRequest,
    BionicDelegationRevokeRequest,
    BionicRetrievalRequest,
)


def test_bionic_retrieval_payload_rejects_model_controlled_context() -> None:
    with pytest.raises(ValidationError):
        BionicRetrievalRequest(
            grant_token="x" * 40,
            bionic_project_id=12,
            bionic_task_id=34,
            owner_subject="trusted-subject",
            query="foundation",
            tenant_id="00000000-0000-0000-0000-000000000001",
            project_id="00000000-0000-0000-0000-000000000002",
        )


def test_bionic_grant_issue_requires_server_verified_owner_subject() -> None:
    with pytest.raises(ValidationError):
        BionicDelegationIssueRequest(
            bionic_project_id=12,
            bionic_task_id=34,
        )


def test_binding_payload_cannot_override_bionic_instance() -> None:
    with pytest.raises(ValidationError):
        BindingCreate(
            bionic_project_id=12,
            tenant_id="00000000-0000-0000-0000-000000000001",
            project_id="00000000-0000-0000-0000-000000000002",
            bionic_instance="attacker-instance",
        )



def test_bionic_revoke_payload_rejects_project_substitution_fields() -> None:
    with pytest.raises(ValidationError):
        BionicDelegationRevokeRequest(
            grant_token="x" * 40,
            bionic_project_id=12,
            bionic_task_id=34,
            owner_subject="trusted-subject",
            tenant_id="00000000-0000-0000-0000-000000000001",
        )
