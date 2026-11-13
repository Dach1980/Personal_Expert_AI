from __future__ import annotations

import importlib.util
import io
import json
from pathlib import Path
from unittest.mock import patch

import pytest

MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "oidc_pkce_smoke.py"
SPEC = importlib.util.spec_from_file_location("oidc_pkce_smoke", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)


def test_local_http_url_accepts_loopback_hosts() -> None:
    module._local_http_url("http://localhost:30000/realms/stack-app", "issuer")
    module._local_http_url("http://127.0.0.1:8765/callback", "callback")


@pytest.mark.parametrize(
    "url",
    [
        "https://localhost:30000/realms/stack-app",
        "http://example.com/realms/stack-app",
        "http://localhost:30000/path?token=secret",
        "http://user:password@localhost:30000/realms/stack-app",
    ],
)
def test_local_http_url_rejects_non_local_or_unsafe_urls(url: str) -> None:
    with pytest.raises(ValueError):
        module._local_http_url(url, "issuer")


def test_discovery_requires_exact_issuer() -> None:
    metadata = {
        "issuer": "http://localhost:30000/realms/other",
        "authorization_endpoint": "http://localhost:30000/auth",
        "token_endpoint": "http://localhost:30000/token",
        "jwks_uri": "http://localhost:30000/certs",
    }
    response = io.BytesIO(json.dumps(metadata).encode())
    with patch.object(module, "urlopen", return_value=response):
        with pytest.raises(RuntimeError, match="issuer"):
            module._load_discovery("http://localhost:30000/realms/stack-app")


def test_discovery_rejects_remote_endpoints() -> None:
    issuer = "http://localhost:30000/realms/stack-app"
    metadata = {
        "issuer": issuer,
        "authorization_endpoint": "https://login.example.com/auth",
        "token_endpoint": "http://localhost:30000/token",
        "jwks_uri": "http://localhost:30000/certs",
    }
    response = io.BytesIO(json.dumps(metadata).encode())
    with patch.object(module, "urlopen", return_value=response):
        with pytest.raises(ValueError, match="local HTTP URL"):
            module._load_discovery(issuer)
