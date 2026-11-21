"""Read-only OAuth/MCP capability probe for Finam AI Screener.

Never prints credentials, access tokens, response bodies, or account data.
It only attempts OAuth client_credentials when the server's published metadata
explicitly advertises that grant. Authorization-code-only servers require a
human Authenticate step and cannot be silently automated by GitHub Actions.
"""
from __future__ import annotations

import base64
import json
import os
import re
import sys
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen

MCP_URL = "https://ai.finam.ru/mcp"
TIMEOUT = 15


class ProbeError(RuntimeError):
    pass


def request(url: str, *, method: str = "GET", headers=None, data=None):
    req = Request(url, data=data, headers=headers or {}, method=method)
    try:
        with urlopen(req, timeout=TIMEOUT) as response:
            return response.status, dict(response.headers.items()), response.read(65536)
    except HTTPError as exc:
        return exc.code, dict(exc.headers.items()), exc.read(65536)
    except (URLError, TimeoutError) as exc:
        raise ProbeError(f"NETWORK_ERROR:{type(exc).__name__}") from None


def json_body(body: bytes):
    try:
        return json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return {}


def header(headers, name):
    for key, value in headers.items():
        if key.lower() == name.lower():
            return value
    return ""


def metadata_url_from_challenge(challenge: str):
    match = re.search(r'resource_metadata\s*=\s*"([^"]+)"', challenge, re.I)
    if match:
        return match.group(1)
    match = re.search(r'resource_metadata\s*=\s*([^,\s]+)', challenge, re.I)
    return match.group(1).strip('"') if match else None


def oauth_metadata_url(issuer: str):
    parsed = urlparse(issuer)
    if parsed.scheme != "https" or not parsed.netloc:
        raise ProbeError("UNSAFE_OAUTH_ISSUER_URL")
    prefix = parsed.path.rstrip("/")
    return f"{parsed.scheme}://{parsed.netloc}/.well-known/oauth-authorization-server{prefix}"


def initialize(access_token: str | None = None):
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
        "MCP-Protocol-Version": "2025-03-26",
        "User-Agent": "moex-edge-finam-ai-screener-probe/1.0",
    }
    if access_token:
        headers["Authorization"] = f"Bearer {access_token}"
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2025-03-26",
            "capabilities": {},
            "clientInfo": {"name": "moex-edge-readonly-probe", "version": "1.0"},
        },
    }
    return request(
        MCP_URL,
        method="POST",
        headers=headers,
        data=json.dumps(payload).encode("utf-8"),
    )


def acquire_client_credentials(token_url: str, client_id: str, client_secret: str,
                               auth_methods: list[str]):
    fields = {"grant_type": "client_credentials"}
    headers = {"Content-Type": "application/x-www-form-urlencoded",
               "Accept": "application/json"}
    if "client_secret_post" in auth_methods:
        fields.update({"client_id": client_id, "client_secret": client_secret})
    else:
        raw = f"{client_id}:{client_secret}".encode("utf-8")
        headers["Authorization"] = "Basic " + base64.b64encode(raw).decode("ascii")
    status, _, body = request(
        token_url, method="POST", headers=headers,
        data=urlencode(fields).encode("ascii"),
    )
    data = json_body(body)
    if status < 200 or status >= 300 or not data.get("access_token"):
        return None, status
    return str(data["access_token"]), status


def main():
    client_id = os.environ.get("FINAM_MCP_ID", "").strip()
    client_secret = os.environ.get("FINAM_MCP_TOKEN", "").strip()
    if not client_id or not client_secret:
        print("RESULT=SECRETS_MISSING")
        print("Required GitHub Actions secrets: FINAM_MCP_ID and FINAM_MCP_TOKEN.")
        return 2

    print("RESULT=SECRETS_PRESENT")
    status, headers, _ = initialize()
    print(f"MCP_UNAUTHENTICATED_HTTP_STATUS={status}")

    if 200 <= status < 300:
        print("RESULT=MCP_ENDPOINT_ACCEPTED_INITIALIZE_WITHOUT_AUTH")
        return 0

    challenge = header(headers, "WWW-Authenticate")
    if status != 401 or not challenge:
        print("RESULT=AUTH_CHALLENGE_NOT_DISCOVERED")
        print("The endpoint did not return a standard 401 OAuth challenge.")
        return 3

    resource_meta_url = metadata_url_from_challenge(challenge)
    if not resource_meta_url:
        print("RESULT=OAUTH_RESOURCE_METADATA_NOT_ADVERTISED")
        return 4

    meta_status, _, meta_body = request(resource_meta_url)
    resource_meta = json_body(meta_body)
    if not 200 <= meta_status < 300:
        print(f"RESOURCE_METADATA_HTTP_STATUS={meta_status}")
        print("RESULT=OAUTH_METADATA_UNAVAILABLE")
        return 5

    issuers = resource_meta.get("authorization_servers") or []
    if not issuers:
        print("RESULT=OAUTH_AUTHORIZATION_SERVER_NOT_ADVERTISED")
        return 6

    issuer = str(issuers[0])
    discovery_url = oauth_metadata_url(issuer)
    oauth_status, _, oauth_body = request(discovery_url)
    oauth_meta = json_body(oauth_body)
    if not 200 <= oauth_status < 300:
        print(f"OAUTH_METADATA_HTTP_STATUS={oauth_status}")
        print("RESULT=OAUTH_METADATA_UNAVAILABLE")
        return 7

    grants = oauth_meta.get("grant_types_supported") or []
    methods = oauth_meta.get("token_endpoint_auth_methods_supported") or []
    scopes = oauth_meta.get("scopes_supported") or []
    device_endpoint = oauth_meta.get("device_authorization_endpoint")
    device_grant = "urn:ietf:params:oauth:grant-type:device_code" in grants
    refresh_grant = "refresh_token" in grants
    print("OAUTH_GRANT_CLIENT_CREDENTIALS_SUPPORTED=" +
          ("yes" if "client_credentials" in grants else "no"))
    print("OAUTH_DEVICE_CODE_SUPPORTED=" +
          ("yes" if device_endpoint or device_grant else "no"))
    print("OAUTH_REFRESH_TOKEN_GRANT_SUPPORTED=" +
          ("yes" if refresh_grant else "no"))
    print("OAUTH_OFFLINE_ACCESS_SCOPE_SUPPORTED=" +
          ("yes" if "offline_access" in scopes else "no"))
    if "client_credentials" not in grants:
        if device_endpoint or device_grant:
            print("RESULT=DEVICE_AUTH_FLOW_POTENTIALLY_AVAILABLE")
            print("Finam advertises a device authorization endpoint/grant; a user-mediated one-time flow may be testable.")
        else:
            print("RESULT=INTERACTIVE_AUTH_REQUIRED")
            print("Published OAuth metadata does not advertise client_credentials or device-code authorization.")
            print("A human Authenticate/browser flow is required; GitHub Actions cannot complete it headlessly.")
        return 0

    token_url = oauth_meta.get("token_endpoint")
    if not token_url:
        print("RESULT=OAUTH_TOKEN_ENDPOINT_MISSING")
        return 8

    token, token_status = acquire_client_credentials(
        str(token_url), client_id, client_secret, methods
    )
    print(f"OAUTH_TOKEN_HTTP_STATUS={token_status}")
    if not token:
        print("RESULT=CLIENT_CREDENTIALS_GRANT_REJECTED")
        print("The published grant exists, but Finam did not issue a token for this client.")
        return 9

    init_status, init_headers, _ = initialize(token)
    print(f"MCP_AUTHENTICATED_INITIALIZE_HTTP_STATUS={init_status}")
    if 200 <= init_status < 300:
        print("RESULT=MCP_AUTHENTICATED")
        return 0
    print("RESULT=MCP_INITIALIZE_REJECTED")
    print("An access token was issued, but the MCP initialize request was not accepted.")
    print("WWW_AUTHENTICATE_PRESENT=" + ("yes" if bool(header(init_headers, "WWW-Authenticate")) else "no"))
    return 10


if __name__ == "__main__":
    try:
        sys.exit(main())
    except ProbeError as exc:
        print(f"RESULT={exc}")
        sys.exit(20)
