#!/usr/bin/env python3
"""Idempotently configure the shared Stack-managed Keycloak realm for PEA.

Required environment:
  KEYCLOAK_BASE_URL       e.g. http://localhost:30000/oidc
  KEYCLOAK_ADMIN_USERNAME
  KEYCLOAK_ADMIN_PASSWORD

Optional:
  KEYCLOAK_REALM          defaults to bionic-gpt
  BIONIC_OIDC_CLIENT_ID   defaults to oauth2-proxy

The script creates/updates the pea-api audience client and pea-api-context
client scope, then attaches that scope as a default scope to Bionic's OIDC
client. It never creates users, tenant memberships or credentials in PEA.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, quote
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[2]


class KeycloakAdmin:
    def __init__(self, base_url: str, username: str, password: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.username = username
        self.password = password
        self.token = ""

    def request(self, method: str, path: str, payload: object | None = None):
        data = None if payload is None else json.dumps(payload).encode("utf-8")
        headers = {"Accept": "application/json"}
        if data is not None:
            headers["Content-Type"] = "application/json"
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        req = Request(f"{self.base_url}{path}", data=data, headers=headers, method=method)
        try:
            with urlopen(req, timeout=10) as response:
                raw = response.read()
                return response.status, response.headers, json.loads(raw) if raw else None
        except HTTPError as exc:
            raw = exc.read()
            try:
                body = json.loads(raw) if raw else None
            except json.JSONDecodeError:
                body = raw.decode("utf-8", errors="replace")
            return exc.code, exc.headers, body
        except URLError as exc:
            raise RuntimeError(f"Keycloak request failed: {exc.reason}") from exc

    def login(self) -> None:
        form = urlencode({
            "grant_type": "password",
            "client_id": "admin-cli",
            "username": self.username,
            "password": self.password,
        }).encode("utf-8")
        req = Request(
            f"{self.base_url}/realms/master/protocol/openid-connect/token",
            data=form,
            headers={"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"},
            method="POST",
        )
        try:
            with urlopen(req, timeout=10) as response:
                payload = json.loads(response.read())
        except (HTTPError, URLError) as exc:
            raise RuntimeError(
                "Could not authenticate to Keycloak master realm. Check admin credentials "
                "and whether the admin-cli password grant is enabled for local administration."
            ) from exc
        self.token = payload["access_token"]


def require_success(status: int, expected: set[int], action: str, body: object) -> None:
    if status not in expected:
        raise RuntimeError(f"{action} failed (HTTP {status}): {body}")


def main() -> int:
    base_url = os.getenv("KEYCLOAK_BASE_URL", "http://localhost:30000/oidc").rstrip("/")
    realm = os.getenv("KEYCLOAK_REALM", "bionic-gpt")
    bionic_client_id = os.getenv("BIONIC_OIDC_CLIENT_ID", "oauth2-proxy")
    username = os.getenv("KEYCLOAK_ADMIN_USERNAME", "")
    password = os.getenv("KEYCLOAK_ADMIN_PASSWORD", "")
    if not username or not password:
        print("Set KEYCLOAK_ADMIN_USERNAME and KEYCLOAK_ADMIN_PASSWORD; no secrets are read from files.", file=sys.stderr)
        return 2

    admin = KeycloakAdmin(base_url, username, password)
    admin.login()
    realm_path = f"/admin/realms/{quote(realm, safe='')}"

    audience_client = json.loads((ROOT / "infra/keycloak/pea-api-client.json").read_text(encoding="utf-8"))
    status, _, clients = admin.request("GET", f"{realm_path}/clients?clientId=pea-api")
    require_success(status, {200}, "Find pea-api client", clients)
    if clients:
        client_uuid = clients[0]["id"]
        status, _, body = admin.request("PUT", f"{realm_path}/clients/{client_uuid}", audience_client)
        require_success(status, {204}, "Update pea-api client", body)
        print("Updated pea-api audience client.")
    else:
        status, _, body = admin.request("POST", f"{realm_path}/clients", audience_client)
        require_success(status, {201}, "Create pea-api client", body)
        print("Created pea-api audience client.")

    scope_representation = json.loads(
        (ROOT / "infra/keycloak/pea-api-context-client-scope.json").read_text(encoding="utf-8")
    )
    status, _, scopes = admin.request("GET", f"{realm_path}/client-scopes")
    require_success(status, {200}, "List client scopes", scopes)
    matches = [scope for scope in scopes if scope["name"] == "pea-api-context"]
    if matches:
        scope_uuid = matches[0]["id"]
        scope_representation["id"] = scope_uuid
        status, _, body = admin.request(
            "PUT", f"{realm_path}/client-scopes/{scope_uuid}", scope_representation
        )
        require_success(status, {204}, "Update pea-api-context scope", body)
        print("Updated pea-api-context client scope.")
    else:
        status, headers, body = admin.request(
            "POST", f"{realm_path}/client-scopes", scope_representation
        )
        require_success(status, {201}, "Create pea-api-context scope", body)
        location = headers.get("Location", "")
        scope_uuid = location.rstrip("/").split("/")[-1]
        if not scope_uuid:
            status, _, scopes = admin.request("GET", f"{realm_path}/client-scopes")
            require_success(status, {200}, "Resolve created client scope", scopes)
            matches = [scope for scope in scopes if scope["name"] == "pea-api-context"]
            if not matches:
                raise RuntimeError("Created client scope could not be resolved.")
            scope_uuid = matches[0]["id"]
        print("Created pea-api-context client scope.")

    status, _, bionic_clients = admin.request(
        "GET", f"{realm_path}/clients?clientId={quote(bionic_client_id, safe='')}"
    )
    require_success(status, {200}, f"Find Bionic OIDC client '{bionic_client_id}'", bionic_clients)
    if not bionic_clients:
        raise RuntimeError(
            f"Bionic OIDC client '{bionic_client_id}' was not found in realm '{realm}'. "
            "Check BIONIC_OIDC_CLIENT_ID against the Stack-managed OIDC client."
        )
    bionic_uuid = bionic_clients[0]["id"]

    status, _, default_scopes = admin.request(
        "GET", f"{realm_path}/clients/{bionic_uuid}/default-client-scopes"
    )
    require_success(status, {200}, "List Bionic default client scopes", default_scopes)
    if any(scope["id"] == scope_uuid for scope in default_scopes):
        print("pea-api-context is already a default scope for Bionic.")
    else:
        status, _, body = admin.request(
            "PUT",
            f"{realm_path}/clients/{bionic_uuid}/default-client-scopes/{scope_uuid}",
        )
        require_success(status, {204}, "Attach PEA context scope to Bionic", body)
        print("Attached pea-api-context as a default Bionic client scope.")

    discovery_url = f"{base_url}/realms/{quote(realm, safe='')}/.well-known/openid-configuration"
    try:
        with urlopen(discovery_url, timeout=10) as response:
            discovery = json.loads(response.read())
    except (HTTPError, URLError) as exc:
        raise RuntimeError("Realm configured, but OIDC discovery could not be read.") from exc
    print(f"OIDC_ISSUER={discovery['issuer']}")
    print(f"OIDC_JWKS_URL={discovery['jwks_uri']}")
    print("Next: set the tenant_id user attribute for each explicitly provisioned user.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except RuntimeError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
