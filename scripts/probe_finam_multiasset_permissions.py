#!/usr/bin/env python3
"""Read-only Finam account-permission probe for MOEX equities and funds.

Never calls order endpoints. Output is sanitized: no account ID, token or API payload.
"""
from __future__ import annotations
import json, os, time
from collections import Counter
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode

BASE = "https://api.finam.ru"
MIC = "MISX"
UNIVERSE = {
    "equity": ["AFKS","AFLT","ALRS","BSPB","CBOM","CHMF","CNRU","DOMRF","ENPG","FLOT","GAZP","GMKN","HEAD","IRAO","LKOH","MAGN","MDMG","MOEX","MTSS","NLMK","NVTK","OZON","PHOR","PLZL","POSI","RAGR","RENI","ROSN","RTKM","RUAL","SBER","SBERP","SNGS","SNGSP","SVCB","T","TATN","TATNP","TRNFP","UGLD","VKCO","VTBR","X5","YDEX"],
    "fund": ["AKME","AKMM","AMNR","AMNY","AMRE","AMRH","BCSD","DIVD","EQMX","GOLD","LQDT","SBCB","SBGB","SBMM","SBMX","SBRB","TBRU","TGLD","TMOS"],
}

def call(method: str, path: str, token: str | None = None, body=None):
    headers = {"Accept": "application/json", "Content-Type": "application/json"}
    if token:
        headers["Authorization"] = "Bearer " + token
    req = Request(BASE + path, headers=headers,
                  data=json.dumps(body).encode() if body is not None else None,
                  method=method)
    try:
        with urlopen(req, timeout=25) as response:
            return json.loads(response.read().decode())
    except HTTPError as exc:
        raise RuntimeError("HTTP_" + str(exc.code)) from None
    except (URLError, TimeoutError) as exc:
        raise RuntimeError("NETWORK_" + type(exc).__name__) from None

def main() -> int:
    secret = os.getenv("FINAM_API_SECRET", "").strip()
    account = os.getenv("FINAM_ACCOUNT_ID", "").strip()
    if not secret or not account:
        print("MULTIASSET_PERMISSION_PROBE=FAIL_CLOSED_SECRETS_MISSING")
        return 2
    try:
        token = call("POST", "/v1/sessions", body={"secret": secret}).get("token")
        if not token:
            raise RuntimeError("SESSION_TOKEN_MISSING")
    except Exception as exc:
        print("MULTIASSET_PERMISSION_PROBE=FAIL_CLOSED_AUTH_" + str(exc)[:80])
        return 2

    totals = Counter()
    by_class = {name: {"checked": 0, "found": 0, "buy_allowed": []} for name in UNIVERSE}
    for asset_class, tickers in UNIVERSE.items():
        for ticker in tickers:
            symbol = f"{ticker}@{MIC}"
            by_class[asset_class]["checked"] += 1
            try:
                encoded = quote(symbol, safe="")
                query = urlencode({"account_id": account})
                call("GET", f"/v1/assets/{encoded}?{query}", token)
                by_class[asset_class]["found"] += 1
                params = call("GET", f"/v1/assets/{encoded}/params?{query}", token)
                longable = params.get("longable")
                if isinstance(longable, dict):
                    longable = longable.get("value")
                tradable = params.get("is_tradable") is True
                if tradable and longable in ("AVAILABLE", 1, "1"):
                    by_class[asset_class]["buy_allowed"].append(ticker)
                    totals[asset_class + ":BUY_ALLOWED"] += 1
                else:
                    totals[asset_class + ":BLOCKED_OR_AMBIGUOUS"] += 1
            except RuntimeError as exc:
                code = str(exc)
                totals[asset_class + ":" + ("NOT_LISTED" if code in ("HTTP_400", "HTTP_404") else "API_ERROR")] += 1
            time.sleep(0.15)

    print("MULTIASSET_PERMISSION_PROBE=COMPLETE")
    print("COUNTS=" + json.dumps(dict(sorted(totals.items())), sort_keys=True))
    for asset_class, data in by_class.items():
        print(asset_class.upper() + "_SUMMARY=" + json.dumps({
            "checked": data["checked"], "found": data["found"],
            "buy_allowed_count": len(data["buy_allowed"]),
            "buy_allowed_symbols": data["buy_allowed"],
        }, sort_keys=True))
    print("SAFETY=READ_ONLY_NO_ORDER_ENDPOINTS")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
