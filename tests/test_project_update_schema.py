"""Regression tests for the partial project update contract."""

import pytest
from pydantic import ValidationError

from app.api.schemas import ProjectUpdate


def test_project_update_accepts_name_and_preserves_partial_fields():
    payload = ProjectUpdate(name="  Новый проект  ")

    assert payload.name == "Новый проект"
    assert payload.model_dump(exclude_unset=True) == {"name": "Новый проект"}


def test_project_update_keeps_existing_description_and_instructions_fields():
    payload = ProjectUpdate(description="Описание", instructions="Правила")

    assert payload.model_dump(exclude_unset=True) == {
        "description": "Описание",
        "instructions": "Правила",
    }


@pytest.mark.parametrize("name", ["", "   ", None])
def test_project_update_rejects_blank_or_null_name(name):
    with pytest.raises(ValidationError):
        ProjectUpdate(name=name)


def test_project_update_rejects_name_longer_than_300_characters():
    with pytest.raises(ValidationError):
        ProjectUpdate(name="x" * 301)


def test_project_update_allows_omitted_name():
    payload = ProjectUpdate(description="Новое описание")

    assert payload.name is None
    assert "name" not in payload.model_dump(exclude_unset=True)
