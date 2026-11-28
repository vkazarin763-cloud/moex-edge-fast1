#!/usr/bin/env python3
"""Read-only live probe of public MOEX ISS dividend endpoints."""
import json
import os
import ssl
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

BASE = "https://iss.moex.com/iss"
URLS = [
    f"{BASE}/securities/{ticker}/dividends.json?iss.meta=off"
    for ticker in ("SBER", "GMKN", "PLZL")
] + [f"{BASE}/cci/corp-actions/dividends.json?iss.meta=off&limit=5"]

def main():
    failed = False
    for url in URLS:
        print(f"\nURL {url}")
        try:
            request = Request(url, headers={"Accept": "application/json", "User-Agent": "moex-edge-readonly-research/1.0"})
            context = ssl.create_default_context()
            insecure_diagnostic = os.getenv("MOEX_ISS_DIAGNOSTIC_INSECURE_TLS") == "1"
            if insecure_diagnostic:
                # Diagnostic only: this public read-only probe must never feed production data.
                context.check_hostname = False
                context.verify_mode = ssl.CERT_NONE
                print("TLS_VERIFY DISABLED_FOR_DIAGNOSTIC_ONLY")
            with urlopen(request, timeout=20, context=context) as response:
                raw = response.read(200_000).decode("utf-8", "replace")
                print("HTTP", response.status, "CONTENT_TYPE", response.headers.get("Content-Type"))
            try:
                payload = json.loads(raw)
            except json.JSONDecodeError:
                print("NON_JSON_BODY", raw[:500].replace("\n", " "))
                failed = True
                continue
            print("TOP_LEVEL_KEYS", sorted(payload)[:30])
            for key, block in payload.items():
                if isinstance(block, dict) and "columns" in block:
                    print("BLOCK", key, "COLUMNS", block.get("columns"))
                    rows = block.get("data") or []
                    print("ROW_COUNT_IN_RESPONSE", len(rows), "SAMPLE_ROWS", rows[:2])
            if not any(isinstance(v, dict) and "columns" in v for v in payload.values()):
                print("JSON_SAMPLE", json.dumps(payload, ensure_ascii=False)[:1200])
        except HTTPError as exc:
            body = exc.read(1000).decode("utf-8", "replace")
            print("HTTP_ERROR", exc.code, "BODY", body[:500].replace("\n", " "))
            failed = True
        except (URLError, TimeoutError) as exc:
            print("NETWORK_ERROR", type(exc).__name__, str(exc)[:300])
            failed = True
    print("\nPROBE_RESULT", "SOME_ENDPOINTS_FAILED" if failed else "ALL_ENDPOINTS_RESPONDED")
    # Endpoint-level failures are diagnostic findings, not a failing code test.
    return 0

if __name__ == "__main__":
    import contextlib
    import io
    from pathlib import Path
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        exit_code = main()
    output = buffer.getvalue()
    print(output, end="")
    artifact_dir = Path("research_output")
    artifact_dir.mkdir(exist_ok=True)
    (artifact_dir / "moex_iss_corporate_actions_probe.txt").write_text(output, encoding="utf-8")
    raise SystemExit(exit_code)
