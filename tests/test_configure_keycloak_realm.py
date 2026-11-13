from __future__ import annotations

import copy
import importlib.util
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "configure_keycloak_realm.py"
SPEC = importlib.util.spec_from_file_location("configure_keycloak_realm", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)


def valid_api() -> dict:
    return {"clientId": "pea-api", **module.EXPECTED_API}


def valid_web() -> dict:
    return {
        "clientId": "pea-web",
        **module.EXPECTED_WEB,
        "redirectUris": ["https://example.test/callback"],
        "webOrigins": ["https://example.test"],
        "attributes": {"pkce.code.challenge.method": "S256"},
    }


def valid_scope() -> dict:
    return {
        "id": "scope-uuid",
        "name": "pea-api-context",
        "protocol": "openid-connect",
        "protocolMappers": [
            {"name": name, "protocol": "openid-connect", **copy.deepcopy(expected)}
            for name, expected in module.EXPECTED_MAPPERS.items()
        ],
    }


def test_dry_run_plan_only_lists_missing_resources() -> None:
    plan = module.build_plan(
        [], [], set(), ["https://example.test/callback"], ["https://example.test"]
    )
    assert plan["blockers"] == []
    assert plan["actions"] == [
        "create pea-api client",
        "create pea-api-context client scope",
        "create pea-web public PKCE client",
        "attach pea-api-context as a default scope to pea-web",
    ]


def test_existing_matching_resources_are_not_scheduled_for_update() -> None:
    plan = module.build_plan(
        [valid_api(), valid_web()],
        [valid_scope()],
        {"scope-uuid"},
        ["https://example.test/callback"],
        ["https://example.test"],
    )
    assert plan["blockers"] == []
    assert plan["actions"] == []


def test_incompatible_existing_client_blocks_preflight() -> None:
    api = valid_api()
    api["bearerOnly"] = False
    plan = module.build_plan(
        [api], [], set(), ["https://example.test/callback"], ["https://example.test"]
    )
    assert any("bearerOnly" in item for item in plan["blockers"])


def test_existing_web_allowlist_mismatch_is_a_blocker() -> None:
    web = valid_web()
    web["redirectUris"] = ["https://unexpected.test/*"]
    plan = module.build_plan(
        [web], [], set(), ["https://example.test/callback"], ["https://example.test"]
    )
    assert any("redirectUris" in item for item in plan["blockers"])


def test_existing_scope_with_extra_mapper_is_a_blocker() -> None:
    scope = valid_scope()
    scope["protocolMappers"].append({"name": "unexpected"})
    assert module.validate_scope(scope)


def test_existing_scope_with_wrong_tenant_mapper_is_a_blocker() -> None:
    scope = valid_scope()
    scope["protocolMappers"][1]["config"]["user.attribute"] = "email"
    assert any("user.attribute" in item for item in module.validate_scope(scope))


def test_duplicate_client_or_scope_names_block_preflight() -> None:
    plan = module.build_plan(
        [valid_api(), valid_api()],
        [valid_scope(), valid_scope()],
        set(),
        ["https://example.test/callback"],
        ["https://example.test"],
    )
    assert any("Multiple clients named pea-api" in item for item in plan["blockers"])
    assert any("Multiple client scopes named" in item for item in plan["blockers"])


def test_base_url_rejects_legacy_path_prefix() -> None:
    try:
        module.validate_base_url("http://localhost:30000/oidc")
    except module.ProvisioningError:
        pass
    else:
        raise AssertionError("A Keycloak base URL with a path prefix must be rejected.")


def test_base_url_accepts_local_keycloak_origin() -> None:
    assert module.validate_base_url("http://localhost:30000/") == "http://localhost:30000"


def test_web_allowlists_reject_wildcards() -> None:
    try:
        module.validate_web_allowlists(["https://example.test/*"], ["https://example.test"])
    except module.ProvisioningError:
        pass
    else:
        raise AssertionError("Wildcard redirect URIs must be rejected.")


def test_web_origins_must_not_contain_paths() -> None:
    try:
        module.validate_web_allowlists(
            ["https://example.test/callback"], ["https://example.test/app"]
        )
    except module.ProvisioningError:
        pass
    else:
        raise AssertionError("Web origins with paths must be rejected.")
