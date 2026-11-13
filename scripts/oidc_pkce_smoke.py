#!/usr/bin/env python3
"""Local-only OIDC Authorization Code + PKCE smoke test for the PEA pea-web client.

The access token and ID token remain in this process and are never printed or saved.
Before running, add the exact loopback redirect URI to pea-web in Keycloak:
  http://127.0.0.1:8765/callback
"""
from __future__ import annotations

import base64
import hashlib
import json
import secrets
import sys
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlencode, urlparse
from urllib.request import Request, urlopen

import jwt
from jwt import PyJWKClient

CLIENT_ID = "pea-web"
EXPECTED_API_AUDIENCE = "pea-api"
REDIRECT_URI = "http://127.0.0.1:8765/callback"
CALLBACK_HOST = "127.0.0.1"
CALLBACK_PORT = 8765
CALLBACK_PATH = "/callback"
CALLBACK_TIMEOUT_SECONDS = 300


def _local_http_url(value: str, label: str) -> None:
    parsed = urlparse(value)
    if (
        parsed.scheme != "http"
        or parsed.hostname not in {"localhost", "127.0.0.1"}
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError(f"{label} must be a local HTTP URL (localhost or 127.0.0.1).")


def _load_discovery(issuer: str) -> dict:
    _local_http_url(issuer, "OIDC_ISSUER")
    discovery_url = f"{issuer.rstrip('/')}/.well-known/openid-configuration"
    try:
        with urlopen(discovery_url, timeout=10) as response:
            metadata = json.loads(response.read())
    except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise RuntimeError("Could not load local Keycloak OIDC discovery metadata.") from exc

    if metadata.get("issuer") != issuer.rstrip("/"):
        raise RuntimeError("Discovery issuer does not exactly match OIDC_ISSUER.")

    for field in ("authorization_endpoint", "token_endpoint", "jwks_uri"):
        endpoint = metadata.get(field)
        if not isinstance(endpoint, str):
            raise RuntimeError(f"Discovery metadata is missing {field}.")
        _local_http_url(endpoint, field)
    return metadata


class _CallbackHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path != CALLBACK_PATH:
            self.send_error(404)
            return
        params = parse_qs(parsed.query, keep_blank_values=True)
        self.server.callback = {key: values[0] for key, values in params.items() if values}  # type: ignore[attr-defined]
        body = (
            b"OIDC callback received. You can close this tab and return to the terminal."
        )
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, _format: str, *args: object) -> None:
        # Never log callback query parameters: they contain the one-time code and state.
        return


def _receive_callback(state: str) -> str:
    server = HTTPServer((CALLBACK_HOST, CALLBACK_PORT), _CallbackHandler)
    server.timeout = 1
    server.callback = None  # type: ignore[attr-defined]
    deadline = time.monotonic() + CALLBACK_TIMEOUT_SECONDS
    try:
        while time.monotonic() < deadline and server.callback is None:  # type: ignore[attr-defined]
            server.handle_request()
    finally:
        server.server_close()

    callback = server.callback  # type: ignore[attr-defined]
    if not isinstance(callback, dict):
        raise RuntimeError("Timed out waiting for the local OIDC callback.")
    if callback.get("state") != state:
        raise RuntimeError("OIDC state validation failed.")
    if callback.get("error"):
        # Do not print error_description; it can contain sensitive server details.
        raise RuntimeError(f"Keycloak authorization failed: {callback['error']}.")
    code = callback.get("code")
    if not isinstance(code, str) or not code:
        raise RuntimeError("OIDC callback did not contain an authorization code.")
    return code


def _exchange_code(token_endpoint: str, code: str, verifier: str) -> dict:
    form = {
        "grant_type": "authorization_code",
        "client_id": CLIENT_ID,
        "code": code,
        "redirect_uri": REDIRECT_URI,
        "code_verifier": verifier,
    }
    request = Request(
        token_endpoint,
        data=urlencode(form).encode(),
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=15) as response:
            payload = json.loads(response.read())
    except HTTPError as exc:
        error_code = ""
        try:
            error_payload = json.loads(exc.read())
            candidate = error_payload.get("error") if isinstance(error_payload, dict) else ""
            if isinstance(candidate, str) and candidate.replace("_", "").replace("-", "").isalnum():
                error_code = candidate
        except (json.JSONDecodeError, UnicodeDecodeError):
            pass
        suffix = f" OAuth error: {error_code}." if error_code else ""
        raise RuntimeError(f"Token exchange failed (HTTP {exc.code}).{suffix}") from exc
    except (URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise RuntimeError("Token exchange failed due to a local connection or response error.") from exc

    if not isinstance(payload, dict) or not isinstance(payload.get("access_token"), str):
        raise RuntimeError("Token response did not contain an access token.")
    if not isinstance(payload.get("id_token"), str):
        raise RuntimeError("Token response did not contain an ID token.")
    return payload


def _validate_tokens(tokens: dict, metadata: dict, issuer: str, nonce: str) -> None:
    jwks = PyJWKClient(metadata["jwks_uri"], cache_jwk_set=True, lifespan=300, timeout=5)
    access_token = tokens["access_token"]
    signing_key = jwks.get_signing_key_from_jwt(access_token)
    access_claims = jwt.decode(
        access_token,
        signing_key.key,
        algorithms=["RS256"],
        issuer=issuer,
        audience=EXPECTED_API_AUDIENCE,
        options={"require": ["exp", "iat", "sub", "iss", "aud"]},
        leeway=30,
    )
    if not access_claims.get("sub"):
        raise RuntimeError("Access token has no subject.")

    id_token = tokens["id_token"]
    id_signing_key = jwks.get_signing_key_from_jwt(id_token)
    id_claims = jwt.decode(
        id_token,
        id_signing_key.key,
        algorithms=["RS256"],
        issuer=issuer,
        audience=CLIENT_ID,
        options={"require": ["exp", "iat", "sub", "iss", "aud", "nonce"]},
        leeway=30,
    )
    if id_claims.get("nonce") != nonce:
        raise RuntimeError("ID token nonce validation failed.")
    if id_claims.get("sub") != access_claims.get("sub"):
        raise RuntimeError("ID token and access token subjects do not match.")


def main() -> int:
    issuer = input(
        "OIDC issuer [http://localhost:30000/realms/stack-app]: "
    ).strip() or "http://localhost:30000/realms/stack-app"
    issuer = issuer.rstrip("/")
    try:
        metadata = _load_discovery(issuer)
        state = secrets.token_urlsafe(32)
        nonce = secrets.token_urlsafe(32)
        verifier = secrets.token_urlsafe(64)
        challenge = base64.urlsafe_b64encode(
            hashlib.sha256(verifier.encode()).digest()
        ).rstrip(b"=").decode()

        params = {
            "client_id": CLIENT_ID,
            "response_type": "code",
            "redirect_uri": REDIRECT_URI,
            "scope": "openid profile email",
            "state": state,
            "nonce": nonce,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        }
        authorization_url = f"{metadata['authorization_endpoint']}?{urlencode(params)}"

        # Bind the callback listener before opening the browser.
        server = HTTPServer((CALLBACK_HOST, CALLBACK_PORT), _CallbackHandler)
        server.timeout = 1
        server.callback = None  # type: ignore[attr-defined]
        deadline = time.monotonic() + CALLBACK_TIMEOUT_SECONDS
        print(f"Opening Keycloak login for {CLIENT_ID}.")
        print(f"Local callback: {REDIRECT_URI}")
        print("The browser will handle login; credentials and tokens are not printed.")
        if not webbrowser.open(authorization_url):
            print("Could not open a browser automatically. Open this URL manually:")
            print(authorization_url)

        try:
            while time.monotonic() < deadline and server.callback is None:  # type: ignore[attr-defined]
                server.handle_request()
        finally:
            server.server_close()

        callback = server.callback  # type: ignore[attr-defined]
        if not isinstance(callback, dict):
            raise RuntimeError("Timed out waiting for the local OIDC callback.")
        if callback.get("state") != state:
            raise RuntimeError("OIDC state validation failed.")
        if callback.get("error"):
            raise RuntimeError(f"Keycloak authorization failed: {callback['error']}.")
        code = callback.get("code")
        if not isinstance(code, str) or not code:
            raise RuntimeError("OIDC callback did not contain an authorization code.")

        tokens = _exchange_code(metadata["token_endpoint"], code, verifier)
        _validate_tokens(tokens, metadata, issuer, nonce)
        print("Authorization Code + PKCE S256: PASS")
        print("ID token signature, issuer, audience and nonce: PASS")
        print("Access token signature, issuer and audience pea-api: PASS")
        print("Subject present and consistent across tokens: PASS")
        print("Tokens were kept in memory only; nothing was written to disk.")
        return 0
    except (RuntimeError, ValueError, OSError, jwt.PyJWTError) as exc:
        print(f"OIDC smoke test failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
