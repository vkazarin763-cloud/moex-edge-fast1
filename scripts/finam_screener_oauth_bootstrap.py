"""Read-only Finam AI Screener OAuth refresh + MCP capability check.

This is a bootstrap gate, not the 44-symbol data collector. It verifies that a
refresh token can obtain an access token and that the authenticated MCP server
exposes screen_securities. It never calls account, portfolio, alert, preset,
order, or trading tools, and never prints credentials or response bodies.
"""
from __future__ import annotations

import json
import os
import re
import sys
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen

MCP_URL = "https://ai.finam.ru/mcp"
PROTOCOL_VERSION = "2025-03-26"
TIMEOUT = 20


class SafeError(RuntimeError):
    pass


def http(url: str, *, method: str = "GET", headers=None, body=None):
    request = Request(url, data=body, headers=headers or {}, method=method)
    try:
        with urlopen(request, timeout=TIMEOUT) as response:
            return response.status, dict(response.headers.items()), response.read(1_000_000)
    except HTTPError as exc:
        # Do not propagate or print provider response bodies: they may contain
        # authentication diagnostics or other sensitive material.
        return exc.code, dict(exc.headers.items()), b""
    except (URLError, TimeoutError) as exc:
        raise SafeError(f"NETWORK_ERROR:{type(exc).__name__}") from None


def parse_json(raw: bytes, label: str):
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise SafeError(f"{label}_INVALID_JSON") from None
    if not isinstance(value, dict):
        raise SafeError(f"{label}_INVALID_RESPONSE")
    return value


def get_header(headers, wanted):
    return next((v for k, v in headers.items() if k.lower() == wanted.lower()), "")


def metadata_url(challenge: str):
    match = re.search(r'resource_metadata\\s*=\\s*"([^"]+)"', challenge, re.I)
    if not match:
        match = re.search(r'resource_metadata\\s*=\\s*([^,\\s]+)', challenge, re.I)
    if not match:
        raise SafeError("OAUTH_RESOURCE_METADATA_NOT_ADVERTISED")
    url = match.group(1).strip('"')
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.netloc:
        raise SafeError("UNSAFE_RESOURCE_METADATA_URL")
    return url


def oauth_discovery(issuer: str):
    parsed = urlparse(issuer)
    if parsed.scheme != "https" or not parsed.netloc:
        raise SafeError("UNSAFE_OAUTH_ISSUER")
    path = parsed.path.rstrip("/")
    url = f"https://{parsed.netloc}/.well-known/oauth-authorization-server{path}"
    status, _, raw = http(url)
    if not 200 <= status < 300:
        raise SafeError(f"OAUTH_DISCOVERY_HTTP_{status}")
    return parse_json(raw, "OAUTH_DISCOVERY")


def refresh_access_token(oauth, client_id, client_secret, refresh_token):
    token_url = oauth.get("token_endpoint")
    if not isinstance(token_url, str) or not token_url.startswith("https://"):
        raise SafeError("OAUTH_TOKEN_ENDPOINT_INVALID")
    methods = oauth.get("token_endpoint_auth_methods_supported") or []
    form = {"grant_type": "refresh_token", "refresh_token": refresh_token}
    headers = {"Content-Type": "application/x-www-form-urlencoded",
               "Accept": "application/json"}
    if "client_secret_post" in methods:
        form.update({"client_id": client_id, "client_secret": client_secret})
    else:
        import base64
        raw = f"{client_id}:{client_secret}".encode()
        headers["Authorization"] = "Basic " + base64.b64encode(raw).decode("ascii")
    status, _, raw = http(token_url, method="POST", headers=headers,
                          body=urlencode(form).encode("ascii"))
    if not 200 <= status < 300:
        raise SafeError(f"OAUTH_REFRESH_REJECTED_HTTP_{status}")
    payload = parse_json(raw, "OAUTH_TOKEN")
    token = payload.get("access_token")
    if not isinstance(token, str) or not token:
        raise SafeError("OAUTH_ACCESS_TOKEN_MISSING")
    # Some providers rotate refresh tokens. A rotated value cannot be written
    # back to GitHub Secrets by this workflow; stop rather than silently lose it.
    rotated = payload.get("refresh_token")
    if rotated and rotated != refresh_token:
        raise SafeError("REFRESH_TOKEN_ROTATED_UPDATE_GITHUB_SECRET")
    return token


def parse_mcp_response(raw: bytes):
    text = raw.decode("utf-8", errors="replace")
    # Streamable HTTP may return JSON or SSE. Extract only JSON data frames.
    chunks = []
    if "data:" in text:
        for line in text.splitlines():
            if line.startswith("data:"):
                data = line[5:].strip()
                if data and data != "[DONE]":
                    chunks.append(data)
    else:
        chunks.append(text.strip())
    if not any(chunks):
        return {}
    for chunk in reversed(chunks):
        try:
            value = json.loads(chunk)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
    raise SafeError("MCP_RESPONSE_NOT_JSON")


def mcp_post(token, payload, session_id=None):
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
        "MCP-Protocol-Version": PROTOCOL_VERSION,
        "User-Agent": "moex-edge-finam-readonly-bootstrap/1.0",
    }
    if session_id:
        headers["MCP-Session-Id"] = session_id
    status, response_headers, raw = http(
        MCP_URL, method="POST", headers=headers,
        body=json.dumps(payload).encode("utf-8")
    )
    if not 200 <= status < 300:
        raise SafeError(f"MCP_HTTP_{status}")
    if payload.get("method") and "id" not in payload and not raw.strip():
        return {}, response_headers
    return parse_mcp_response(raw), response_headers


def main():
    client_id = os.environ.get("FINAM_MCP_ID", "").strip()
    client_secret = os.environ.get("FINAM_MCP_TOKEN", "").strip()
    refresh_token = os.environ.get("FINAM_MCP_REFRESH_TOKEN", "").strip()
    if not all((client_id, client_secret, refresh_token)):
        raise SafeError("REQUIRED_GITHUB_SECRETS_MISSING")

    # Discover the published OAuth metadata through the endpoint's challenge.
    status, headers, _ = http(
        MCP_URL, method="POST",
        headers={"Content-Type": "application/json",
                 "Accept": "application/json, text/event-stream",
                 "MCP-Protocol-Version": PROTOCOL_VERSION},
        body=json.dumps({
            "jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {"protocolVersion": PROTOCOL_VERSION,
                       "capabilities": {},
                       "clientInfo": {"name": "moex-edge-bootstrap", "version": "1.0"}}
        }).encode("utf-8")
    )
    if status != 401:
        raise SafeError(f"EXPECTED_OAUTH_CHALLENGE_HTTP_401_GOT_{status}")
    resource_url = metadata_url(get_header(headers, "WWW-Authenticate"))
    meta_status, _, meta_raw = http(resource_url)
    if not 200 <= meta_status < 300:
        raise SafeError(f"OAUTH_RESOURCE_METADATA_HTTP_{meta_status}")
    resource = parse_json(meta_raw, "OAUTH_RESOURCE_METADATA")
    issuers = resource.get("authorization_servers") or []
    if not issuers:
        raise SafeError("OAUTH_AUTHORIZATION_SERVER_NOT_ADVERTISED")
    oauth = oauth_discovery(str(issuers[0]))
    grants = oauth.get("grant_types_supported") or []
    if "refresh_token" not in grants:
        raise SafeError("REFRESH_TOKEN_GRANT_NOT_ADVERTISED")

    access_token = refresh_access_token(oauth, client_id, client_secret, refresh_token)
    init, init_headers = mcp_post(access_token, {
        "jsonrpc": "2.0", "id": 1, "method": "initialize",
        "params": {"protocolVersion": PROTOCOL_VERSION,
                   "capabilities": {},
                   "clientInfo": {"name": "moex-edge-readonly-bootstrap", "version": "1.0"}}
    })
    if init.get("error"):
        raise SafeError("MCP_INITIALIZE_REJECTED")
    session_id = get_header(init_headers, "Mcp-Session-Id")
    # Stateless MCP endpoints may omit a session ID; retain protocol version.
    mcp_post(access_token, {"jsonrpc": "2.0", "method": "notifications/initialized",
                            "params": {}}, session_id)
    listed, _ = mcp_post(access_token, {
        "jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}
    }, session_id)
    if listed.get("error"):
        raise SafeError("MCP_TOOLS_LIST_REJECTED")
    tools = listed.get("result", {}).get("tools", [])
    names = sorted(t.get("name", "") for t in tools if isinstance(t, dict))
    if "screen_securities" not in names:
        raise SafeError("SCREEN_SECURITIES_TOOL_NOT_AVAILABLE")
    print("RESULT=AUTHENTICATED_READONLY_MCP_READY")
    print("SCREEN_SECURITIES=available")
    print(f"MCP_TOOL_COUNT={len(names)}")
    print("No data query was made; no account or trading tools were called.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SafeError as exc:
        print(f"RESULT={exc}")
        sys.exit(1)
