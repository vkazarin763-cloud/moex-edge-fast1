"""Fail-closed portfolio eligibility: only account-confirmed Finam buyable assets."""
from __future__ import annotations
import json
from pathlib import Path
from typing import Any

CONFIG_PATH = Path("experimental_portfolio/finam_allowlist.json")
UNIVERSE_SYMBOLS = {item["symbol"] for item in __import__("experimental_portfolio.engine", fromlist=["UNIVERSE"]).UNIVERSE}

def load_finam_allowlist(path: Path = CONFIG_PATH) -> dict[str, Any]:
    raw=json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw,dict): raise ValueError("Finam allowlist must be a JSON object")
    entries=raw.get("instruments",[])
    if not isinstance(entries,list): raise ValueError("allowlist instruments must be a list")
    allowed=set(); blocked={}
    for entry in entries:
        if not isinstance(entry,dict) or not isinstance(entry.get("symbol"),str):
            raise ValueError("invalid allowlist entry")
        symbol=entry["symbol"]
        if symbol not in UNIVERSE_SYMBOLS: raise ValueError(f"unknown portfolio symbol: {symbol}")
        status=entry.get("account_buy_permission")
        if status=="BUY_ALLOWED" and entry.get("verified_account_access") is True and entry.get("verified_at"):
            allowed.add(symbol)
        else:
            blocked[symbol]=status or "NOT_VERIFIED"
    return {"allowed_symbols":sorted(allowed),"blocked_symbols":blocked,
      "verification_source":raw.get("verification_source","unknown"),
      "account_scope":raw.get("account_scope","unknown"),
      "last_verified":raw.get("last_verified"),
      "fail_closed":True}
