#!/usr/bin/env python3
"""Read-only MOEX ISS probe; TLS verification is always enabled."""
import json
import ssl
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

ISS = "https://iss.moex.com/iss"
URLS = [
    f"{ISS}/statistics/engines/stock/splits.json?iss.meta=off",
    "http://iss.moex.com/iss/statistics/engines/stock/splits.json?iss.meta=off",
    f"{ISS}/cci/corp-actions/dividends.json?iss.meta=off",
]

def main():
    failed = False
    context = ssl.create_default_context()
    for url in URLS:
        print(f"\nURL {url}")
        try:
            request = Request(url, headers={"Accept": "application/json", "User-Agent": "moex-edge-readonly-research/1.0"})
            with urlopen(request, timeout=20, context=context if url.startswith("https:") else None) as response:
                raw = response.read(200_000).decode("utf-8", "replace")
                print("HTTP", response.status, "FINAL_URL", response.geturl(), "CONTENT_TYPE", response.headers.get("Content-Type"))
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
