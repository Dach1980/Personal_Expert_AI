#!/usr/bin/env python3
"""Safely provision the PEA clients in an existing Keycloak realm.

Default behavior is read-only. Pass --apply to create missing resources.
Existing resources are validated and are never updated by this script.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urlparse
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
EXPECTED_API = {
    "protocol": "openid-connect",
    "enabled": True,
    "bearerOnly": True,
    "publicClient": False,
    "standardFlowEnabled": False,
    "implicitFlowEnabled": False,
    "directAccessGrantsEnabled": False,
    "serviceAccountsEnabled": False,
}
EXPECTED_WEB = {
    "protocol": "openid-connect",
    "enabled": True,
    "publicClient": True,
    "standardFlowEnabled": True,
    "implicitFlowEnabled": False,
    "directAccessGrantsEnabled": False,
    "serviceAccountsEnabled": False,
}
EXPECTED_MAPPERS = {
    "pea-api-audience": {
        "protocolMapper": "oidc-audience-mapper",
        "config": {
            "included.client.audience": "pea-api",
            "id.token.claim": "false",
            "access.token.claim": "true",
            "userinfo.token.claim": "false",
        },
    },
    "pea-tenant-id": {
        "protocolMapper": "oidc-usermodel-attribute-mapper",
        "config": {
            "user.attribute": "tenant_id",
            "claim.name": "tenant_id",
            "jsonType.label": "String",
            "id.token.claim": "false",
            "access.token.claim": "true",
            "userinfo.token.claim": "false",
            "multivalued": "false",
        },
    },
}


class ProvisioningError(RuntimeError):
    """A safe, user-displayable provisioning error."""


def parse_csv(value: str) -> list[str]:
    return list(dict.fromkeys(part.strip() for part in value.split(",") if part.strip()))


def validate_base_url(value: str) -> str:
    value = value.rstrip("/")
    parsed = urlparse(value)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.netloc
        or parsed.username
        or parsed.password
    ):
        raise ProvisioningError("KEYCLOAK_BASE_URL must be an absolute HTTP(S) origin without credentials.")
    if parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
        raise ProvisioningError(
            "KEYCLOAK_BASE_URL must be the Keycloak origin without a path, query or fragment."
        )
    return value


def validate_web_allowlists(redirect_uris: list[str], web_origins: list[str]) -> None:
    if not redirect_uris or not web_origins:
        raise ProvisioningError("PEA Web redirect URI and origin allowlists must both be non-empty.")

    for uri in redirect_uris:
        parsed = urlparse(uri)
        if (
            "*" in uri
            or parsed.scheme not in {"http", "https"}
            or not parsed.netloc
            or parsed.query
            or parsed.fragment
            or (parsed.scheme == "http" and parsed.hostname not in {"localhost", "127.0.0.1", "::1"})
        ):
            raise ProvisioningError(
                "Every PEA_WEB_REDIRECT_URIS entry must be an exact HTTPS URL "
                "(HTTP is allowed only for loopback development)."
            )

    for origin in web_origins:
        parsed = urlparse(origin)
        if (
            "*" in origin
            or parsed.scheme not in {"http", "https"}
            or not parsed.netloc
            or parsed.path not in {"", "/"}
            or parsed.query
            or parsed.fragment
            or (parsed.scheme == "http" and parsed.hostname not in {"localhost", "127.0.0.1", "::1"})
        ):
            raise ProvisioningError(
                "Every PEA_WEB_ORIGINS entry must be an exact origin without a path "
                "(HTTP is allowed only for loopback development)."
            )


def validate_scope(scope: dict) -> list[str]:
    blockers: list[str] = []
    if scope.get("name") != "pea-api-context":
        blockers.append("Existing pea-api-context scope has an unexpected name.")
    if scope.get("protocol") != "openid-connect":
        blockers.append("Existing pea-api-context scope uses an unexpected protocol.")
    mappers = scope.get("protocolMappers")
    if not isinstance(mappers, list):
        return blockers + ["Existing pea-api-context scope has no valid protocolMappers list."]
    by_name = {item.get("name"): item for item in mappers if isinstance(item, dict)}
    if len(by_name) != len(mappers) or set(by_name) != set(EXPECTED_MAPPERS):
        blockers.append(
            "Existing pea-api-context scope has unexpected or duplicate protocol mappers."
        )
        return blockers
    for name, expected in EXPECTED_MAPPERS.items():
        actual = by_name[name]
        if actual.get("protocol") != "openid-connect":
            blockers.append(f"Existing mapper {name} has an unexpected protocol.")
        if actual.get("protocolMapper") != expected["protocolMapper"]:
            blockers.append(f"Existing mapper {name} has an unexpected mapper type.")
        config = actual.get("config") or {}
        for key, value in expected["config"].items():
            if config.get(key) != value:
                blockers.append(f"Existing mapper {name} has an incompatible {key} setting.")
    return blockers


def validate_existing_client(
    client: dict, expected: dict[str, object], label: str
) -> list[str]:
    blockers: list[str] = []
    for key, value in expected.items():
        if client.get(key) != value:
            blockers.append(
                f"Existing {label} client has incompatible {key}; it will not be changed."
            )
    return blockers


def build_plan(
    clients: list[dict],
    scopes: list[dict],
    web_default_scope_ids: set[str],
    redirect_uris: list[str],
    web_origins: list[str],
) -> dict:
    """Build a mutation plan without performing network or filesystem writes."""
    blockers: list[str] = []
    if not redirect_uris or not web_origins:
        blockers.append("PEA Web redirect URI and origin allowlists must both be non-empty.")

    def unique_client(client_id: str) -> dict | None:
        matches = [item for item in clients if item.get("clientId") == client_id]
        if len(matches) > 1:
            blockers.append(
                f"Multiple clients named {client_id} exist; manual review is required."
            )
            return None
        return matches[0] if matches else None

    api = unique_client("pea-api")
    web = unique_client("pea-web")
    scope_matches = [item for item in scopes if item.get("name") == "pea-api-context"]
    scope = None
    if len(scope_matches) > 1:
        blockers.append(
            "Multiple client scopes named pea-api-context exist; manual review is required."
        )
    elif scope_matches:
        scope = scope_matches[0]
        if not scope.get("id"):
            blockers.append(
                "Existing pea-api-context scope has no internal ID; manual review is required."
            )

    if api is not None:
        blockers.extend(validate_existing_client(api, EXPECTED_API, "pea-api"))
    if web is not None:
        blockers.extend(validate_existing_client(web, EXPECTED_WEB, "pea-web"))
        if set(web.get("redirectUris") or []) != set(redirect_uris):
            blockers.append("Existing pea-web redirectUris differ from the requested allowlist.")
        if set(web.get("webOrigins") or []) != set(web_origins):
            blockers.append("Existing pea-web webOrigins differ from the requested allowlist.")
        attributes = web.get("attributes") or {}
        if attributes.get("pkce.code.challenge.method") != "S256":
            blockers.append("Existing pea-web client does not enforce PKCE S256.")
    if scope is not None:
        blockers.extend(validate_scope(scope))

    actions: list[str] = []
    if api is None:
        actions.append("create pea-api client")
    if scope is None:
        actions.append("create pea-api-context client scope")
    if web is None:
        actions.append("create pea-web public PKCE client")
    if scope is None or web is None or (
        scope is not None and scope.get("id") not in web_default_scope_ids
    ):
        actions.append("attach pea-api-context as a default scope to pea-web")

    return {"blockers": blockers, "actions": actions}


class KeycloakAdmin:
    def __init__(self, base_url: str, username: str, password: str) -> None:
        self.base_url = base_url
        self.username = username
        self.password = password
        self.token = ""

    def login(self) -> None:
        form = urlencode({
            "grant_type": "password",
            "client_id": "admin-cli",
            "username": self.username,
            "password": self.password,
        }).encode("utf-8")
        request = Request(
            f"{self.base_url}/realms/master/protocol/openid-connect/token",
            data=form,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            method="POST",
        )
        try:
            with urlopen(request, timeout=15) as response:
                payload = json.loads(response.read())
        except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise ProvisioningError(
                "Keycloak admin authentication failed. Check the supplied credentials and "
                "whether the admin-cli password grant is enabled. No realm changes were made."
            ) from exc
        token = payload.get("access_token")
        if not isinstance(token, str) or not token:
            raise ProvisioningError("Keycloak did not return an admin access token.")
        self.token = token

    def request(self, method: str, path: str, payload: object | None = None):
        data = None if payload is None else json.dumps(payload).encode("utf-8")
        headers = {"Accept": "application/json", "Authorization": f"Bearer {self.token}"}
        if data is not None:
            headers["Content-Type"] = "application/json"
        request = Request(
            f"{self.base_url}{path}", data=data, headers=headers, method=method
        )
        try:
            with urlopen(request, timeout=15) as response:
                raw = response.read()
                body = json.loads(raw) if raw else None
                return response.status, response.headers, body
        except HTTPError as exc:
            return exc.code, exc.headers, None
        except (URLError, TimeoutError) as exc:
            raise ProvisioningError(
                f"Keycloak {method} request failed for {path}."
            ) from exc


def require_status(status: int, expected: set[int], action: str) -> None:
    if status not in expected:
        raise ProvisioningError(
            f"{action} failed with HTTP {status}; no response body was logged."
        )


def get_json(url: str) -> dict:
    request = Request(url, headers={"Accept": "application/json"})
    try:
        with urlopen(request, timeout=15) as response:
            payload = json.loads(response.read())
    except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise ProvisioningError("OIDC discovery could not be retrieved.") from exc
    if not isinstance(payload, dict):
        raise ProvisioningError("OIDC discovery returned an invalid document.")
    return payload


def load_templates(
    redirect_uris: list[str], web_origins: list[str]
) -> tuple[dict, dict, dict]:
    api = json.loads((ROOT / "infra/keycloak/pea-api-client.json").read_text(encoding="utf-8"))
    scope = json.loads(
        (ROOT / "infra/keycloak/pea-api-context-client-scope.json").read_text(encoding="utf-8")
    )
    web = json.loads((ROOT / "infra/keycloak/pea-web-client.json").read_text(encoding="utf-8"))
    web["redirectUris"] = redirect_uris
    web["webOrigins"] = web_origins
    return api, scope, web


def preflight(
    base_url: str,
    realm: str,
    admin: KeycloakAdmin,
    redirect_uris: list[str],
    web_origins: list[str],
) -> tuple[dict, dict, dict]:
    discovery_url = (
        f"{base_url}/realms/{quote(realm, safe='')}/.well-known/openid-configuration"
    )
    discovery = get_json(discovery_url)
    expected_issuer = f"{base_url}/realms/{realm}"
    if discovery.get("issuer") != expected_issuer:
        raise ProvisioningError(
            "OIDC discovery issuer does not exactly match the configured base URL and realm."
        )
    if not isinstance(discovery.get("jwks_uri"), str) or not discovery["jwks_uri"]:
        raise ProvisioningError("OIDC discovery does not contain a valid jwks_uri.")

    admin.login()
    realm_path = f"/admin/realms/{quote(realm, safe='')}"
    status, _, clients = admin.request("GET", f"{realm_path}/clients")
    require_status(status, {200}, "List realm clients")
    status, _, scopes = admin.request("GET", f"{realm_path}/client-scopes")
    require_status(status, {200}, "List realm client scopes")
    if not isinstance(clients, list) or not isinstance(scopes, list):
        raise ProvisioningError("Keycloak returned an invalid clients/scopes collection.")

    web_matches = [item for item in clients if item.get("clientId") == "pea-web"]
    web_default_scope_ids: set[str] = set()
    if len(web_matches) == 1:
        web_uuid = web_matches[0].get("id")
        if not web_uuid:
            raise ProvisioningError("Existing pea-web client has no internal ID.")
        status, _, default_scopes = admin.request(
            "GET", f"{realm_path}/clients/{quote(web_uuid, safe='')}/default-client-scopes"
        )
        require_status(status, {200}, "List pea-web default client scopes")
        if not isinstance(default_scopes, list):
            raise ProvisioningError("Keycloak returned an invalid pea-web default scopes list.")
        web_default_scope_ids = {
            item.get("id") for item in default_scopes if isinstance(item, dict) and item.get("id")
        }

    plan = build_plan(clients, scopes, web_default_scope_ids, redirect_uris, web_origins)
    return discovery, plan, {
        "realm_path": realm_path,
        "clients": clients,
        "scopes": scopes,
    }


def apply_plan(
    admin: KeycloakAdmin,
    realm_path: str,
    plan: dict,
    state: dict,
    templates: tuple[dict, dict, dict],
) -> None:
    if plan["blockers"]:
        raise ProvisioningError("Apply refused because preflight reported blockers.")
    api_template, scope_template, web_template = templates
    clients = state["clients"]
    scopes = state["scopes"]

    def has_client(client_id: str) -> bool:
        return any(item.get("clientId") == client_id for item in clients)

    if not has_client("pea-api"):
        status, _, _ = admin.request("POST", f"{realm_path}/clients", api_template)
        require_status(status, {201}, "Create pea-api client")
    if not any(item.get("name") == "pea-api-context" for item in scopes):
        status, _, _ = admin.request("POST", f"{realm_path}/client-scopes", scope_template)
        require_status(status, {201}, "Create pea-api-context scope")
    if not has_client("pea-web"):
        status, _, _ = admin.request("POST", f"{realm_path}/clients", web_template)
        require_status(status, {201}, "Create pea-web client")

    status, _, clients = admin.request("GET", f"{realm_path}/clients")
    require_status(status, {200}, "Resolve created PEA clients")
    status, _, scopes = admin.request("GET", f"{realm_path}/client-scopes")
    require_status(status, {200}, "Resolve created PEA scope")
    web_matches = [item for item in clients if item.get("clientId") == "pea-web"]
    scope_matches = [item for item in scopes if item.get("name") == "pea-api-context"]
    if len(web_matches) != 1 or len(scope_matches) != 1:
        raise ProvisioningError("Created PEA resources could not be resolved unambiguously.")
    web_uuid = web_matches[0].get("id")
    scope_uuid = scope_matches[0].get("id")
    if not web_uuid or not scope_uuid:
        raise ProvisioningError("Created PEA resources are missing internal IDs.")

    status, _, default_scopes = admin.request(
        "GET", f"{realm_path}/clients/{quote(web_uuid, safe='')}/default-client-scopes"
    )
    require_status(status, {200}, "Recheck pea-web default scopes")
    if not any(item.get("id") == scope_uuid for item in default_scopes or []):
        status, _, _ = admin.request(
            "PUT",
            f"{realm_path}/clients/{quote(web_uuid, safe='')}/default-client-scopes/"
            f"{quote(scope_uuid, safe='')}",
        )
        require_status(status, {204}, "Attach pea-api-context to pea-web")
    print(
        "Apply completed. Only missing PEA resources were created; existing resources were not updated."
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Create missing PEA resources after a complete successful preflight.",
    )
    args = parser.parse_args(argv)
    try:
        base_url = validate_base_url(
            os.getenv("KEYCLOAK_BASE_URL", "http://localhost:30000")
        )
        realm = os.getenv("KEYCLOAK_REALM", "stack-app").strip()
        if not realm:
            raise ProvisioningError("KEYCLOAK_REALM must not be empty.")
        username = os.getenv("KEYCLOAK_ADMIN_USERNAME", "")
        password = os.getenv("KEYCLOAK_ADMIN_PASSWORD", "")
        if not username or not password:
            raise ProvisioningError(
                "Set KEYCLOAK_ADMIN_USERNAME and KEYCLOAK_ADMIN_PASSWORD in the environment. "
                "Credentials are never read from files or printed."
            )
        redirects = parse_csv(os.getenv(
            "PEA_WEB_REDIRECT_URIS",
            "https://dach1980.github.io/Personal_Expert_AI_Web/",
        ))
        origins = parse_csv(os.getenv(
            "PEA_WEB_ORIGINS", "https://dach1980.github.io"
        ))
        validate_web_allowlists(redirects, origins)
        templates = load_templates(redirects, origins)
        admin = KeycloakAdmin(base_url, username, password)
        discovery, plan, state = preflight(base_url, realm, admin, redirects, origins)
        print(f"Realm: {realm}")
        print(f"Issuer: {discovery['issuer']}")
        print(f"JWKS: {discovery['jwks_uri']}")
        if plan["blockers"]:
            for blocker in plan["blockers"]:
                print(f"BLOCKER: {blocker}", file=sys.stderr)
            print("Preflight failed; no realm changes were made.", file=sys.stderr)
            return 2
        if plan["actions"]:
            print("Planned changes:")
            for action in plan["actions"]:
                print(f"- {action}")
        else:
            print("No changes required; all PEA resources already match the expected configuration.")
        if not args.apply:
            print("Dry-run only. No Keycloak changes were made. Pass --apply to create missing resources.")
            return 0
        apply_plan(admin, state["realm_path"], plan, state, templates)
        return 0
    except (ProvisioningError, OSError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
