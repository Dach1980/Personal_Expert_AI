import pytest
from pydantic import ValidationError

from app.api.schemas import SearchRequest
from app.main import app


def test_project_search_route_is_registered():
    path = "/api/v1/tenants/{tenant_id}/projects/{project_id}/search"
    assert path in app.openapi()["paths"]
    assert "post" in app.openapi()["paths"][path]


def test_search_request_normalizes_query_and_bounds_top_k():
    request = SearchRequest(query="  отметка пола  ", top_k=20)
    assert request.query == "отметка пола"
    assert request.top_k == 20
    assert request.filters.version_state == "current"


def test_search_request_rejects_blank_or_too_short_query():
    with pytest.raises(ValidationError):
        SearchRequest(query="  ")
    with pytest.raises(ValidationError):
        SearchRequest(query="x")


def test_search_request_rejects_unbounded_top_k_and_unknown_version_state():
    with pytest.raises(ValidationError):
        SearchRequest(query="план", top_k=500)
    with pytest.raises(ValidationError):
        SearchRequest(query="план", filters={"version_state": "any"})
