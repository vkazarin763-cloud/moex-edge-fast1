#!/usr/bin/env python3
"""Read-only Finam weekly-history quality probe for account-buyable MOEX shares/funds."""
from __future__ import annotations
import json, math, os, time
from collections import Counter
from datetime import datetime, timedelta, timezone
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode

BASE = "https://api.finam.ru"
MIC = "MISX"
MIN_VALID_WEEKLY_BARS = 200
UNIVERSE = {
    "equity": ["AFKS","AFLT","ALRS","BSPB","CBOM","CHMF","CNRU","DOMRF","ENPG","FLOT","GAZP","GMKN","HEAD","IRAO","LKOH","MAGN","MDMG","MOEX","MTSS","NLMK","NVTK","OZON","PHOR","PLZL","POSI","RAGR","RENI","ROSN","RTKM","RUAL","SBER","SBERP","SNGS","SNGSP","SVCB","T","TATN","TATNP","TRNFP","UGLD","VKCO","VTBR","X5","YDEX"],
    "fund": ["AKME","AKMM","AMNR","AMNY","AMRE","AMRH","BCSD","DIVD","EQMX","GOLD","LQDT","SBCB","SBGB","SBMM","SBMX","SBRB","TBRU","TGLD","TMOS"],
}

def api(method, path, token=None, body=None):
    headers = {"Accept": "application/json", "Content-Type": "application/json"}
    if token:
        headers["Authorization"] = "Bearer " + token
    req = Request(BASE + path, headers=headers,
                  data=json.dumps(body).encode() if body is not None else None,
                  method=method)
    try:
        with urlopen(req, timeout=30) as response:
            return json.loads(response.read().decode())
    except HTTPError as exc:
        raise RuntimeError("HTTP_" + str(exc.code)) from None
    except (URLError, TimeoutError) as exc:
        raise RuntimeError("NETWORK_" + type(exc).__name__) from None

def bar_date(value):
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value, timezone.utc).date().isoformat()
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).date().isoformat()
    except ValueError:
        return None

def inspect_bars(rows):
    by_date = {}
    invalid = 0
    undated = 0
    for bar in rows:
        day = bar_date(bar.get("timestamp") or bar.get("date"))
        if day is None:
            undated += 1
            continue
        try:
            values = []
            for key in ("open", "high", "low", "close"):
                raw = bar[key]
                values.append(float(raw.get("value") if isinstance(raw, dict) else raw))
            o, h, low, c = values
            if not all(math.isfinite(x) and x > 0 for x in values):
                raise ValueError()
            if h < max(o, low, c) or low > min(o, h, c):
                raise ValueError()
        except (KeyError, TypeError, ValueError, OverflowError):
            invalid += 1
            continue
        if day in by_date:
            invalid += 1
            continue
        by_date[day] = {"date": day, "open": o, "high": h, "low": low, "close": c}
    dates = sorted(by_date)
    return {
        "valid": len(dates), "invalid_or_duplicate": invalid, "undated": undated,
        "first": dates[0] if dates else None, "last": dates[-1] if dates else None,
    }

def main():
    secret = os.getenv("FINAM_API_SECRET", "").strip()
    account = os.getenv("FINAM_ACCOUNT_ID", "").strip()
    if not secret or not account:
        print("MULTIASSET_HISTORY=FAIL_CLOSED_SECRETS_MISSING")
        return 2
    try:
        token = api("POST", "/v1/sessions", body={"secret": secret}).get("token")
        if not token:
            raise RuntimeError("SESSION_TOKEN_MISSING")
    except Exception as exc:
        print("MULTIASSET_HISTORY=FAIL_CLOSED_AUTH_" + str(exc)[:80])
        return 2

    end = datetime.now(timezone.utc)
    start = end - timedelta(days=365 * 5)  # Finam weekly history is limited to 5 years.
    interval = urlencode({
        "timeframe": "TIME_FRAME_W",
        "interval.start_time": start.isoformat(),
        "interval.end_time": end.isoformat(),
    })
    outcomes = {kind: [] for kind in UNIVERSE}
    errors = Counter()
    for kind, tickers in UNIVERSE.items():
        for ticker in tickers:
            symbol = f"{ticker}@{MIC}"
            result = {"symbol": symbol, "asset_class": kind, "buy_permission": False}
            try:
                encoded = quote(symbol, safe="")
                query = urlencode({"account_id": account})
                api("GET", f"/v1/assets/{encoded}?{query}", token)
                params = api("GET", f"/v1/assets/{encoded}/params?{query}", token)
                longable = params.get("longable")
                if isinstance(longable, dict):
                    longable = longable.get("value")
                result["buy_permission"] = (
                    params.get("is_tradable") is True and longable in ("AVAILABLE", 1, "1")
                )
                if not result["buy_permission"]:
                    result["blocked_reason"] = "ACCOUNT_BUY_PERMISSION_NOT_CONFIRMED"
                else:
                    data = api("GET", f"/v1/instruments/{encoded}/bars?{interval}", token)
                    stats = inspect_bars(data.get("bars", []))
                    result.update(stats)
                    result["history_sufficient"] = stats["valid"] >= MIN_VALID_WEEKLY_BARS
                    if not result["history_sufficient"]:
                        result["blocked_reason"] = "INSUFFICIENT_VALID_WEEKLY_HISTORY"
            except RuntimeError as exc:
                result["blocked_reason"] = str(exc)
                errors[kind + ":" + str(exc)] += 1
            outcomes[kind].append(result)
            time.sleep(0.12)

    print("MULTIASSET_HISTORY=COMPLETE")
    for kind, rows in outcomes.items():
        approved = [x for x in rows if x.get("buy_permission")]
        sufficient = [x for x in rows if x.get("buy_permission") and x.get("history_sufficient")]
        print(kind.upper() + "_SUMMARY=" + json.dumps({
            "checked": len(rows),
            "account_buyable": len(approved),
            "history_sufficient_200w": len(sufficient),
            "history_insufficient": sum(1 for x in approved if x.get("history_sufficient") is False),
            "api_errors": sum(1 for x in rows if "blocked_reason" in x and x.get("buy_permission") is not True),
            "qualified_symbols": sorted(x["symbol"] for x in sufficient),
        }, sort_keys=True))
        print(kind.upper() + "_DETAILS=" + json.dumps(rows, sort_keys=True))
    print("ERROR_COUNTS=" + json.dumps(dict(sorted(errors.items())), sort_keys=True))
    print("SAFETY=READ_ONLY_NO_ORDER_ENDPOINTS_NO_ALLOWLIST_WRITES")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
