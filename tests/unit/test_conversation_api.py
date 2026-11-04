import pytest
from pydantic import ValidationError

from app.api.schemas import ChatMessageCreate, ConversationCreate
from app.main import app


def test_conversation_routes_are_registered():
    paths = set(app.openapi()['paths'])
    assert "/api/v1/tenants/{tenant_id}/projects/{project_id}/conversations" in paths
    assert (
        "/api/v1/tenants/{tenant_id}/projects/{project_id}/conversations/"
        "{conversation_id}/messages"
    ) in paths


def test_message_payload_rejects_empty_or_whitespace_content():
    with pytest.raises(ValidationError):
        ChatMessageCreate(content="")
    with pytest.raises(ValidationError):
        ChatMessageCreate(content="   ")
    assert ChatMessageCreate(content="  вопрос  ").content == "вопрос"


def test_conversation_title_is_trimmed_and_cannot_be_blank():
    with pytest.raises(ValidationError):
        ConversationCreate(title="   ")
    assert ConversationCreate(title="  Проверка  ").title == "Проверка"
